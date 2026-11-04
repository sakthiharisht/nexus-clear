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
from app.backends.claude_backend import ClaudeBackend
from app.backends.jev_backend import JevBackend
from app.backends.types import ClassificationResult
from app.core.config import settings
from app.eval.classify_run import build_classify_input

_PROMPT_VERSION_BY_BACKEND = {
    "jev": JevBackend.prompt_version,
    "claude": ClaudeBackend.prompt_version,
}

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
    is_jev = backend_name == "jev"
    return ClassificationResult(
        doc_type=predicted_doc_type,
        probabilities={predicted_doc_type: confidence},
        legible=legible,
        slot_match=predicted_doc_type != "other",
        decided_by=backend_name,  # type: ignore[arg-type]
        input_tokens=350 if is_jev else 450,
        output_tokens=20 if is_jev else 60,
        # Jev's cost is "n/a" even in simulation - its direct-API
        # pricing isn't verified for real either (app/backends/
        # jev_backend.py), so a simulated nonzero number here would be
        # strictly less honest than the real backend's own cost_known.
        cost_usd=0.0,
        cost_known=not is_jev,
        latency_ms=180.0 if is_jev else 650.0,
        simulated=True,
    )


def seed(ground_truth: dict[str, Any], fixtures_root: Path, cache_root: Path) -> int:
    """Never overwrites an existing cache file whose `simulated` is
    already False - re-running this after a live recording (M5.1
    housekeeping #2) must not silently regress real data back to a
    placeholder. Hit exactly that bug once already: seeding both sets
    after adding the hard set clobbered 240 real easy-set recordings,
    recovered only because they were already committed to git.
    """
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
                ("claude", "claude-haiku-5-5", 0.02),
                ("claude", "claude-sonnet-5-5", 0.03),
                ("claude", "claude-opus-5-5", 0.04),
            ):
                key = cache_key(
                    backend_name, model, _PROMPT_VERSION_BY_BACKEND[backend_name], classify_input
                )
                path = cache_root / backend_name / f"{key}.json"
                if path.exists():
                    existing = ClassificationResult.model_validate_json(
                        path.read_text(encoding="utf-8")
                    )
                    if not existing.simulated:
                        continue

                result = _simulate(
                    backend_name=backend_name,
                    true_doc_type=true_doc_type,
                    legible_score=legible_score,
                    offset=offset,
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
                written += 1
    return written


def main() -> None:  # pragma: no cover - thin CLI wrapper, exercised via seed() in tests
    fixtures_root = _REPO_ROOT / "eval" / "fixtures"

    ground_truth_path = fixtures_root / "ground_truth.json"
    ground_truth = json.loads(ground_truth_path.read_text(encoding="utf-8"))
    written = seed(ground_truth, fixtures_root, settings.model_cache_root)
    print(f"Wrote {written} simulated classify fixtures (easy set) to {settings.model_cache_root}")

    # M5.1 housekeeping #2: seed() doesn't care which manifest it's
    # given - a hard-set "packet" is just a one-document instance of
    # the same shape (app/eval/generator/hard_classify_set.py).
    hard_ground_truth_path = fixtures_root / "hard_classify_ground_truth.json"
    if hard_ground_truth_path.exists():
        hard_ground_truth = json.loads(hard_ground_truth_path.read_text(encoding="utf-8"))
        hard_written = seed(hard_ground_truth, fixtures_root, settings.model_cache_root)
        print(f"Wrote {hard_written} simulated classify fixtures (hard set)")


if __name__ == "__main__":  # pragma: no cover
    main()
