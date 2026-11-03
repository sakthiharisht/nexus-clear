"""Wires app.core.config.settings into concrete DecisionBackend
instances behind the record/replay cache (app/backends/cache.py), per
DECISION_BACKEND.
"""

from __future__ import annotations

from app.backends.base import DecisionBackend
from app.backends.cache import CachedBackend
from app.backends.claude_backend import ClaudeBackend
from app.backends.jev_backend import JevBackend
from app.core.config import Settings


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
