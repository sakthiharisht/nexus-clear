"""Tests app.eval.classify_fixture_seed's seed() function against a
tmp_path cache root - never touches the real committed
eval/fixtures/model_cache/.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.backends.cache import CachedBackend, MissingFixtureError
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
    def __init__(self, name: str) -> None:
        self.name = name

    def classify(self, classify_input: object) -> ClassificationResult:
        raise AssertionError("seeded fixtures should make a live call unnecessary")


def test_seed_writes_one_file_per_document_per_backend(tmp_path: Path) -> None:
    written = seed(GROUND_TRUTH, FIXTURES_ROOT, tmp_path)
    assert written == 12 * 5 * 2  # 12 packets x 5 slots x {jev, claude}
    assert len(list((tmp_path / "jev").glob("*.json"))) == 60
    assert len(list((tmp_path / "claude").glob("*.json"))) == 60


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
