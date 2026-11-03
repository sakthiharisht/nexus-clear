"""Tests for the non-LLM baseline extractor (SPEC.md section 14, M3):
reads real rendered packets, verifies it recovers readable fields, and
confirms it never guesses on unreadable (image-only) documents.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from faker import Faker
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from app.eval.baseline_extraction import (
    _field,
    _money,
    _parse_date,
    _read_text,
    extract_baseline_facts,
)
from app.eval.generator.build import DEFAULT_SEED
from app.eval.generator.packets import PACKET_SPECS, build_packet

GroundTruthPackets = tuple[list[dict[str, Any]], Path]


@pytest.fixture(scope="module")
def ground_truth_packets(tmp_path_factory: pytest.TempPathFactory) -> GroundTruthPackets:
    output_root = tmp_path_factory.mktemp("baseline-extraction")
    Faker.seed(DEFAULT_SEED)
    fake = Faker()
    packets = []
    for index, spec in enumerate(PACKET_SPECS):
        built = build_packet(spec, index, fake, output_root)
        packets.append(
            {
                "packet_id": built.packet_id,
                "kind": built.kind,
                "defect_ids": built.defect_ids,
                "target_date": built.target_date.isoformat(),
                "documents": {
                    slot: path.relative_to(output_root).as_posix()
                    for slot, path in built.document_paths.items()
                },
                "facts": json.loads(built.facts.model_dump_json()),
            }
        )
    return packets, output_root


def _packet(packets: list[dict[str, Any]], packet_id: str) -> dict[str, Any]:
    return next(p for p in packets if p["packet_id"] == packet_id)


def test_reads_fields_from_a_readable_license_pdf(ground_truth_packets: GroundTruthPackets) -> None:
    packets, root = ground_truth_packets
    packet = _packet(packets, "clean-1")
    facts, notes = extract_baseline_facts(packet, root)

    assert notes == []
    assert facts.license.license_type == packet["facts"]["license"]["license_type"]
    expected_exp = packet["facts"]["license"]["expiration_date"]
    assert facts.license.expiration_date is not None
    assert facts.license.expiration_date.isoformat() == expected_exp
    assert facts.coi.per_occurrence == packet["facts"]["coi"]["per_occurrence"]
    assert len(facts.cv.positions) == len(packet["facts"]["cv"]["positions"])


def test_png_scan_yields_unknown_never_a_guess(ground_truth_packets: GroundTruthPackets) -> None:
    packets, root = ground_truth_packets
    packet = _packet(packets, "benign-2-rotated-scan")
    facts, notes = extract_baseline_facts(packet, root)

    assert any("license" in n for n in notes)
    license_doc = next(d for d in facts.documents if d.slot == "license")
    assert license_doc.uploaded_doc_type is None
    assert license_doc.legible_score is None
    assert license_doc.contains_injection_text is None
    # And consequently the content fields baseline would have read from it:
    assert facts.license.license_type is None
    assert facts.license.expiration_date is None


def test_profile_and_supervision_come_from_ground_truth_not_extraction(
    ground_truth_packets: GroundTruthPackets,
) -> None:
    packets, root = ground_truth_packets
    packet = _packet(packets, "defective-8")  # D15: invalid NPI check digit
    facts, _ = extract_baseline_facts(packet, root)

    assert facts.profile.npi == packet["facts"]["profile"]["npi"]
    assert facts.profile.legal_name == packet["facts"]["profile"]["legal_name"]


def test_injection_keyword_heuristic_detects_d14_on_the_cv_slot(
    ground_truth_packets: GroundTruthPackets,
) -> None:
    packets, root = ground_truth_packets
    packet = _packet(packets, "defective-7")  # D09+D10+D14
    facts, _ = extract_baseline_facts(packet, root)

    cv_doc = next(d for d in facts.documents if d.slot == "cv")
    assert cv_doc.contains_injection_text is True


def test_injection_heuristic_false_on_clean_text(ground_truth_packets: GroundTruthPackets) -> None:
    packets, root = ground_truth_packets
    packet = _packet(packets, "clean-1")
    facts, _ = extract_baseline_facts(packet, root)

    cv_doc = next(d for d in facts.documents if d.slot == "cv")
    assert cv_doc.contains_injection_text is False


def test_wrong_doc_in_slot_is_classified_by_its_actual_title_when_readable(
    ground_truth_packets: GroundTruthPackets,
) -> None:
    # D09 without an accompanying illegibility defect: the license slot
    # holds CV content but is still a readable PDF, so baseline should
    # correctly classify it as "cv", not "texas_lpc_license".
    packets, root = ground_truth_packets
    original = _packet(packets, "defective-7")
    # Swap in this packet's own cv.pdf as a stand-in "readable wrong
    # document" at the license slot, bypassing the real D10 scan.
    packet = {
        **original,
        "documents": {**original["documents"], "license": original["documents"]["cv"]},
    }
    facts, notes = extract_baseline_facts(packet, root)

    license_doc = next(d for d in facts.documents if d.slot == "license")
    assert license_doc.uploaded_doc_type == "cv"
    assert license_doc.expected_doc_type == "texas_lpc_license"
    assert notes == []


def test_no_document_uploaded_for_a_slot_yields_unknown(
    ground_truth_packets: GroundTruthPackets,
) -> None:
    packets, root = ground_truth_packets
    original = _packet(packets, "clean-1")
    docs_without_w9 = {k: v for k, v in original["documents"].items() if k != "w9"}
    packet = {**original, "documents": docs_without_w9}

    facts, notes = extract_baseline_facts(packet, root)

    assert any("w9" in n and "no document uploaded" in n for n in notes)
    w9_doc = next(d for d in facts.documents if d.slot == "w9")
    assert w9_doc.uploaded_doc_type is None


def test_readable_text_with_an_unrecognized_title_is_noted(
    ground_truth_packets: GroundTruthPackets,
) -> None:
    packets, root = ground_truth_packets
    original = _packet(packets, "clean-1")

    weird_pdf = root / "weird.pdf"
    c = canvas.Canvas(str(weird_pdf), pagesize=LETTER, invariant=1)
    c.drawString(72, 740, "Not A Known Document Title")
    c.showPage()
    c.save()

    packet = {
        **original,
        "documents": {**original["documents"], "w9": str(weird_pdf.relative_to(root))},
    }
    facts, notes = extract_baseline_facts(packet, root)

    assert any("didn't match a known doc type" in n for n in notes)
    w9_doc = next(d for d in facts.documents if d.slot == "w9")
    assert w9_doc.uploaded_doc_type is None


def test_read_text_returns_none_for_a_corrupt_pdf(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 not actually a valid pdf stream")
    assert _read_text(broken) is None


def test_parse_date_and_money_helpers_handle_missing_and_malformed_values() -> None:
    assert _parse_date(None) is None
    assert _parse_date("not-a-date") is None
    assert _money("Per occurrence: $100,000", "Aggregate") is None  # label absent
    assert _money("Per occurrence: not-a-number", "Per occurrence") is None
    assert _field("No colon here", "Label") is None

