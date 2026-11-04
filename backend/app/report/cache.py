"""Record/replay cache for gap report phrasing calls (CLAUDE.md:
"LLM/Jev calls go through the record/replay cache so CI is offline and
deterministic"). Parallel to app/backends/extract_cache.py's
CachedExtractor, keyed on the whole batch of PhraseRequests at once -
a phraser's natural unit of work is "phrase this set of findings," not
one finding at a time (same reasoning as app/reconcile/cache.py's
CachedInvestigator).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.report.types import PhraseRequest, PhraseResult, SentencePhraser


class MissingFixtureError(RuntimeError):
    """Raised in "replay" mode when no cached response exists for this
    exact batch of requests - a cache miss fails loudly in CI instead
    of silently reaching the network."""


def cache_key(
    backend_name: str, model: str, prompt_version: str, requests: list[PhraseRequest]
) -> str:
    """`prompt_version` (M7 housekeeping #1) is part of the key so an
    edited prompt can never silently replay sentences phrased under
    the old wording."""
    canonical = json.dumps(
        {
            "backend": backend_name,
            "model": model,
            "prompt_version": prompt_version,
            "requests": [r.model_dump(mode="json") for r in requests],
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


class CachedPhraser:
    def __init__(
        self, phraser: SentencePhraser, *, model: str, cache_root: Path, mode: str
    ) -> None:
        self._phraser = phraser
        self._model = model
        self._cache_root = cache_root
        self._mode = mode

    @property
    def name(self) -> str:
        return self._phraser.name

    @property
    def prompt_version(self) -> str:
        return self._phraser.prompt_version

    def _path_for(self, requests: list[PhraseRequest]) -> Path:
        key = cache_key(self._phraser.name, self._model, self._phraser.prompt_version, requests)
        return self._cache_root / self._phraser.name / f"report-{key}.json"

    def phrase(self, requests: list[PhraseRequest]) -> PhraseResult:
        if not requests:
            return PhraseResult()

        path = self._path_for(requests)
        if path.exists():
            return PhraseResult.model_validate_json(path.read_text(encoding="utf-8"))

        if self._mode == "replay":
            raise MissingFixtureError(
                f"no cached {self._phraser.name!r} phrasing for this batch "
                f"(expected at {path}) - run with a live API key to seed it"
            )

        result = self._phraser.phrase(requests)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return result
