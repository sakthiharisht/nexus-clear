"""Ciphertext storage (SPEC.md section 7.1): a BlobStore puts/gets opaque
bytes by key. `LocalBlobStore` is the dev/demo implementation ("Local
BlobStore now, S3 adapter stubbed") — stores files under a configured
root directory, named by the caller-supplied key (SHA-256 content hash in
practice, per SPEC section 7.1: "Store ciphertext named by hash").
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class BlobStore(Protocol):
    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        # Keys are always a sha256 hex digest or a document UUID in
        # practice; reject anything that could be a path-traversal
        # attempt regardless. ":" matters on Windows specifically: a
        # key like "D:secret" has no "/" or "\\" but pathlib's `/`
        # still treats the drive-letter prefix as anchored and
        # discards root entirely (confirmed empirically - root / "D:x"
        # returns "D:x", not a path under root).
        if not key or "/" in key or "\\" in key or ".." in key or ":" in key:
            raise ValueError(f"invalid blob key: {key!r}")
        return self._root / key

    def put(self, key: str, data: bytes) -> None:
        self._path_for(key).write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path_for(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path_for(key).exists()
