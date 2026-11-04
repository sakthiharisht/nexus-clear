"""Record/replay cache for Extract calls (CLAUDE.md: "LLM/Jev calls go
through the record/replay cache so CI is offline and deterministic.
Live runs refresh the cache."). Parallel to app/backends/cache.py's
CachedBackend, but over ExtractInput/ExtractionResult/`.extract()`
instead of ClassifyInput/ClassificationResult/`.classify()` - kept as
its own small module rather than generalizing cache.py, since the two
result types don't share a common Pydantic base to parse back out of
JSON generically.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Protocol

from app.backends.extract_types import ExtractInput, ExtractionResult


class MissingFixtureError(RuntimeError):
    """Raised in "replay" mode when no cached response exists for an
    input - a cache miss fails loudly in CI instead of silently
    reaching the network."""


class ExtractionBackend(Protocol):
    @property
    def name(self) -> str: ...

    def extract(self, extract_input: ExtractInput) -> ExtractionResult: ...


def cache_key(backend_name: str, model: str, extract_input: ExtractInput) -> str:
    """M6.1: when an image is attached, the key hashes the image's own
    sha256 digest rather than embedding the full base64 payload into
    the canonical JSON - same result for lookup purposes (same bytes
    in -> same key out), but doesn't push a large blob through
    json.dumps + a second hash for no benefit. `image_b64=None` (the
    common case - every text-layer document) is unaffected: the
    canonical dict is identical to before this existed, so every
    already-recorded fixture still resolves under its original key.
    """
    input_dict = extract_input.model_dump(mode="json")
    image_b64 = input_dict.get("image_b64")
    if image_b64 is not None:
        input_dict["image_b64"] = hashlib.sha256(base64.b64decode(image_b64)).hexdigest()
    canonical = json.dumps(
        {"backend": backend_name, "model": model, "input": input_dict}, sort_keys=True
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


class CachedExtractor:
    def __init__(
        self,
        backend: ExtractionBackend,
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

    def _path_for(self, extract_input: ExtractInput) -> Path:
        key = cache_key(self._backend.name, self._model, extract_input)
        return self._cache_root / self._backend.name / f"extract-{key}.json"

    def extract(self, extract_input: ExtractInput) -> ExtractionResult:
        path = self._path_for(extract_input)
        if path.exists():
            return ExtractionResult.model_validate_json(path.read_text(encoding="utf-8"))

        if self._mode == "replay":
            raise MissingFixtureError(
                f"no cached {self._backend.name!r} extraction for this input "
                f"(expected at {path}) - run with a live API key to seed it"
            )

        result = self._backend.extract(extract_input)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return result
