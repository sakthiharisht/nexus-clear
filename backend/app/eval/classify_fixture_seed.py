"""Seeds eval/fixtures/model_cache/ with classify responses for the 12
real packets' documents, for both the Jev and Claude backends.

IMPORTANT - these are SIMULATED responses, not real model output.
Neither JEV_API_KEY nor ANTHROPIC_API_KEY was available in the
environment this was built in (see the M5 completion report's "what I
could not verify live" section) - CachedBackend's "record" mode
(app/backends/cache.py), which calls a real backend live and writes
its genuine response, was never exercised here. This script instead
deterministically derives a plausible response from each document's
own ground-truth facts (app/eval/generator): correct doc_type unless
the ground truth's own legible_score is low, confidence/legibility
tracking that score with a small per-backend offset, cost/latency set
to illustrative placeholders - not measured, not real pricing math
(unlike app/backends/claude_backend.py's verified per-model rates,
which only apply to an actual token count a real call would report).

Run with `uv run python -m app.eval.classify_fixture_seed` (from
backend/). Re-run after regenerating eval/fixtures/packets/ or changing
build_classify_input's shape - cache keys hash the exact ClassifyInput,
so drift there orphans old files (safe to delete; a real eval run's
MissingFixtureError names exactly which key it needed).

To replace this with real model output: set ANTHROPIC_API_KEY and/or
JEV_API_KEY, set MODEL_CACHE_MODE=record, and run app.eval.run with
classify modes enabled - CachedBackend calls the real backend on every
miss and writes its genuine response, overwriting these simulated ones
file by file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.backends.cache import cache_key
from app.backends.types import ClassificationResult
from app.core.config import settings
from app.eval.classify_run import build_classify_input

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _simulate(
    *, backend_name: str, true_doc_type: str, legible_score: float, offset: float
) -> ClassificationResult:
    legible = max(0.0, min(1.0, legible_score + offset))
    # A document the ground truth itself marks as poorly legible is
    # also where a real classifier would plausibly misfire - simulated
    # that way rather than every call being perfectly accurate, which
    # would make accuracy/ECE trivially 100%/0 and prove nothing about
    # the metric machinery.
    confused = legible_score < 0.5
    predicted_doc_type = "other" if confused else true_doc_type
    confidence = 0.55 if confused else max(0.80, min(0.99, 0.80 + legible_score * 0.19))
    return ClassificationResult(
        doc_type=predicted_doc_type,
        probabilities={predicted_doc_type: confidence},
        legible=legible,
        slot_match=predicted_doc_type != "other",
        decided_by=backend_name,  # type: ignore[arg-type]
        cost_usd=0.0002 if backend_name == "jev" else 0.0009,
        latency_ms=180.0 if backend_name == "jev" else 650.0,
    )


def seed(ground_truth: dict[str, Any], fixtures_root: Path, cache_root: Path) -> int:
    written = 0
    for packet in ground_truth["packets"]:
        for doc_fact in packet["facts"]["documents"]:
            slot = doc_fact["slot"]
            if slot not in packet["documents"]:
                continue

            classify_input = build_classify_input(packet, slot, fixtures_root)
            legible_score = doc_fact["legible_score"] or 0.0
            true_doc_type = doc_fact["uploaded_doc_type"]

            for backend_name, model, offset in (
                ("jev", settings.jev_model, -0.03),
                ("claude", settings.model_classify_fallback, 0.02),
            ):
                result = _simulate(
                    backend_name=backend_name,
                    true_doc_type=true_doc_type,
                    legible_score=legible_score,
                    offset=offset,
                )
                key = cache_key(backend_name, model, classify_input)
                path = cache_root / backend_name / f"{key}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
                written += 1
    return written


def main() -> None:  # pragma: no cover - thin CLI wrapper, exercised via seed() in tests
    ground_truth_path = _REPO_ROOT / "eval" / "fixtures" / "ground_truth.json"
    fixtures_root = _REPO_ROOT / "eval" / "fixtures"
    ground_truth = json.loads(ground_truth_path.read_text(encoding="utf-8"))
    written = seed(ground_truth, fixtures_root, settings.model_cache_root)
    print(f"Wrote {written} simulated classify fixtures to {settings.model_cache_root}")


if __name__ == "__main__":  # pragma: no cover
    main()
