"""Envelope encryption key management (SPEC.md section 7.1): a KeyManager
wraps and unwraps per-case data encryption keys (DEKs) under a master key
it never exposes. `LocalKeyManager` is the dev/demo implementation (SPEC
section 7.1: "LocalKeyManager now, AWS KMS adapter stubbed") — production
would implement this same Protocol against AWS KMS instead; no stub class
is written for that here since there's nothing to call yet (CLAUDE.md:
don't build for hypothetical future requirements).

Not a production key-management story even with `master_key` set
(README.md's caveat) - a real deployment should load the master key
from AWS KMS/Secrets Manager/Vault directly rather than putting a
long-lived raw key in a process's environment at all. `master_key`
here is the one meaningful step up from the file fallback that's still
in scope for this project: it at least gets the key off local disk and
out of a world where "whoever can read the container's filesystem can
read the master key."
"""

from __future__ import annotations

import base64
import stat
from pathlib import Path
from typing import Protocol

from app.vault import aead


class KeyManager(Protocol):
    def wrap_key(self, data_key: bytes, aad: bytes) -> bytes: ...
    def unwrap_key(self, wrapped: bytes, aad: bytes) -> bytes: ...


class LocalKeyManager:
    """Wraps/unwraps under a master key sourced from, in order:

    1. `master_key_b64` (SPEC section 12's MASTER_KEY env var, base64 of
       32 raw bytes) - whatever secret store the deployment actually
       uses injects this; never typed in by hand, never committed.
    2. `master_key_path` - a local file, generated on first use if it
       doesn't exist, created with mode 0600 (owner read/write only).
       Dev/demo fallback only, not a production key management story -
       CLAUDE.md invariant 4: never commit this file; the default path
       sits under the gitignored `data/` directory.
    """

    def __init__(self, master_key_path: Path, master_key_b64: str | None = None) -> None:
        self._master_key = (
            self._decode_master_key(master_key_b64)
            if master_key_b64 is not None
            else self._load_or_create_master_key(master_key_path)
        )

    @staticmethod
    def _decode_master_key(b64: str) -> bytes:
        key = base64.b64decode(b64)
        if len(key) != aead.KEY_BITS // 8:
            raise ValueError(
                f"MASTER_KEY: expected a {aead.KEY_BITS}-bit (base64-encoded) master key, "
                f"got {len(key) * 8} bits"
            )
        return key

    @staticmethod
    def _load_or_create_master_key(path: Path) -> bytes:
        if path.exists():
            key = path.read_bytes()
            if len(key) != aead.KEY_BITS // 8:
                raise ValueError(
                    f"{path}: expected a {aead.KEY_BITS}-bit master key, "
                    f"got {len(key) * 8} bits"
                )
            return key
        key = aead.generate_key()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(key)
        # 0600 (owner read/write only). POSIX-only in practice - Windows
        # has no equivalent permission bits and chmod there only toggles
        # the read-only attribute; this is a no-op hardening step on
        # local Windows dev and a real one in the (Linux) container.
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return key

    def wrap_key(self, data_key: bytes, aad: bytes) -> bytes:
        return aead.seal(self._master_key, data_key, aad)

    def unwrap_key(self, wrapped: bytes, aad: bytes) -> bytes:
        return aead.open_(self._master_key, wrapped, aad)
