import pytest
from cryptography.exceptions import InvalidTag

from app.vault import aead


def test_round_trip() -> None:
    key = aead.generate_key()
    plaintext = b"synthetic document bytes, not a real credential"
    sealed = aead.seal(key, plaintext)
    assert aead.open_(key, sealed) == plaintext


def test_generated_key_is_256_bits() -> None:
    assert len(aead.generate_key()) == 32


def test_each_seal_uses_a_fresh_nonce() -> None:
    key = aead.generate_key()
    a = aead.seal(key, b"same plaintext")
    b = aead.seal(key, b"same plaintext")
    assert a != b  # different nonce -> different ciphertext even for identical input


def test_wrong_key_fails_to_open() -> None:
    sealed = aead.seal(aead.generate_key(), b"secret")
    with pytest.raises(InvalidTag):
        aead.open_(aead.generate_key(), sealed)


def test_tampered_ciphertext_fails_to_open() -> None:
    key = aead.generate_key()
    sealed = bytearray(aead.seal(key, b"secret"))
    sealed[-1] ^= 0xFF  # flip a bit in the auth tag
    with pytest.raises(InvalidTag):
        aead.open_(key, bytes(sealed))
