"""Record/replay cache for model calls (CLAUDE.md: "LLM/Jev calls go
through the record/replay cache so CI is offline and deterministic.
Live runs refresh the cache."). Wraps any DecisionBackend; the wrapped
backend is only ever actually invoked in "record" mode, and even then
only on a genuine cache miss.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.backends.base import DecisionBackend
from app.backends.types import ClassificationResult, ClassifyInput


class MissingFixtureError(RuntimeError):
    """Raised in "replay" mode when no cached response exists for an
    input. A cache miss is a hard, specific error - never a silent
    live call - so an incomplete fixture set fails loudly in CI
    instead of nondeterministically hitting the network.
    """


def cache_key(backend_name: str, model: str, classify_input: ClassifyInput) -> str:
    canonical = json.dumps(
        {
            "backend": backend_name,
            "model": model,
            "input": classify_input.model_dump(mode="json"),
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


class CachedBackend:
    """Satisfies DecisionBackend itself, so it's a drop-in wrapper
    anywhere a backend is expected (app/backends/policy.py, the eval
    runner): `CachedBackend(ClaudeBackend(...), ...)` IS a
    DecisionBackend, not a separate kind of thing.
    """

    def __init__(
        self,
        backend: DecisionBackend,
        *,
        model: str,
        cache_root: Path,
        mode: str,
    ) -> None:
        self._backend = backend
        self._model = model
        self._cache_root = cache_root
        self._mode = mode

    @property
    def name(self) -> str:
        return self._backend.name

    def _path_for(self, classify_input: ClassifyInput) -> Path:
        key = cache_key(self._backend.name, self._model, classify_input)
        return self._cache_root / self._backend.name / f"{key}.json"

    def classify(self, classify_input: ClassifyInput) -> ClassificationResult:
        path = self._path_for(classify_input)
        if path.exists():
            return ClassificationResult.model_validate_json(path.read_text(encoding="utf-8"))

        if self._mode == "replay":
            raise MissingFixtureError(
                f"no cached {self._backend.name!r} response for this input "
                f"(expected at {path}) - run with MODEL_CACHE_MODE=record and "
                f"a live API key to seed it"
            )

        result = self._backend.classify(classify_input)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return result
