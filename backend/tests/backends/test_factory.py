from __future__ import annotations

from pathlib import Path

import pytest

from app.backends.cache import CachedBackend
from app.backends.factory import build_jev_backend, build_primary_and_fallback
from app.core.config import Settings


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "model_cache_root": tmp_path,
        "model_cache_mode": "replay",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_decision_backend_claude_never_requires_or_touches_jev(tmp_path: Path) -> None:
    """CLAUDE.md invariant 6: DECISION_BACKEND=claude must run end to
    end - confirms no JEV_API_KEY is needed at all on this path."""
    settings = _settings(tmp_path, decision_backend="claude", jev_api_key=None)
    primary, fallback = build_primary_and_fallback(settings)
    assert primary.name == "claude"
    assert fallback is None


def test_decision_backend_jev_with_a_key_returns_jev_primary_and_claude_fallback(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, decision_backend="jev", jev_api_key="test-key")
    primary, fallback = build_primary_and_fallback(settings)
    assert primary.name == "jev"
    assert fallback is not None and fallback.name == "claude"


def test_decision_backend_jev_without_a_key_raises(tmp_path: Path) -> None:
    settings = _settings(tmp_path, decision_backend="jev", jev_api_key=None)
    with pytest.raises(RuntimeError, match="JEV_API_KEY"):
        build_primary_and_fallback(settings)


def test_build_jev_backend_returns_none_without_a_key(tmp_path: Path) -> None:
    assert build_jev_backend(_settings(tmp_path, jev_api_key=None)) is None


def test_build_jev_backend_returns_a_cached_backend_with_a_key(tmp_path: Path) -> None:
    backend = build_jev_backend(_settings(tmp_path, jev_api_key="test-key"))
    assert isinstance(backend, CachedBackend)
    assert backend.name == "jev"
