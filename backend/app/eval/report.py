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
        f"| {_pct(metrics['unknown_rate'])} "
        f"| {_pct(metrics['coverage'])} "
        f"| {_pct(metrics['accuracy_when_decided'])} |"
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


def _packets_table(result: dict[str, Any]) -> list[str]:
    """One row per packet: kind, every planted defect, and which one is
    primary (first-listed, by convention - see
    app/eval/generator/build.py's primary_defect field and
    app/eval/metrics.py's primary_defect_detected_rate)."""
    any_mode = next(iter(result["modes"].values()))
    lines = [
        "| packet_id | kind | primary defect | all defects |",
        "| --- | --- | --- | --- |",
    ]
    for packet in any_mode["packets"]:
        defect_ids = packet["defect_ids"]
        primary = defect_ids[0] if defect_ids else "-"
        all_defects = ", ".join(defect_ids) if defect_ids else "-"
        lines.append(f"| {packet['packet_id']} | {packet['kind']} | {primary} | {all_defects} |")
    return lines


def _classify_table_row(mode: str, metrics: dict[str, Any]) -> str:
    tokens = f"{metrics['total_input_tokens']}/{metrics['total_output_tokens']}"
    cost = f"${metrics['total_cost_usd']:.4f}" if metrics["cost_known"] else "n/a"
    return (
        f"| {mode} | {metrics['n']} | {_pct(metrics['accuracy'])} "
        f"| {metrics['ece']:.3f} | {_pct(metrics['escalation_rate'])} "
        f"| {tokens} | {cost} | {metrics['mean_latency_ms']:.0f} |"
    )


def _is_hard_mode(mode: str) -> bool:
    return mode.removesuffix("-SIMULATED").endswith("-hard")


def _simulated_caveat(modes: dict[str, Any]) -> list[str]:
    simulated_modes = [mode for mode in modes if mode.endswith("-SIMULATED")]
    if not simulated_modes:
        return []
    return [
        "**A mode name ending in -SIMULATED (" + ", ".join(sorted(simulated_modes)) + ") "
        "was built from app/eval/classify_fixture_seed.py's simulated fixtures, not "
        "real model output - see the M5/M5.1 completion reports for why. Every other "
        "mode below is a real recorded response "
        "(app/eval/live_classify.py, MODEL_CACHE_MODE=record).**",
        "",
    ]


