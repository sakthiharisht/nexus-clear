"""Integration tests for the M3 eval runner against the real committed
fixtures (rules/tx_bcbstx_lpc.yaml + eval/fixtures/ground_truth.json) —
no LLM calls anywhere in this path.
"""

import json
from pathlib import Path

import pytest
import yaml

from app.eval.report import render_markdown_report
from app.eval.run import load_config, main, run_eval

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_CONFIG_PATH = REPO_ROOT / "eval" / "config.yaml"


def test_load_config_reads_the_real_config() -> None:
    config = load_config(REAL_CONFIG_PATH)
    assert config["rule_pack"] == "rules/tx_bcbstx_lpc.yaml"
    assert set(config["modes"]) == {"ceiling", "baseline"}


def test_load_config_rejects_a_non_mapping_yaml_file(tmp_path: Path) -> None:
    bad_config = tmp_path / "config.yaml"
    bad_config.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a YAML mapping"):
        load_config(bad_config)


def test_ceiling_mode_is_a_perfect_sanity_check() -> None:
    config = load_config(REAL_CONFIG_PATH)
    result = run_eval({**config, "modes": ["ceiling"]}, REPO_ROOT)
    metrics = result["metrics"]["ceiling"]

    assert metrics["exact_match_rate"] == 1.0
    assert metrics["false_positives_on_clean_or_benign"] == 0
    assert metrics["unexplained_miss_count"] == 0
    assert metrics["structural_miss_count"] == 0
    assert metrics["overlap_explained_miss_count"] == 0


def test_baseline_mode_has_no_false_positives_and_every_miss_is_explained() -> None:
    config = load_config(REAL_CONFIG_PATH)
    result = run_eval({**config, "modes": ["baseline"]}, REPO_ROOT)
    metrics = result["metrics"]["baseline"]

    # The whole point of "never guess": baseline may fall back to unknown
    # a lot, but it must never confidently assert a clean/benign packet
    # has a problem it doesn't have.
    assert metrics["false_positives_on_clean_or_benign"] == 0
    # Every real gap in this fixture set is accounted for as either a
    # known structural limitation (no Reconcile/MCP, no OCR) or a
    # documented defect-overlap — not a mystery regression.
    assert metrics["unexplained_miss_count"] == 0
    assert metrics["structural_miss_count"] + metrics["overlap_explained_miss_count"] > 0


def test_markdown_report_mentions_both_modes() -> None:
    config = load_config(REAL_CONFIG_PATH)
    result = run_eval(config, REPO_ROOT)
    report = render_markdown_report(result)

    assert "ceiling" in report
    assert "baseline" in report
    assert "Overlap-explained" in report
    assert "—" not in report  # no em dashes - plain ASCII for portability


def test_main_writes_a_json_run_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_dir = tmp_path / "runs"
    config = load_config(REAL_CONFIG_PATH)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump({**config, "output_dir": str(output_dir)}), encoding="utf-8"
    )

    monkeypatch.setattr("sys.argv", ["app.eval.run", "--config", str(config_path)])
    main()

    run_files = list(output_dir.glob("run-*.json"))
    assert len(run_files) == 1
    written = json.loads(run_files[0].read_text(encoding="utf-8"))
    assert "ceiling" in written["metrics"]
    assert "baseline" in written["metrics"]
