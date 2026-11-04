"""Record/replay cache for Investigator calls (CLAUDE.md: "LLM/Jev
calls go through the record/replay cache so CI is offline and
deterministic"). Parallel to app/backends/extract_cache.py's
CachedExtractor, but caches a whole investigation (one or more model
turns, one or more tool calls) rather than a single model call - the
Investigator's natural unit of work is "resolve this set of tasks,"
not "one request."
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.reconcile.investigator import (
    InvestigationResult,
    InvestigatorLike,
    NameMatchTask,
    RegistryTask,
)


class MissingFixtureError(RuntimeError):
    """Raised in "replay" mode when no cached investigation exists for
    this exact set of tasks - a cache miss fails loudly in CI instead
    of silently reaching the network."""


def cache_key(
    model: str, name_match_tasks: list[NameMatchTask], registry_tasks: list[RegistryTask]
) -> str:
    canonical = json.dumps(
        {
            "model": model,
            "name_match_tasks": [t.model_dump(mode="json") for t in name_match_tasks],
            "registry_tasks": [t.model_dump(mode="json") for t in registry_tasks],
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


class CachedInvestigator:
    def __init__(
        self, investigator: InvestigatorLike, *, model: str, cache_root: Path, mode: str
    ) -> None:
        self._investigator = investigator
        self._model = model
        self._cache_root = cache_root
        self._mode = mode

    def _path_for(
        self, name_match_tasks: list[NameMatchTask], registry_tasks: list[RegistryTask]
    ) -> Path:
        key = cache_key(self._model, name_match_tasks, registry_tasks)
        return self._cache_root / "claude" / f"reconcile-{key}.json"

    def investigate(
        self, *, name_match_tasks: list[NameMatchTask], registry_tasks: list[RegistryTask]
    ) -> InvestigationResult:
        path = self._path_for(name_match_tasks, registry_tasks)
        if path.exists():
            return InvestigationResult.model_validate_json(path.read_text(encoding="utf-8"))

        if self._mode == "replay":
            raise MissingFixtureError(
                f"no cached investigation for this task set (expected at {path}) - "
                "run with a live API key to seed it"
            )

        result = self._investigator.investigate(
            name_match_tasks=name_match_tasks, registry_tasks=registry_tasks
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return result
