"""Direct unit tests for app.eval.report's classify-section rendering.
test_run.py exercises render_markdown_report end to end against the
real committed cache, which (since M5.1) has no simulated rows left -
these tests pin the simulated-caveat and easy/hard-split behavior with
fabricated data instead, so that real data flipping to "all real"
doesn't silently drop coverage of the still-reachable simulated path.
"""

from __future__ import annotations

from app.eval.report import _classify_section, _is_hard_mode, _simulated_caveat

_METRICS_TEMPLATE: dict[str, object] = {
    "n": 10,
    "accuracy": 1.0,
    "ece": 0.05,
    "escalation_rate": 0.1,
    "total_input_tokens": 100,
    "total_output_tokens": 20,
    "total_cost_usd": 0.001,
    "cost_known": True,
    "mean_latency_ms": 500.0,
}


def test_simulated_caveat_is_empty_when_nothing_is_simulated() -> None:
    assert _simulated_caveat({"classify-claude-haiku": _METRICS_TEMPLATE}) == []


def test_simulated_caveat_names_only_the_simulated_mode() -> None:
    modes = {
        "classify-claude-haiku": _METRICS_TEMPLATE,
        "classify-jev-SIMULATED": _METRICS_TEMPLATE,
    }
    lines = _simulated_caveat(modes)
    assert len(lines) == 2  # one caveat sentence + a trailing blank line
    assert "classify-jev-SIMULATED" in lines[0]
    assert "classify-claude-haiku" not in lines[0]


def test_is_hard_mode_detects_hard_with_and_without_simulated_suffix() -> None:
    assert _is_hard_mode("classify-claude-haiku-hard") is True
    assert _is_hard_mode("classify-claude-haiku-hard-SIMULATED") is True
    assert _is_hard_mode("classify-claude-haiku") is False
    assert _is_hard_mode("classify-claude-haiku-SIMULATED") is False


def test_classify_section_splits_easy_and_hard_into_separate_tables() -> None:
    result = {
        "classify_metrics": {
            "classify-claude-haiku": _METRICS_TEMPLATE,
            "classify-claude-haiku-hard": {**_METRICS_TEMPLATE, "n": 29},
        }
    }
    section = "\n".join(_classify_section(result))
    assert "Easy set" in section
    assert "Hard set" in section
    assert "Too small to support ranking" in section

    easy_part, hard_part = section.split("Hard set")
    # The easy table's row for "classify-claude-haiku" must not be
    # mistaken for the hard-set row sharing that prefix.
    assert "| classify-claude-haiku |" in easy_part
    assert "| classify-claude-haiku-hard |" not in easy_part
    assert "| classify-claude-haiku-hard |" in hard_part


def test_classify_section_shows_simulated_caveat_when_a_mode_is_simulated() -> None:
    result = {
        "classify_metrics": {
            "classify-jev-hard-SIMULATED": {**_METRICS_TEMPLATE, "n": 29},
        }
    }
    section = "\n".join(_classify_section(result))
    assert "classify-jev-hard-SIMULATED" in section
    assert "was built from app/eval/classify_fixture_seed.py" in section


def test_classify_section_returns_empty_when_no_classify_metrics() -> None:
    assert _classify_section({"classify_metrics": {}}) == []
    assert _classify_section({}) == []
