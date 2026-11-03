from pathlib import Path

import pytest

from app.vault.blob_store import LocalBlobStore


def test_put_get_round_trip(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path / "blobs")
    store.put("abc123", b"ciphertext bytes")
    assert store.get("abc123") == b"ciphertext bytes"


def test_exists(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path / "blobs")
    assert not store.exists("abc123")
    store.put("abc123", b"data")
    assert store.exists("abc123")


def test_creates_root_directory_on_init(tmp_path: Path) -> None:
    root = tmp_path / "does" / "not" / "exist" / "yet"
    assert not root.exists()
    LocalBlobStore(root)
    assert root.exists()


@pytest.mark.parametrize("bad_key", ["", "a/b", "a\\b", "..", "../escape"])
def test_rejects_path_traversal_keys(tmp_path: Path, bad_key: str) -> None:
    store = LocalBlobStore(tmp_path / "blobs")
    with pytest.raises(ValueError, match="invalid blob key"):
        store.put(bad_key, b"data")
