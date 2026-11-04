"""Wires app.core.config.settings into a concrete SentencePhraser
behind the record/replay cache (app/report/cache.py), parallel to
app/backends/factory.py.
"""

from __future__ import annotations

from app.core.config import Settings
from app.report.cache import CachedPhraser
from app.report.claude_phraser import ClaudePhraser


def build_phraser(settings: Settings) -> CachedPhraser:
    return CachedPhraser(
        ClaudePhraser(model=settings.model_report),
        model=settings.model_report,
        cache_root=settings.model_cache_root,
        mode=settings.model_cache_mode,
    )
