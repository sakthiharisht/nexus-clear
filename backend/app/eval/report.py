"""Markdown rendering of an eval run's metrics (SPEC.md section 14, M3).
Pure string formatting - app/eval/run.py prints the result to stdout and
separately writes the full JSON to eval/runs/.
"""

from __future__ import annotations

from typing import Any


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _mode_table_row(mode: str, metrics: dict[str, Any]) -> str:
    return (
        f"| {mode} | {_pct(metrics['exact_match_rate'])} "
        f"| {_pct(metrics['primary_defect_detected_rate'])} "
        f"| {metrics['false_positives_on_clean_or_benign']} "
        f"({_pct(metrics['false_positive_rate_clean_benign'])}) "
        f"| {_pct(metrics['unknown_rate'])} |"
    )


def _per_rule_table(metrics: dict[str, Any]) -> list[str]:
    lines = [
        "| rule_id | TP | FP | FN | TN | precision | recall |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for rule_id in sorted(metrics["per_rule"]):
        r = metrics["per_rule"][rule_id]
        precision = "-" if r["true_positive"] + r["false_positive"] == 0 else (
            f"{r['true_positive'] / (r['true_positive'] + r['false_positive']):.2f}"
        )
        recall = "-" if r["true_positive"] + r["false_negative"] == 0 else (
            f"{r['true_positive'] / (r['true_positive'] + r['false_negative']):.2f}"
        )
        lines.append(
            f"| {rule_id} | {r['true_positive']} | {r['false_positive']} | "
            f"{r['false_negative']} | {r['true_negative']} | {precision} | {recall} |"
        )
    return lines


def _per_defect_table(metrics: dict[str, Any]) -> list[str]:
    lines = ["| defect_id | detected |", "| --- | --- |"]
    for defect_id in sorted(metrics["per_defect_detected"]):
        mark = "yes" if metrics["per_defect_detected"][defect_id] else "no"
        lines.append(f"| {defect_id} | {mark} |")
    return lines


def _misses_section(metrics: dict[str, Any], category: str, title: str) -> list[str]:
    rows = [m for m in metrics["misses"] if m["category"] == category]
    if not rows:
        return [f"### {title}", "", "None.", ""]
    lines = [f"### {title} ({len(rows)})", ""]
    for m in rows:
        lines.append(
            f"- `{m['packet_id']}` / `{m['finding_id']}`: expected `{m['expected']}`, "
            f"got `{m['actual']}` - {m['explanation']}"
        )
    lines.append("")
    return lines


def render_markdown_report(result: dict[str, Any]) -> str:
    lines = [
        "# M3 eval run",
        "",
        f"rule_pack_version: `{result['rule_pack_version']}`  "
        f"ground_truth_seed: `{result['ground_truth_seed']}`",
        "",
        "## Mode comparison",
        "",
        "| mode | exact match | primary defect detected "
        "| false positives (clean/benign) | unknown rate |",
        "| --- | --- | --- | --- | --- |",
    ]
    for mode in result["metrics"]:
        lines.append(_mode_table_row(mode, result["metrics"][mode]))
    lines.append("")

    for mode, metrics in result["metrics"].items():
        lines.append(f"## {mode} - per-rule precision/recall")
        lines.append("")
        lines += _per_rule_table(metrics)
        lines.append("")
        lines.append(f"## {mode} - per-defect detection")
        lines.append("")
        lines += _per_defect_table(metrics)
        lines.append("")
        lines.append(f"## {mode} - misses")
        lines.append("")
        lines += _misses_section(metrics, "overlap_explained", "Overlap-explained")
        lines += _misses_section(
            metrics, "structural_no_reconcile", "Structural: no Reconcile/MCP yet"
        )
        lines += _misses_section(
            metrics, "structural_no_ocr", "Structural: no OCR for scanned documents"
        )
        lines += _misses_section(metrics, "unexplained", "Unexplained (needs investigation)")

    return "\n".join(lines)
