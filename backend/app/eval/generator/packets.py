"""The 12 synthetic packets (SPEC.md section 10): 2 clean, 2 benign
variations (must produce no false positives), 8 defective (covering
D01-D15, exactly one each, 1-3 defects per packet)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Literal

from faker import Faker

from app.core.contracts import FindingStatus
from app.eval.generator import documents as docs
from app.eval.generator.expected import expected_findings
from app.eval.generator.mutations import (
    SLOT_DOC_TYPES,
    SLOTS,
    PacketBuildState,
    apply_defect,
    initial_state,
)
from app.eval.generator.provider import ProviderSpec, build_provider
from app.rules.context import (
    CaseFacts,
    CoiFacts,
    CvFacts,
    CvPosition,
    DocumentFact,
    LicenseFacts,
    ProfileFacts,
    RegistryResult,
    SupervisionFacts,
)

TARGET_DATE = date(2026, 11, 17)

PacketKind = Literal["clean", "benign", "defective"]


@dataclass(frozen=True)
class PacketSpec:
    packet_id: str
    kind: PacketKind
    defect_ids: list[str]
    description: str


PACKET_SPECS: list[PacketSpec] = [
    PacketSpec("clean-1", "clean", [], "clean packet"),
    PacketSpec("clean-2", "clean", [], "clean packet, a different provider"),
    PacketSpec(
        "benign-1-nickname",
        "benign",
        [],
        "license holder uses a nickname of the legal name; must not false-positive",
    ),
    PacketSpec(
        "benign-2-rotated-scan",
        "benign",
        [],
        "license is a slightly rotated scan, still legible; must not false-positive",
    ),
    PacketSpec("defective-1", "defective", ["D01", "D08"], "license expired + CV gap"),
    PacketSpec(
        "defective-2", "defective", ["D02", "D04"], "license expiring soon + COI limits low"
    ),
    PacketSpec(
        "defective-3", "defective", ["D03", "D13"], "COI expired + insured name unrelated"
    ),
    PacketSpec(
        "defective-4", "defective", ["D05", "D11"], "name mismatch + NPI taxonomy wrong"
    ),
    PacketSpec("defective-5", "defective", ["D06"], "Associate submitting as independent"),
    PacketSpec("defective-6", "defective", ["D07"], "Associate, supervisor license expired"),
    PacketSpec(
        "defective-7",
        "defective",
        ["D09", "D10", "D14"],
        "wrong doc in slot + illegible scan + prompt injection in CV",
    ),
    PacketSpec("defective-8", "defective", ["D12", "D15"], "LEIE hit + invalid NPI check digit"),
    # Pre-M9 fix #5: benign-1-nickname's "Jon"/"Jonathan" pair is a
    # well-known nickname a model resolves confidently (>= 0.9,
    # tests/reconcile/test_acceptance.py's own "benign nickname passes"
    # case) - it never actually reaches Escalate's ambiguous middle
    # band live. These three are legitimately the same person too
    # (ground truth still resolves R-LIC-004/R-COI-004 to pass), but
    # each varies the name in a way a real fuzzy/LLM matcher is
    # genuinely less certain about - appended at the end of this list
    # so the existing 12 packets' Faker-derived content is unaffected
    # (Faker's seeded stream is consumed in list order).
    PacketSpec(
        "benign-3-hyphenated-surname",
        "benign",
        [],
        "license holder's surname is hyphenated on the license, spaced on "
        "intake (Garcia-Lopez vs Garcia Lopez); must not false-positive",
    ),
    PacketSpec(
        "benign-4-middle-initial",
        "benign",
        [],
        "intake profile adds a middle initial the license doesn't have "
        "(Robert Chen vs Robert J. Chen); must not false-positive",
    ),
    PacketSpec(
        "benign-5-suffix",
        "benign",
        [],
        "intake profile adds a generational suffix the (older) license "
        "doesn't have (William Harrison vs William Harrison III); must "
        "not false-positive",
    ),
]


@dataclass
class BuiltPacket:
    packet_id: str
    kind: PacketKind
    defect_ids: list[str]
    description: str
    target_date: date
    facts: CaseFacts
    expected_findings: dict[str, FindingStatus]
    registry_fixtures: dict[str, dict[str, dict[str, object]]]
    document_paths: dict[str, Path]


def _build_documents(state: PacketBuildState) -> list[DocumentFact]:
    return [
        DocumentFact(
            doc_id=f"doc-{slot}",
            slot=slot,
            expected_doc_type=SLOT_DOC_TYPES[slot],
            uploaded_doc_type=state.uploaded_doc_type[slot],
            legible_score=state.legible_score[slot],
            contains_injection_text=state.contains_injection[slot],
        )
        for slot in SLOTS
    ]


def _case_facts(
    state: PacketBuildState, target_date: date, documents: list[DocumentFact]
) -> CaseFacts:
    p = state.provider
    return CaseFacts(
        target_date=target_date,
        license=LicenseFacts(
            doc_id="doc-license",
            holder_name=p.license_holder_name,
            license_number=p.license_number,
            license_type=p.license_type,
            status=p.license_status,
            issue_date=p.license_issue_date,
            expiration_date=p.license_expiration_date,
            issuing_board=p.issuing_board,
        ),
        coi=CoiFacts(
            doc_id="doc-coi",
            insured_name=p.coi_insured_name,
            carrier=p.coi_carrier,
            policy_number=p.coi_policy_number,
            effective_date=p.coi_effective_date,
            expiration_date=p.coi_expiration_date,
            per_occurrence=p.coi_per_occurrence,
            aggregate=p.coi_aggregate,
        ),
        cv=CvFacts(
            doc_id="doc-cv",
            positions=[
                CvPosition(title=pos.title, employer=pos.employer, start=pos.start, end=pos.end)
                for pos in p.positions
            ],
        ),
        profile=ProfileFacts(legal_name=p.legal_name, practice_name=p.practice_name, npi=p.npi),
        supervision=SupervisionFacts(
            supervisor_count=p.supervisor_count,
            supervisor_license_number=p.supervisor_license_number,
        ),
        documents=documents,
        name_match_probabilities=dict(state.name_match_probabilities),
        registry_results=_registry_results(state),
    )


def _registry_results(state: PacketBuildState) -> dict[str, RegistryResult]:
    results: dict[str, RegistryResult] = {}
    if state.provider.license_type == "LPC Associate":
        results["R-SUP-001"] = RegistryResult(
            status=state.supervisor_license_status, registry="tx_license_lookup"
        )
    results["R-ID-002"] = RegistryResult(checks=dict(state.nppes_checks), registry="nppes")
    results["R-EXC-001"] = RegistryResult(
        possible_match=state.leie_possible_match, registry="leie"
    )
    return results


def _registry_fixture_payload(state: PacketBuildState) -> dict[str, dict[str, dict[str, object]]]:
    """Preview of the per-tool FIXTURE-mode files M7's MCP tool adapters
    will read (SPEC.md section 7.6), keyed by query input (npi / license
    number / name) rather than by rule id."""
    p = state.provider
    payload: dict[str, dict[str, dict[str, object]]] = {
        "nppes": {
            p.npi: {
                "exists": state.nppes_checks.get("exists", True),
                "name_consistent": state.nppes_checks.get("name_consistent", True),
                "taxonomy_counselor": state.nppes_checks.get("taxonomy_counselor", True),
                "name": p.legal_name,
            }
        },
        "tx_license": {
            p.license_number: {
                "status": p.license_status,
                "holder_name": p.license_holder_name,
                "license_type": p.license_type,
            }
        },
        "leie": {
            p.legal_name: {
                "possible_match": state.leie_possible_match,
                "npi": p.npi,
            }
        },
    }
    if p.license_type == "LPC Associate":
        payload["tx_license"][p.supervisor_license_number] = {
            "status": state.supervisor_license_status,
            "holder_name": "Supervising LPC-S",
            "license_type": "LPC-S",
        }
    return payload


# Degradation presets for write_scan_image — see documents.py.
_HEAVY_DEGRADATION = {
    "rotate_degrees": 7,
    "blur_radius": 2.5,
    "noise_amount": 600,
    "contrast_factor": 0.35,
    "add_shadow": True,
}
_BENIGN_DEGRADATION = {"rotate_degrees": 3, "blur_radius": 0.3, "contrast_factor": 0.95}


def _license_slot_content(state: PacketBuildState) -> docs.DocumentContent:
    """What's in the license slot: normally the license itself, but D09
    (wrong document in slot) puts CV content there instead — independent
    of whether D10 also renders that slot as a degraded scan."""
    if state.uploaded_doc_type["license"] == "cv":
        injection = state.cv_injection_text if state.contains_injection["cv"] else None
        return docs.cv_content(state.provider, injection)
    return docs.license_content(state.provider)


def _render_license_slot(state: PacketBuildState, packet_dir: Path) -> Path:
    content = _license_slot_content(state)
    degradation = state.license_scan_degradation

    if degradation is None:
        path = packet_dir / "license.pdf"
        docs.write_pdf(path, content)
        return path

    path = packet_dir / "license.png"
    preset = _HEAVY_DEGRADATION if degradation == "heavy" else _BENIGN_DEGRADATION
    docs.write_scan_image(path, content, seed=state.provider.index, **preset)  # type: ignore[arg-type]
    return path


def _render_documents(state: PacketBuildState, packet_dir: Path) -> dict[str, Path]:
    p = state.provider
    paths: dict[str, Path] = {"license": _render_license_slot(state, packet_dir)}

    paths["coi"] = packet_dir / "coi.pdf"
    docs.render_coi(p, paths["coi"])

    paths["cv"] = packet_dir / "cv.pdf"
    docs.render_cv(p, paths["cv"], injection_text=state.cv_injection_text)

    paths["education"] = packet_dir / "education.pdf"
    docs.render_education(p, paths["education"])

    paths["w9"] = packet_dir / "w9.pdf"
    docs.render_w9(p, paths["w9"])

    return paths


def _apply_benign_variation(spec: PacketSpec, state: PacketBuildState) -> None:
    if spec.packet_id == "benign-1-nickname":
        # The SPEC.md section 7.5 fixture example, verbatim: "Jon" vs
        # "Jonathan" must PASS. Hardcoded (not derived from the Faker name)
        # so the nickname relationship is unambiguous. coi_insured_name is
        # overridden too (a provider fills out every form with the same
        # preferred name) - build_provider() already set it from the
        # pre-override legal_name, so leaving it alone here would silently
        # make the COI's insured name an unrelated Faker name instead of a
        # second instance of the same nickname relationship.
        state.provider = replace(
            state.provider,
            legal_name="Jonathan Alvarez",
            license_holder_name="Jon Alvarez",
            coi_insured_name="Jon Alvarez",
        )
        state.name_match_probabilities["R-LIC-004"] = 0.95
        state.name_match_probabilities["R-COI-004"] = 0.95
    elif spec.packet_id == "benign-2-rotated-scan":
        state.license_scan_degradation = "benign"
        state.legible_score["license"] = 0.85
    elif spec.packet_id == "benign-3-hyphenated-surname":
        state.provider = replace(
            state.provider,
            legal_name="Maria Garcia Lopez",
            license_holder_name="Maria Garcia-Lopez",
            coi_insured_name="Maria Garcia-Lopez",
        )
        # Ceiling mode needs ground truth to resolve to pass
        # deterministically (>= R-LIC-004/R-COI-004's min_probability
        # 0.9) - exactly at the threshold, not confidently above it
        # like benign-1's well-known nickname, since this variant is
        # genuinely less certain for a real matcher to resolve.
        state.name_match_probabilities["R-LIC-004"] = 0.90
        state.name_match_probabilities["R-COI-004"] = 0.90
    elif spec.packet_id == "benign-4-middle-initial":
        state.provider = replace(
            state.provider,
            legal_name="Robert J. Chen",
            license_holder_name="Robert Chen",
            coi_insured_name="Robert Chen",
        )
        state.name_match_probabilities["R-LIC-004"] = 0.90
        state.name_match_probabilities["R-COI-004"] = 0.90
    elif spec.packet_id == "benign-5-suffix":
        state.provider = replace(
            state.provider,
            legal_name="William Harrison III",
            license_holder_name="William Harrison",
            coi_insured_name="William Harrison",
        )
        state.name_match_probabilities["R-LIC-004"] = 0.90
        state.name_match_probabilities["R-COI-004"] = 0.90


def build_packet(spec: PacketSpec, index: int, fake: Faker, output_root: Path) -> BuiltPacket:
    provider: ProviderSpec = build_provider(index, TARGET_DATE, fake)
    state = initial_state(provider)

    _apply_benign_variation(spec, state)
    for defect_id in spec.defect_ids:
        apply_defect(state, defect_id, TARGET_DATE)

    documents = _build_documents(state)
    facts = _case_facts(state, TARGET_DATE, documents)

    packet_dir = output_root / "packets" / spec.packet_id
    document_paths = _render_documents(state, packet_dir)

    return BuiltPacket(
        packet_id=spec.packet_id,
        kind=spec.kind,
        defect_ids=spec.defect_ids,
        description=spec.description,
        target_date=TARGET_DATE,
        facts=facts,
        expected_findings=expected_findings(spec.defect_ids),
        registry_fixtures=_registry_fixture_payload(state),
        document_paths=document_paths,
    )
