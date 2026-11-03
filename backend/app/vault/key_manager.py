"""Envelope encryption key management (SPEC.md section 7.1): a KeyManager
wraps and unwraps per-case data encryption keys (DEKs) under a master key
it never exposes. `LocalKeyManager` is the dev/demo implementation (SPEC
section 7.1: "LocalKeyManager now, AWS KMS adapter stubbed") — production
would implement this same Protocol against AWS KMS instead; no stub class
is written for that here since there's nothing to call yet (CLAUDE.md:
don't build for hypothetical future requirements).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.vault import aead


class KeyManager(Protocol):
    def wrap_key(self, data_key: bytes) -> bytes: ...
    def unwrap_key(self, wrapped: bytes) -> bytes: ...


class LocalKeyManager:
    """Wraps/unwraps with a local master key file (AES-256-GCM).

    Dev/demo only, not a production key management story: generates the
    master key on first use if the file doesn't exist. CLAUDE.md invariant
    4 — never commit this file; MASTER_KEY_PATH should point under the
    gitignored `data/` directory.
    """

    def __init__(self, master_key_path: Path) -> None:
        self._master_key = self._load_or_create_master_key(master_key_path)

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
        return key

    def wrap_key(self, data_key: bytes) -> bytes:
        return aead.seal(self._master_key, data_key)

    def unwrap_key(self, wrapped: bytes) -> bytes:
        return aead.open_(self._master_key, wrapped)
