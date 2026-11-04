"""Wires app.core.config.settings into concrete DecisionBackend/
ExtractionBackend/InvestigatorLike instances behind the record/replay
cache (app/backends/cache.py, app/backends/extract_cache.py,
app/reconcile/cache.py), per DECISION_BACKEND and model_cache_mode.
"""

from __future__ import annotations

from app.backends.base import DecisionBackend
from app.backends.cache import CachedBackend
from app.backends.claude_backend import ClaudeBackend
from app.backends.claude_extractor import ClaudeExtractor
from app.backends.extract_cache import CachedExtractor
from app.backends.jev_backend import JevBackend
from app.core.config import Settings
from app.reconcile.cache import CachedInvestigator
from app.reconcile.investigator import Investigator
from app.tools_mcp.server import build_mcp_server


def build_claude_backend(settings: Settings) -> CachedBackend:
    return CachedBackend(
        ClaudeBackend(model=settings.model_classify_fallback),
        model=settings.model_classify_fallback,
        cache_root=settings.model_cache_root,
        mode=settings.model_cache_mode,
    )


def build_jev_backend(settings: Settings) -> CachedBackend | None:
    if settings.jev_api_key is None:
        return None
    return CachedBackend(
        JevBackend(api_key=settings.jev_api_key, model=settings.jev_model),
        model=settings.jev_model,
        cache_root=settings.model_cache_root,
        mode=settings.model_cache_mode,
    )


def build_primary_and_fallback(
    settings: Settings,
) -> tuple[DecisionBackend, DecisionBackend | None]:
    """CLAUDE.md invariant 6: DECISION_BACKEND=claude must run end to
    end with zero Jev involvement - the claude branch below never
    looks at jev_api_key at all, not even to check it's absent.
    """
    claude = build_claude_backend(settings)
    if settings.decision_backend == "claude":
        return claude, None

    jev = build_jev_backend(settings)
    if jev is None:
        raise RuntimeError("DECISION_BACKEND=jev but no JEV_API_KEY is configured")
    return jev, claude


def build_extractor(settings: Settings) -> CachedExtractor:
    return CachedExtractor(
        ClaudeExtractor(model=settings.model_extract),
        model=settings.model_extract,
        cache_root=settings.model_cache_root,
        mode=settings.model_cache_mode,
    )


def build_investigator(settings: Settings) -> CachedInvestigator:
    mcp = build_mcp_server(
        mode=settings.mcp_tool_mode,
        fixtures_root=settings.registry_fixtures_root,
        rule_pack_path=settings.rule_pack_path,
        leie_cache_path=settings.leie_cache_path,
    )
    raw_investigator = Investigator(
        mcp, model=settings.model_investigate, max_tool_calls=settings.investigator_max_tool_calls
    )
    return CachedInvestigator(
        raw_investigator,
        model=settings.model_investigate,
        cache_root=settings.model_cache_root,
        mode=settings.model_cache_mode,
    )
