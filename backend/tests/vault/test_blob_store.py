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


@pytest.mark.parametrize(
    "bad_key",
    [
        "",
        "a/b",
        "a\\b",
        "..",
        "../escape",
        "/etc/passwd",
        "C:\\Windows\\evil",
        "D:secret",  # no "/" or "\\" - pathlib still treats this as drive-anchored on Windows
        "file.txt:hidden",  # NTFS alternate data stream syntax
    ],
)
def test_rejects_path_traversal_keys(tmp_path: Path, bad_key: str) -> None:
    store = LocalBlobStore(tmp_path / "blobs")
    with pytest.raises(ValueError, match="invalid blob key"):
        store.put(bad_key, b"data")


@pytest.mark.parametrize("bad_key", ["D:secret", "C:\\Windows\\evil"])
def test_rejected_keys_never_actually_escape_root(tmp_path: Path, bad_key: str) -> None:
    """Belt-and-suspenders: even if a future change weakened the key
    validation, confirm these specific keys would have landed outside
    `root` - the property the validation exists to prevent."""
    root = tmp_path / "blobs"
    escaped = root / bad_key
    assert root not in escaped.parents
