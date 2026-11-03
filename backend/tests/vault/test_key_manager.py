from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from app.vault import aead
from app.vault.key_manager import LocalKeyManager


def test_wrap_unwrap_round_trip(tmp_path: Path) -> None:
    km = LocalKeyManager(tmp_path / "master.key")
    data_key = aead.generate_key()
    wrapped = km.wrap_key(data_key, aad=b"case-a")
    assert km.unwrap_key(wrapped, aad=b"case-a") == data_key


def test_wrapped_key_cannot_be_unwrapped_under_a_different_aad(tmp_path: Path) -> None:
    km = LocalKeyManager(tmp_path / "master.key")
    wrapped = km.wrap_key(aead.generate_key(), aad=b"case-a")
    with pytest.raises(InvalidTag):
        km.unwrap_key(wrapped, aad=b"case-b")


def test_generates_a_master_key_on_first_use(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "master.key"
    assert not path.exists()
    LocalKeyManager(path)
    assert path.exists()
    assert len(path.read_bytes()) == 32


def test_reuses_an_existing_master_key(tmp_path: Path) -> None:
    path = tmp_path / "master.key"
    km1 = LocalKeyManager(path)
    wrapped = km1.wrap_key(b"0" * 32, aad=b"case-a")

    km2 = LocalKeyManager(path)  # same file, fresh instance
    assert km2.unwrap_key(wrapped, aad=b"case-a") == b"0" * 32


def test_two_key_managers_with_different_master_keys_cannot_cross_unwrap(
    tmp_path: Path,
) -> None:
    km1 = LocalKeyManager(tmp_path / "a.key")
    km2 = LocalKeyManager(tmp_path / "b.key")
    wrapped = km1.wrap_key(aead.generate_key(), aad=b"case-a")
    with pytest.raises(InvalidTag):
        km2.unwrap_key(wrapped, aad=b"case-a")


def test_rejects_a_malformed_master_key_file(tmp_path: Path) -> None:
    path = tmp_path / "master.key"
    path.write_bytes(b"too short")
    with pytest.raises(ValueError, match="expected a 256-bit master key"):
        LocalKeyManager(path)
