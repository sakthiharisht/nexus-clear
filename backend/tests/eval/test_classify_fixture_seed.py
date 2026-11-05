"""Tests app.eval.classify_fixture_seed's seed() function against a
tmp_path cache root - never touches the real committed
eval/fixtures/model_cache/.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.backends.cache import CachedBackend, MissingFixtureError
from app.backends.claude_backend import ClaudeBackend
from app.backends.types import ClassificationResult
from app.core.config import settings
from app.eval.classify_fixture_seed import seed
from app.eval.classify_run import build_classify_input

REPO_ROOT = Path(__file__).resolve().parents[3]
GROUND_TRUTH = json.loads(
    (REPO_ROOT / "eval" / "fixtures" / "ground_truth.json").read_text(encoding="utf-8")
)
FIXTURES_ROOT = REPO_ROOT / "eval" / "fixtures"


class _UnreachableBackend:
    # Matches ClaudeBackend's real fingerprint - every call site below
    # uses name="claude" against fixtures seed() wrote keyed under
    # ClaudeBackend.prompt_version (app/eval/classify_fixture_seed.py's
    # _PROMPT_VERSION_BY_BACKEND), so this must resolve to the same key.
    prompt_version = ClaudeBackend.prompt_version

    def __init__(self, name: str) -> None:
        self.name = name

    def classify(self, classify_input: object) -> ClassificationResult:
        raise AssertionError("seeded fixtures should make a live call unnecessary")


def test_seed_writes_one_file_per_document_per_backend_and_tier(tmp_path: Path) -> None:
    written = seed(GROUND_TRUTH, FIXTURES_ROOT, tmp_path)
    # 15 packets x 5 slots x {jev, claude-haiku, claude-sonnet, claude-opus}
    assert written == 15 * 5 * 4
    assert len(list((tmp_path / "jev").glob("*.json"))) == 75
    assert len(list((tmp_path / "claude").glob("*.json"))) == 75 * 3


def test_seed_never_overwrites_an_already_real_recording(tmp_path: Path) -> None:
    """Regression: seeding a second manifest (e.g. the hard set) into
    the same cache root once clobbered 240 already-real easy-set
    recordings back to simulated placeholders."""
    seed(GROUND_TRUTH, FIXTURES_ROOT, tmp_path)
    packet = next(p for p in GROUND_TRUTH["packets"] if p["packet_id"] == "clean-1")
    classify_input = build_classify_input(packet, "license", FIXTURES_ROOT)

    from app.backends.cache import cache_key

    key = cache_key("claude", "claude-haiku-5-5", ClaudeBackend.prompt_version, classify_input)
    real_path = tmp_path / "claude" / f"{key}.json"
    real_result = ClassificationResult(
        doc_type="texas_lpc_license",
        probabilities={"texas_lpc_license": 0.99},
        legible=0.98,
        slot_match=True,
        decided_by="claude",
        simulated=False,
    )
    real_path.write_text(real_result.model_dump_json(indent=2) + "\n", encoding="utf-8")

    written = seed(GROUND_TRUTH, FIXTURES_ROOT, tmp_path)
    reloaded = ClassificationResult.model_validate_json(real_path.read_text(encoding="utf-8"))
    assert reloaded.simulated is False
    assert reloaded.doc_type == "texas_lpc_license"
    # Every OTHER file in this second pass was a legitimate re-seed
    # (freshly written to tmp_path); only the one marked real was
    # skipped.
    assert written == 15 * 5 * 4 - 1


def test_seeded_fixtures_are_replayable_without_any_live_call(tmp_path: Path) -> None:
    seed(GROUND_TRUTH, FIXTURES_ROOT, tmp_path)

    packet = next(p for p in GROUND_TRUTH["packets"] if p["packet_id"] == "clean-1")
    classify_input = build_classify_input(packet, "license", FIXTURES_ROOT)

    cached = CachedBackend(
        _UnreachableBackend("claude"),
        model=settings.model_classify_fallback,
        cache_root=tmp_path,
        mode="replay",
    )
    result = cached.classify(classify_input)
    assert result.doc_type == "texas_lpc_license"


def test_a_confused_low_legibility_document_predicts_other(tmp_path: Path) -> None:
    seed(GROUND_TRUTH, FIXTURES_ROOT, tmp_path)

    # defective-7 plants D10: license legible_score is well below 0.5.
    packet = next(p for p in GROUND_TRUTH["packets"] if p["packet_id"] == "defective-7")
    classify_input = build_classify_input(packet, "license", FIXTURES_ROOT)

    cached = CachedBackend(
        _UnreachableBackend("claude"),
        model=settings.model_classify_fallback,
        cache_root=tmp_path,
        mode="replay",
    )
    result = cached.classify(classify_input)
    assert result.doc_type == "other"


def test_seed_skips_a_slot_with_no_uploaded_document(tmp_path: Path) -> None:
    fabricated_ground_truth = {
        "packets": [
            {
                "packet_id": "p1",
                "documents": {},
                "facts": {
                    "documents": [
                        {
                            "slot": "license",
                            "expected_doc_type": "texas_lpc_license",
                            "uploaded_doc_type": None,
                            "legible_score": None,
                        }
                    ]
                },
            }
        ]
    }
    written = seed(fabricated_ground_truth, FIXTURES_ROOT, tmp_path)
    assert written == 0


def test_an_unseeded_cache_root_raises_missing_fixture(tmp_path: Path) -> None:
    packet = next(p for p in GROUND_TRUTH["packets"] if p["packet_id"] == "clean-1")
    classify_input = build_classify_input(packet, "license", FIXTURES_ROOT)
    cached = CachedBackend(
        _UnreachableBackend("claude"),
        model=settings.model_classify_fallback,
        cache_root=tmp_path,
        mode="replay",
    )
    with pytest.raises(MissingFixtureError):
        cached.classify(classify_input)
