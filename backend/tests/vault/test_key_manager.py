import base64
import stat
import sys
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


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits don't apply on Windows")
def test_generated_master_key_file_is_mode_0600(tmp_path: Path) -> None:
    path = tmp_path / "master.key"
    LocalKeyManager(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_master_key_env_var_is_used_instead_of_the_file_when_set(tmp_path: Path) -> None:
    path = tmp_path / "master.key"
    path.write_bytes(aead.generate_key())  # a *different* key sitting on disk

    env_key = aead.generate_key()
    km = LocalKeyManager(path, base64.b64encode(env_key).decode())
    wrapped = km.wrap_key(b"0" * 32, aad=b"case-a")

    # A KeyManager loaded from the file key must NOT be able to unwrap
    # it - proving the env var's key, not the file's, actually sealed it.
    file_km = LocalKeyManager(path)
    with pytest.raises(InvalidTag):
        file_km.unwrap_key(wrapped, aad=b"case-a")

    # The file on disk is untouched - no fallback write happened.
    assert path.read_bytes() != env_key


def test_master_key_env_var_does_not_create_or_touch_the_file(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "master.key"
    LocalKeyManager(path, base64.b64encode(aead.generate_key()).decode())
    assert not path.exists()


def test_rejects_a_malformed_master_key_env_var(tmp_path: Path) -> None:
    bad_b64 = base64.b64encode(b"too short").decode()
    with pytest.raises(ValueError, match="MASTER_KEY"):
        LocalKeyManager(tmp_path / "master.key", bad_b64)
