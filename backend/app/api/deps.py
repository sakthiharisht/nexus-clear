"""FastAPI dependency providers: DB session (reuses app.core.db.get_session),
plus the loaded rule pack, vault components, and model backends as
process-lifetime singletons (`lru_cache` on a zero-argument function) —
constructing a LocalKeyManager, reloading the rule pack, or rebuilding
a backend on every request would be wasteful for no benefit.
"""

from __future__ import annotations

from functools import lru_cache

from app.backends.base import DecisionBackend
from app.backends.extract_cache import CachedExtractor
from app.backends.factory import build_extractor, build_investigator, build_primary_and_fallback
from app.core.config import settings
from app.core.db import get_session
from app.reconcile.cache import CachedInvestigator
from app.report.cache import CachedPhraser
from app.report.factory import build_phraser
from app.rules.loader import load_rule_pack
from app.rules.schema import RulePack
from app.vault.blob_store import BlobStore, LocalBlobStore
from app.vault.key_manager import KeyManager, LocalKeyManager

__all__ = [
    "get_session",
    "get_rule_pack",
    "get_key_manager",
    "get_blob_store",
    "get_primary_backend",
    "get_fallback_backend",
    "get_extractor",
    "get_investigator",
    "get_phraser",
]


@lru_cache(maxsize=1)
def get_rule_pack() -> RulePack:
    return load_rule_pack(settings.rule_pack_path)


@lru_cache(maxsize=1)
def get_key_manager() -> KeyManager:
    return LocalKeyManager(settings.master_key_path, settings.master_key)


@lru_cache(maxsize=1)
def get_blob_store() -> BlobStore:
    return LocalBlobStore(settings.blob_store_root)


@lru_cache(maxsize=1)
def _primary_and_fallback() -> tuple[DecisionBackend, DecisionBackend | None]:
    return build_primary_and_fallback(settings)


def get_primary_backend() -> DecisionBackend:
    return _primary_and_fallback()[0]


def get_fallback_backend() -> DecisionBackend | None:
    return _primary_and_fallback()[1]


@lru_cache(maxsize=1)
def get_extractor() -> CachedExtractor:
    return build_extractor(settings)


@lru_cache(maxsize=1)
def get_investigator() -> CachedInvestigator:
    return build_investigator(settings)


@lru_cache(maxsize=1)
def get_phraser() -> CachedPhraser:
    return build_phraser(settings)
