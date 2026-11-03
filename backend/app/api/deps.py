"""FastAPI dependency providers: DB session (reuses app.core.db.get_session),
plus the loaded rule pack and vault components as process-lifetime
singletons (`lru_cache` on a zero-argument function) — constructing a
LocalKeyManager or reloading the rule pack on every request would be
wasteful for no benefit.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.core.db import get_session
from app.rules.loader import load_rule_pack
from app.rules.schema import RulePack
from app.vault.blob_store import BlobStore, LocalBlobStore
from app.vault.key_manager import KeyManager, LocalKeyManager

__all__ = ["get_session", "get_rule_pack", "get_key_manager", "get_blob_store"]


@lru_cache(maxsize=1)
def get_rule_pack() -> RulePack:
    return load_rule_pack(settings.rule_pack_path)


@lru_cache(maxsize=1)
def get_key_manager() -> KeyManager:
    return LocalKeyManager(settings.master_key_path)


@lru_cache(maxsize=1)
def get_blob_store() -> BlobStore:
    return LocalBlobStore(settings.blob_store_root)
