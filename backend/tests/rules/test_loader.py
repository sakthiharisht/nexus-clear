"""Loader tests: the real pack loads; every way a pack can be malformed is
rejected with a RulePackError (M1 accept criterion)."""

import copy
from pathlib import Path
from typing import Any

import pytest

from app.rules.loader import RulePackError, load_rule_pack

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_PACK_PATH = REPO_ROOT / "rules" / "tx_bcbstx_lpc.yaml"


def _minimal_pack_dict() -> dict[str, Any]:
    """A small, valid pack — used as a base that negative tests mutate."""
    return {
        "pack_id": "test-pack",
        "version": "0.0.1",
        "jurisdiction": "TX",
        "payer": "TEST",
        "provider_type": "LPC",
        "application_path": "CAQH",
        "target_date_default_offset_days": 14,
        "sources": {
            "internal_policy": {
                "url": None,
                "doc_date": None,
                "last_verified": "2026-11-03",
                "notes": "Thresholds chosen by this project.",
            },
        },
        "required_slots": [
            {
                "slot": "license",
                "doc_type": "texas_lpc_license",
                "required": True,
                "source": "internal_policy",
                "needs_verification": False,
            },
        ],
        "rules": [
            {
                "id": "R-DOC-001",
                "title": "Uploaded document matches the checklist slot",
                "severity": "blocker",
                "kind": "doc_type_match",
                "params": {},
                "source": "internal_policy",
                "needs_verification": False,
            },
        ],
    }


def _write_pack(tmp_path: Path, data: dict[str, Any]) -> Path:
    import yaml

    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return pack_path


# ---- positive cases ----------------------------------------------------


def test_loads_the_real_seed_pack() -> None:
    pack = load_rule_pack(REAL_PACK_PATH)
    assert pack.pack_id == "tx-bcbstx-lpc"
    assert len(pack.rules) == 18
    # Every rule's params must already match its kind (Rule's own
    # model_validator enforces this at load time); re-checking here just
    # documents the expectation for readers of this test.
    for rule in pack.rules:
        rule.parsed_params()


def test_loads_a_minimal_valid_pack(tmp_path: Path) -> None:
    pack = load_rule_pack(_write_pack(tmp_path, _minimal_pack_dict()))
    assert pack.pack_id == "test-pack"
    assert len(pack.rules) == 1


# ---- malformed-pack rejection -------------------------------------------


def test_missing_file() -> None:
    with pytest.raises(RulePackError):
        load_rule_pack("does/not/exist.yaml")


def test_not_valid_yaml(tmp_path: Path) -> None:
    pack_path = tmp_path / "bad.yaml"
    pack_path.write_text("pack_id: [unclosed", encoding="utf-8")
    with pytest.raises(RulePackError):
        load_rule_pack(pack_path)


def test_top_level_must_be_a_mapping(tmp_path: Path) -> None:
    pack_path = tmp_path / "list.yaml"
    pack_path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(RulePackError):
        load_rule_pack(pack_path)


def test_missing_required_field(tmp_path: Path) -> None:
    data = _minimal_pack_dict()
    del data["pack_id"]
    with pytest.raises(RulePackError):
        load_rule_pack(_write_pack(tmp_path, data))


def test_unknown_severity_value(tmp_path: Path) -> None:
    data = _minimal_pack_dict()
    data["rules"][0]["severity"] = "catastrophic"
    with pytest.raises(RulePackError):
        load_rule_pack(_write_pack(tmp_path, data))


def test_unknown_kind_value(tmp_path: Path) -> None:
    data = _minimal_pack_dict()
    data["rules"][0]["kind"] = "vibes_check"
    with pytest.raises(RulePackError):
        load_rule_pack(_write_pack(tmp_path, data))


def test_duplicate_rule_id(tmp_path: Path) -> None:
    data = _minimal_pack_dict()
    data["rules"].append(copy.deepcopy(data["rules"][0]))
    with pytest.raises(RulePackError):
        load_rule_pack(_write_pack(tmp_path, data))


def test_rule_source_not_in_sources(tmp_path: Path) -> None:
    data = _minimal_pack_dict()
    data["rules"][0]["source"] = "nonexistent_source"
    with pytest.raises(RulePackError):
        load_rule_pack(_write_pack(tmp_path, data))


def test_required_slot_source_not_in_sources(tmp_path: Path) -> None:
    data = _minimal_pack_dict()
    data["required_slots"][0]["source"] = "nonexistent_source"
    with pytest.raises(RulePackError):
        load_rule_pack(_write_pack(tmp_path, data))


def test_duplicate_required_slot(tmp_path: Path) -> None:
    data = _minimal_pack_dict()
    data["required_slots"].append(copy.deepcopy(data["required_slots"][0]))
    with pytest.raises(RulePackError):
        load_rule_pack(_write_pack(tmp_path, data))


def test_params_missing_a_required_field_for_its_kind(tmp_path: Path) -> None:
    data = _minimal_pack_dict()
    data["rules"][0]["kind"] = "enum_match"
    data["rules"][0]["params"] = {"field": "license.license_type"}  # missing "allowed"
    with pytest.raises(RulePackError):
        load_rule_pack(_write_pack(tmp_path, data))


def test_params_has_an_unknown_key_for_its_kind(tmp_path: Path) -> None:
    data = _minimal_pack_dict()
    data["rules"][0]["params"] = {"this_is_not_a_real_param": True}
    with pytest.raises(RulePackError):
        load_rule_pack(_write_pack(tmp_path, data))


def test_numeric_min_pair_fields_and_mins_length_mismatch(tmp_path: Path) -> None:
    data = _minimal_pack_dict()
    data["rules"][0]["kind"] = "numeric_min_pair"
    data["rules"][0]["params"] = {
        "fields": ["coi.per_occurrence", "coi.aggregate"],
        "mins": [100000],
    }
    with pytest.raises(RulePackError):
        load_rule_pack(_write_pack(tmp_path, data))


def test_registry_check_with_no_decision_mode_is_rejected(tmp_path: Path) -> None:
    data = _minimal_pack_dict()
    data["rules"][0]["kind"] = "registry_check"
    data["rules"][0]["params"] = {"tool": "nppes_lookup"}  # none of the 3 modes set
    with pytest.raises(RulePackError):
        load_rule_pack(_write_pack(tmp_path, data))


def test_registry_check_with_two_decision_modes_is_rejected(tmp_path: Path) -> None:
    data = _minimal_pack_dict()
    data["rules"][0]["kind"] = "registry_check"
    data["rules"][0]["params"] = {
        "tool": "nppes_lookup",
        "expect_status": "Active",
        "expect": ["exists"],
    }
    with pytest.raises(RulePackError):
        load_rule_pack(_write_pack(tmp_path, data))


def test_unknown_top_level_key_is_rejected(tmp_path: Path) -> None:
    data = _minimal_pack_dict()
    data["totally_made_up_field"] = 123
    with pytest.raises(RulePackError):
        load_rule_pack(_write_pack(tmp_path, data))
