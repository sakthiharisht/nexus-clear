from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from app.vault import aead
from app.vault.key_manager import LocalKeyManager


def test_wrap_unwrap_round_trip(tmp_path: Path) -> None:
    km = LocalKeyManager(tmp_path / "master.key")
    data_key = aead.generate_key()
    wrapped = km.wrap_key(data_key)
    assert km.unwrap_key(wrapped) == data_key


def test_generates_a_master_key_on_first_use(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "master.key"
    assert not path.exists()
    LocalKeyManager(path)
    assert path.exists()
    assert len(path.read_bytes()) == 32


def test_reuses_an_existing_master_key(tmp_path: Path) -> None:
    path = tmp_path / "master.key"
    km1 = LocalKeyManager(path)
    wrapped = km1.wrap_key(b"0" * 32)

    km2 = LocalKeyManager(path)  # same file, fresh instance
    assert km2.unwrap_key(wrapped) == b"0" * 32


def test_two_key_managers_with_different_master_keys_cannot_cross_unwrap(
    tmp_path: Path,
) -> None:
    km1 = LocalKeyManager(tmp_path / "a.key")
    km2 = LocalKeyManager(tmp_path / "b.key")
    wrapped = km1.wrap_key(aead.generate_key())
    with pytest.raises(InvalidTag):
        km2.unwrap_key(wrapped)


def test_rejects_a_malformed_master_key_file(tmp_path: Path) -> None:
    path = tmp_path / "master.key"
    path.write_bytes(b"too short")
    with pytest.raises(ValueError, match="expected a 256-bit master key"):
        LocalKeyManager(path)
