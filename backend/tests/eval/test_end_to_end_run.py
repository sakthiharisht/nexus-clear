from __future__ import annotations

import json
from pathlib import Path

from app.backends.extract_types import (
    CoiExtraction,
    CvExtraction,
    ExtractedField,
    ExtractInput,
    ExtractionResult,
    LicenseExtraction,
)
from app.eval.end_to_end_run import run_end_to_end
from app.reconcile.investigator import (
    InvestigationResult,
    NameMatchConclusion,
    NameMatchTask,
    RegistryConclusion,
    RegistryTask,
)
from app.rules.loader import load_rule_pack

REPO_ROOT = Path(__file__).resolve().parents[3]
GROUND_TRUTH = json.loads(
    (REPO_ROOT / "eval" / "fixtures" / "ground_truth.json").read_text(encoding="utf-8")
)
FIXTURES_ROOT = REPO_ROOT / "eval" / "fixtures"
PACK = load_rule_pack(REPO_ROOT / "rules" / "tx_bcbstx_lpc.yaml")


def _field(value: str | None, quote: str | None) -> ExtractedField:
    return ExtractedField(value=value, confidence=0.9, page=1, quote=quote)


class _StubExtractor:
    name = "claude"
    prompt_version = "test"

    def __init__(self) -> None:
        self.calls = 0

    def extract(self, extract_input: ExtractInput) -> ExtractionResult:
        self.calls += 1
        if extract_input.kind == "license":
            holder_name = None
            if "Holder name:" in extract_input.document_text:
                start = extract_input.document_text.index("Holder name:")
                line = extract_input.document_text[start:].splitlines()[0]
                holder_name = line.split(":", 1)[1].strip()
            fields = LicenseExtraction(
                holder_name=_field(holder_name, f"Holder name: {holder_name}")
                if holder_name
                else LicenseExtraction().holder_name
            )
            return ExtractionResult(kind="license", fields=fields)
        if extract_input.kind == "coi":
            return ExtractionResult(kind="coi", fields=CoiExtraction())
        return ExtractionResult(kind="cv", fields=CvExtraction())


class _StubInvestigator:
    prompt_version = "test"

    def __init__(self) -> None:
        self.calls: list[tuple[list[NameMatchTask], list[RegistryTask]]] = []

    def investigate(
        self, *, name_match_tasks: list[NameMatchTask], registry_tasks: list[RegistryTask]
    ) -> InvestigationResult:
        self.calls.append((name_match_tasks, registry_tasks))
        return InvestigationResult(
            name_match_conclusions=[
                NameMatchConclusion(rule_id=t.rule_id, probability=0.95) for t in name_match_tasks
            ],
            registry_conclusions=[
                RegistryConclusion(
                    rule_id=t.rule_id,
                    exists=True,
                    checks={"exists": True, "name_consistent": True, "taxonomy_counselor": True},
                    status="Active",
                    possible_match=False,
                )
                for t in registry_tasks
            ],
        )


def test_run_end_to_end_covers_every_packet() -> None:
    extractor = _StubExtractor()
    investigator = _StubInvestigator()
    result = run_end_to_end(
        PACK,
        GROUND_TRUTH,
        FIXTURES_ROOT,
        mode_name="e2e-test",
        extractor=extractor,
        investigator=investigator,
    )
    assert len(result.packets) == len(GROUND_TRUTH["packets"])
    assert result.mode == "e2e-test"


def test_run_end_to_end_produces_findings_matching_the_rule_pack() -> None:
    extractor = _StubExtractor()
    investigator = _StubInvestigator()
    result = run_end_to_end(
        PACK,
        {"packets": [p for p in GROUND_TRUTH["packets"] if p["packet_id"] == "clean-1"]},
        FIXTURES_ROOT,
        mode_name="e2e-test",
        extractor=extractor,
        investigator=investigator,
    )
    packet = result.packets[0]
    assert packet.packet_id == "clean-1"
    assert set(packet.actual) == set(packet.expected)


def test_defective_7_skips_license_extraction_but_scores_cv() -> None:
    """D09: the license slot holds a CV - no license extraction call
    should happen for that slot, matching app/eval/extract_run.py's
    own gate."""
    extractor = _StubExtractor()
    investigator = _StubInvestigator()
    packet = next(p for p in GROUND_TRUTH["packets"] if p["packet_id"] == "defective-7")
    result = run_end_to_end(
        PACK,
        {"packets": [packet]},
        FIXTURES_ROOT,
        mode_name="e2e-test",
        extractor=extractor,
        investigator=investigator,
    )
    notes = result.packets[0].extraction_notes
    assert any("license" in n for n in notes)


def test_registry_tasks_are_always_sent_to_the_investigator() -> None:
    extractor = _StubExtractor()
    investigator = _StubInvestigator()
    run_end_to_end(
        PACK,
        {"packets": [p for p in GROUND_TRUTH["packets"] if p["packet_id"] == "clean-1"]},
        FIXTURES_ROOT,
        mode_name="e2e-test",
        extractor=extractor,
        investigator=investigator,
    )
    assert investigator.calls
    _, registry_tasks = investigator.calls[0]
    assert any(t.rule_id == "R-ID-002" for t in registry_tasks)


def test_extraction_failure_is_recorded_as_a_note_not_a_crash() -> None:
    class _RaisingExtractor:
        name = "claude"
        prompt_version = "test"

        def extract(self, extract_input: ExtractInput) -> ExtractionResult:
            raise ValueError("Claude did not return a parsed structured output")

    investigator = _StubInvestigator()
    result = run_end_to_end(
        PACK,
        {"packets": [p for p in GROUND_TRUTH["packets"] if p["packet_id"] == "clean-1"]},
        FIXTURES_ROOT,
        mode_name="e2e-test",
        extractor=_RaisingExtractor(),
        investigator=investigator,
    )
    assert any("failed" in n for n in result.packets[0].extraction_notes)
