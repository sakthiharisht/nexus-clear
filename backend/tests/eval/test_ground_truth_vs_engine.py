"""M2's core correctness test: feed each packet's ground-truth CaseFacts
into the real M1 rules engine (no LLM, no extraction, no tool calls) and
assert it produces exactly the hand-authored expected findings from
app/eval/generator/expected.py.

This is NOT the same as recording whatever the engine happens to output —
expected.py's baseline + per-defect overrides were written independently,
from what each defect *should* do to which rule_id, before ever being
compared to the engine's actual behavior. A mismatch here means either the
engine has a bug or the ground truth's understanding of a rule is wrong;
either way, it's a real finding, not a tautology.
"""

from pathlib import Path

import pytest
from faker import Faker

from app.eval.generator.build import DEFAULT_SEED
from app.eval.generator.packets import PACKET_SPECS, BuiltPacket, PacketSpec, build_packet
from app.rules.engine import evaluate_rule_pack
from app.rules.loader import load_rule_pack
from app.rules.schema import RulePack

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_PACK_PATH = REPO_ROOT / "rules" / "tx_bcbstx_lpc.yaml"


@pytest.fixture(scope="module")
def rule_pack() -> RulePack:
    return load_rule_pack(REAL_PACK_PATH)


@pytest.fixture(scope="module")
def built_packets(tmp_path_factory: pytest.TempPathFactory) -> dict[str, BuiltPacket]:
    output_root = tmp_path_factory.mktemp("eval-ground-truth")
    Faker.seed(DEFAULT_SEED)
    fake = Faker()
    return {
        spec.packet_id: build_packet(spec, index, fake, output_root)
        for index, spec in enumerate(PACKET_SPECS)
    }


@pytest.mark.parametrize("spec", PACKET_SPECS, ids=lambda s: s.packet_id)
def test_packet_matches_hand_authored_expectations(
    spec: PacketSpec, rule_pack: RulePack, built_packets: dict[str, BuiltPacket]
) -> None:
    built = built_packets[spec.packet_id]

    findings = evaluate_rule_pack(rule_pack, built.facts, built.target_date)
    actual = {f.finding_id: f.status for f in findings}

    assert actual == built.expected_findings


def test_clean_and_benign_packets_have_zero_fails(
    rule_pack: RulePack, built_packets: dict[str, BuiltPacket]
) -> None:
    for spec in PACKET_SPECS:
        if spec.kind not in ("clean", "benign"):
            continue
        built = built_packets[spec.packet_id]
        findings = evaluate_rule_pack(rule_pack, built.facts, built.target_date)
        fails = [f.rule_id for f in findings if f.status == "fail"]
        assert fails == [], f"{spec.packet_id}: unexpected false positive(s) {fails}"


def test_d14_injection_is_flagged_info_only_with_no_other_behavior_change(
    rule_pack: RulePack, built_packets: dict[str, BuiltPacket]
) -> None:
    built = built_packets["defective-7"]
    results = evaluate_rule_pack(rule_pack, built.facts, built.target_date)
    findings = {f.finding_id: f for f in results}

    injection_finding = findings["R-SEC-001:doc-cv"]
    assert injection_finding.status == "fail"
    assert injection_finding.severity == "info"

    # Every finding not explicitly overridden by D09/D10/D14 in expected.py
    # still matches the clean baseline — the injected text changed nothing
    # else (CLAUDE.md invariant 3: documents are untrusted data).
    for finding_id, status in built.expected_findings.items():
        assert findings[finding_id].status == status
