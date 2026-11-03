"""Low-level AES-256-GCM seal/open, shared by key wrapping
(app/vault/key_manager.py) and document encryption (app/vault/service.py)
— both are "encrypt some bytes under some key", just applied to different
things (a data key vs. document content).

Verified against the current `cryptography` docs
(https://cryptography.io/en/latest/hazmat/primitives/aead/, checked
2026-11-03) before writing this: `AESGCM(key)` constructor,
`AESGCM.generate_key(bit_length)` classmethod, `encrypt(nonce, data,
associated_data)` / `decrypt(nonce, data, associated_data)` methods, a
12-byte (NIST-recommended) nonce that must never repeat for a given key,
and that the returned ciphertext already includes the 128-bit
authentication tag (no separate tag handling needed) — confirmed with a
local round-trip before relying on it.

`associated_data` is required (no default) rather than optional: GCM's
whole point for this project is binding ciphertext to the context it was
sealed under (which case, which document, which content hash) so a
blob or wrapped key moved/mixed up elsewhere fails to decrypt instead of
silently decrypting as something else's plaintext. Making callers pass
it explicitly, every time, is deliberate — see app/vault/service.py for
what the context actually contains.
"""

from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_SIZE = 12
KEY_BITS = 256


def generate_key() -> bytes:
    return AESGCM.generate_key(bit_length=KEY_BITS)


def seal(key: bytes, plaintext: bytes, associated_data: bytes) -> bytes:
    """A fresh random nonce, prepended to the ciphertext (nonces aren't
    secret — they only must never repeat for the same key, so storing one
    alongside its ciphertext is the standard pattern)."""
    nonce = os.urandom(NONCE_SIZE)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data)
    return nonce + ciphertext


def open_(key: bytes, blob: bytes, associated_data: bytes) -> bytes:
    nonce, ciphertext = blob[:NONCE_SIZE], blob[NONCE_SIZE:]
    return AESGCM(key).decrypt(nonce, ciphertext, associated_data)