def _classify_table(modes: dict[str, Any]) -> list[str]:
    lines = [
        "| mode | n | accuracy | ECE | escalation rate | tokens (in/out) "
        "| cost | mean latency (ms) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for mode, metrics in modes.items():
        lines.append(_classify_table_row(mode, metrics))
    lines.append("")
    return lines


def _classify_section(result: dict[str, Any]) -> list[str]:
    classify_metrics = result.get("classify_metrics", {})
    if not classify_metrics:
        return []
    easy_modes = {m: v for m, v in classify_metrics.items() if not _is_hard_mode(m)}
    hard_modes = {m: v for m, v in classify_metrics.items() if _is_hard_mode(m)}

    lines = [
        "## M5 Classify",
        "",
        "SPEC.md section 7.2: accuracy is over accepted (non-escalated) "
        "documents only - the honest end-to-end number, matching how the "
        "M3 baseline's accuracy_when_decided excludes undecided findings. "
        "ECE (expected calibration error) covers every prediction, "
        "escalated or not - calibration is a property of what the model "
        "said, whether or not the policy trusted it.",
        "",
        "**classify-jev and classify-claude-* run each backend alone with "
        "no fallback - raw per-backend numbers. classify-policy-claude "
        "runs the real DECISION_BACKEND=claude wiring "
        "(app/backends/factory.py), proving CLAUDE.md invariant 6 with "
        "zero Jev involvement.**",
        "",
    ]
    lines += _simulated_caveat(classify_metrics)

    if easy_modes:
        any_n = next(iter(easy_modes.values()))["n"]
        lines += [f"### Easy set ({any_n} documents)", ""]
        lines += _classify_table(easy_modes)

    if hard_modes:
        any_n = next(iter(hard_modes.values()))["n"]
        lines += [
            f"### Hard set ({any_n} adversarial documents - "
            "app/eval/generator/hard_classify_set.py)",
            "",
            f"**n={any_n} per tier. Too small to support ranking tiers against each "
            "other, or against the easy set above - a few documents flipping would "
            "change the ordering. Read these as rough signal (does accuracy hold up "
            "at all on harder inputs?), not a leaderboard.**",
            "",
        ]
        lines += _classify_table(hard_modes)

    return lines


def _extract_table_row(mode: str, metrics: dict[str, Any]) -> str:
    tokens = f"{metrics['total_input_tokens']}/{metrics['total_output_tokens']}"
    cost = f"${metrics['total_cost_usd']:.4f}" if metrics["cost_known"] else "n/a"
    return (
        f"| {mode} | {metrics['n_documents']} | {_pct(metrics['overall_coverage'])} "
        f"| {_pct(metrics['overall_accuracy_when_known'])} "
        f"| {_pct(metrics['quote_verified_rate'])} "
        f"| {tokens} | {cost} | {metrics['mean_latency_ms']:.0f} |"
    )


def _extract_field_table(extract_metrics: dict[str, Any]) -> list[str]:
    modes = list(extract_metrics)
    fields: list[str] = []
    seen = set()
    for mode in modes:
        for field in extract_metrics[mode]["per_field"]:
            if field not in seen:
                seen.add(field)
                fields.append(field)

    lines = [
        "| field | " + " | ".join(modes) + " |",
        "| --- | " + " | ".join("---" for _ in modes) + " |",
    ]
    for field in fields:
        cells = []
        for mode in modes:
            per_field = extract_metrics[mode]["per_field"].get(field)
            if per_field is None:
                cells.append("-")
                continue
            cells.append(
                f"cov {_pct(per_field['coverage'])} / acc {_pct(per_field['accuracy_when_known'])}"
            )
        lines.append(f"| {field} | " + " | ".join(cells) + " |")
    lines.append("")
    return lines


def _is_vision_mode(mode: str) -> bool:
    return mode.removesuffix("-SIMULATED").endswith("-vision") or mode == "extract-vision-baseline"


def _is_hard_extract_mode(mode: str) -> bool:
    return mode.removesuffix("-SIMULATED").endswith("-hard") and not _is_vision_mode(mode)


def _hard_extract_category_table(result: dict[str, Any], modes: dict[str, Any]) -> list[str]:
    """Per-category accuracy (app/eval/generator/hard_extraction_set.py's
    6 categories, stored as DocumentExtraction.slot for hard-mode rows)
    - a model's narrative-reading ability and its multi-page handling
    are different capabilities that would otherwise average out in
    the single per-field table."""
    extract_modes_raw = result.get("extract_modes", {})
    categories: list[str] = []
    seen = set()
    rows: dict[str, dict[str, tuple[int, int]]] = {}  # mode -> category -> (correct, total)

    for mode in modes:
        raw = extract_modes_raw.get(mode)
        if raw is None:
            continue
        per_category: dict[str, tuple[int, int]] = {}
        for doc in raw["documents"]:
            category = doc["slot"]
            if category not in seen:
                seen.add(category)
                categories.append(category)
            decidable = [f for f in doc["field_results"] if f["expected"] is not None]
            correct = sum(1 for f in decidable if f["correct"])
            total = len(decidable)
            prev_correct, prev_total = per_category.get(category, (0, 0))
            per_category[category] = (prev_correct + correct, prev_total + total)
        rows[mode] = per_category

    lines = [
        "| category | " + " | ".join(modes) + " |",
        "| --- | " + " | ".join("---" for _ in modes) + " |",
    ]
    for category in sorted(categories):
        cells = []
        for mode in modes:
            correct, total = rows.get(mode, {}).get(category, (0, 0))
            cells.append(f"{_pct(correct / total) if total else 'n/a'} ({correct}/{total})")
        lines.append(f"| {category} | " + " | ".join(cells) + " |")
    lines.append("")
    return lines


def _extract_mode_table(modes: dict[str, Any]) -> list[str]:
    lines = [
        "| mode | n documents | coverage | accuracy when known "
        "| quote_verified rate | tokens (in/out) | cost | mean latency (ms) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for mode, metrics in modes.items():
        lines.append(_extract_table_row(mode, metrics))
    lines.append("")
    return lines


def _extract_section(result: dict[str, Any]) -> list[str]:
    extract_metrics = result.get("extract_metrics", {})
    if not extract_metrics:
        return []
    vision_modes = {m: v for m, v in extract_metrics.items() if _is_vision_mode(m)}
    hard_modes = {m: v for m, v in extract_metrics.items() if _is_hard_extract_mode(m)}
    main_modes = {
        m: v for m, v in extract_metrics.items() if m not in vision_modes and m not in hard_modes
    }

    lines = [
        "## M6 Extract",
        "",
        "SPEC.md section 7.3: coverage is the share of fields where "
        "ground truth has a real value AND the field was extracted as "
        "`known` (not demoted to `unknown`); accuracy_when_known is, of "
        "those, the share whose value actually matches ground truth - "
        "mirroring the M3 baseline's coverage/accuracy_when_decided "
        "split (a model that's honestly cautious scores differently "
        "from one that's confidently wrong). Scope: only "
        "license/coi/cv are scored - education/w9 have no ground-truth "
        "field values in this fixture set to score against (see "
        "app/eval/extract_run.py's module docstring).",
        "",
    ]
    lines += _simulated_caveat(extract_metrics)

    if main_modes:
        lines += _extract_mode_table(main_modes)
        lines += ["### Per-field coverage / accuracy", ""]
        lines += _extract_field_table(main_modes)

    if vision_modes:
        any_n = next(iter(vision_modes.values()))["n_documents"]
        lines += [
            f"### Vision (n={any_n} image-only license scans - "
            "app/eval/extract_vision_run.py)",
            "",
            f"**n={any_n} per tier - the two scan documents in this corpus "
            "(a genuine rotated license scan, and an illegible wrong-document "
            "scan). Too small to rank tiers against each other. Read as a "
            "capability check (can vision read a scan at all, and does it "
            "correctly report unknown rather than hallucinate on a bad one) "
            "- extract-vision-baseline is M3's regex extractor, which has no "
            "OCR at all, included to make that contrast explicit: its "
            "coverage is 0% by construction, not a bug.**",
            "",
        ]
        lines += _extract_mode_table(vision_modes)
        lines += ["### Vision per-field coverage / accuracy", ""]
        lines += _extract_field_table(vision_modes)

    if hard_modes:
        any_n = next(iter(hard_modes.values()))["n_documents"]
        lines += [
            f"### Hard extraction set (n={any_n} - "
            "app/eval/generator/hard_extraction_set.py)",
            "",
            f"**n={any_n} across 6 categories (noisy layouts, narrative prose, "
            "multi-page documents, unusual CV formatting, ambiguous MM/DD "
            "dates, name suffixes). Too small to rank tiers against each "
            "other or against the main 12-packet set above - read per "
            "category below, not as one blended score: a model's "
            "narrative-reading ability and its multi-page handling are "
            "different capabilities that would otherwise average out.**",
            "",
        ]
        lines += _extract_mode_table(hard_modes)
        lines += ["### Hard set accuracy by category (correct/decidable)", ""]
        lines += _hard_extract_category_table(result, hard_modes)

    return lines


def _escalate_section(result: dict[str, Any]) -> list[str]:
    metrics = result.get("escalate_metrics")
    if not metrics:
        return []

    precision = "n/a" if metrics["precision"] is None else f"{metrics['precision']:.2f}"
    recall = "n/a" if metrics["recall"] is None else f"{metrics['recall']:.2f}"
    lines = [
        "## M8 Escalate",
        "",
        "SPEC.md section 7.7: every Finding is escalated or not "
        "(app/escalate/engine.py's five criteria - low confidence, a "
        "blocker's stricter confidence bar, an LEIE possible match, an "
        "unverified quote feeding a blocker, an injection flag). "
        "Precision/recall are scored against this corpus's own known "
        "escalation-relevant defects (app/eval/escalate_run.py's "
        "GROUND_TRUTH_ESCALATIONS) - the confidence-driven criteria "
        "aren't exhaustively exercised by this 12-packet set alone; "
        "see that module's docstring for what is and isn't covered "
        "here.",
        "",
        "| mode | total findings | escalated | escalation rate | precision | recall |",
        "| --- | --- | --- | --- | --- | --- |",
        f"| {metrics['mode']} | {metrics['total_findings']} | {metrics['escalated_count']} "
        f"| {metrics['escalation_rate']:.3f} | {precision} | {recall} |",
        "",
    ]
    if metrics["simulated"]:
        lines += [
            "**SIMULATED**: at least one extraction in this run came from a "
            "placeholder fixture, not a live model call - treat these "
            "numbers as provisional.",
            "",
        ]
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
        "## Packets",
        "",
    ]
    lines += _packets_table(result)
    lines += [
        "",
        "## Mode comparison",
        "",
        "| mode | exact match | primary defect detected "
        "| false positives (clean/benign) | unknown rate | coverage | accuracy when decided |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for mode in result["metrics"]:
        lines.append(_mode_table_row(mode, result["metrics"][mode]))
    lines.append("")

    if "baseline" in result["metrics"]:
        lines += [
            "**Baseline caveats** - read these numbers as an upper bound on what "
            "regex/fuzzy-matching can do, not a general benchmark:",
            "- Field extraction (app/eval/baseline_extraction.py) is regex matched "
            "against this project's own renderer's exact \"Label: value\" line "
            "format. It will not generalize to real-world document layouts the "
            "way an LLM-based extractor would.",
            "- Name matching (app/eval/baseline_reconcile.py) is rapidfuzz "
            "token_sort_ratio with no nickname table, so it only resolves clear "
            "matches and clear mismatches - a genuine nickname pair (\"Jon\" vs "
            "\"Jonathan\") scores in the ambiguous middle and stays unknown. See "
            "the structural_no_reconcile misses below for exactly where this "
            "shows up.",
            "",
        ]

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
        lines += _misses_section(
            metrics, "structural_wrong_doc_type", "Structural: wrong document type in slot"
        )
        lines += _misses_section(
            metrics, "structural_extraction_failed", "Structural: extraction error"
        )
        lines += _misses_section(metrics, "unexplained", "Unexplained (needs investigation)")

    lines += _classify_section(result)
    lines += _extract_section(result)
    lines += _escalate_section(result)

    return "\n".join(lines)
