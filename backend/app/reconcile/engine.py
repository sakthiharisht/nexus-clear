"""Reconcile (SPEC.md section 7.5): produces the resolved inputs
section 7.4's `name_match` and `registry_*` rules consume - a
similarity probability per name_match rule, a RegistryResult per
registry_* rule - written into CaseFacts for the rules engine
(app/rules/engine.py) to threshold. Code still decides pass/fail
(CLAUDE.md invariant 1); this stage only resolves facts.

name_match: normalized exact match (>= CLEAR_MATCH_THRESHOLD) or clear
mismatch (<= CLEAR_MISMATCH_THRESHOLD) resolves in code alone, no
model call at all. The ambiguous middle band, and every registry_*
rule (which always needs a real lookup, not just a comparison).

SPEC's own text also describes an intermediate Jev `same_person`
step before escalating to the Investigator for ambiguous names. M7
does not build that step: the user's own M7 instructions specify
only the Investigator ("the one real agent loop"), and CLAUDE.md
invariant 6 requires the whole pipeline to run on
DECISION_BACKEND=claude with zero Jev involvement anyway - adding a
Jev pre-filter here would be scope beyond what was asked, not a gap.
Flagged as a SPEC deviation, not a silent omission.

Entity resolution (which lookup key a registry rule queries by) is
the same hardcoded-per-kind mapping app/eval/baseline_reconcile.py
already uses - a second rule of any registry_* kind, or one querying
a different entity, would need this generalized.
"""

from __future__ import annotations

from app.reconcile.investigator import Investigator, NameMatchTask, RegistryTask
from app.reconcile.matching import CLEAR_MATCH_THRESHOLD, CLEAR_MISMATCH_THRESHOLD, name_similarity
from app.rules.context import CaseFacts, RegistryResult, get_path
from app.rules.schema import NameMatchParams, Rule, RulePack

_REGISTRY_KINDS = {"registry_status_check", "registry_flags_check", "registry_exclusion_check"}

# Maps each registry tool to the kwarg in RegistryTask.query that
# matches app/tools_mcp/server.py's EvidenceRecord.query for that tool
# (the value each tool's make_evidence_record call actually uses) -
# needed to correlate an Investigator's audit_log entry back to the
# task that caused it, so record_hash/fetched_at can be taken from
# the audit log (code-captured) rather than trusted from the model's
# own submission.
_PRIMARY_QUERY_KEY = {
    "nppes_lookup": "npi",
    "leie_check": "name",
    "tx_license_lookup": "license_number",
}


def _applies(rule: Rule, facts: CaseFacts) -> bool:
    gate = rule.applies_when
    if gate is None:
        return True
    return get_path(facts, gate.field) == gate.equals


def _resolve_registry_task(rule: Rule, facts: CaseFacts) -> RegistryTask | None:
    if rule.kind == "registry_status_check":
        key = get_path(facts, "supervision.supervisor_license_number")
        if not isinstance(key, str):
            return None
        return RegistryTask(
            rule_id=rule.id,
            kind="registry_status_check",
            tool="tx_license_lookup",
            query={"license_number": key},
        )
    if rule.kind == "registry_flags_check":
        npi = facts.profile.npi
        if not npi:
            return None
        return RegistryTask(
            rule_id=rule.id, kind="registry_flags_check", tool="nppes_lookup", query={"npi": npi}
        )
    if rule.kind == "registry_exclusion_check":
        legal_name = facts.profile.legal_name
        if not legal_name:
            return None
        return RegistryTask(
            rule_id=rule.id,
            kind="registry_exclusion_check",
            tool="leie_check",
            query={"name": legal_name},
        )
    return None


def _resolve_name_match_tasks(
    pack: RulePack, facts: CaseFacts
) -> tuple[dict[str, float], list[NameMatchTask]]:
    probabilities: dict[str, float] = {}
    tasks: list[NameMatchTask] = []
    for rule in pack.rules:
        if rule.kind != "name_match" or not _applies(rule, facts):
            continue
        params = NameMatchParams.model_validate(rule.params)
        left = get_path(facts, params.left)
        if not isinstance(left, str):
            continue

        candidates: list[tuple[str, str, float]] = []
        right = get_path(facts, params.right)
        if isinstance(right, str):
            candidates.append((params.right, right, name_similarity(left, right)))
        if params.alt_right:
            alt_right = get_path(facts, params.alt_right)
            if isinstance(alt_right, str):
                candidates.append((params.alt_right, alt_right, name_similarity(left, alt_right)))
        if not candidates:
            continue

        right_label, right_value, score = max(candidates, key=lambda c: c[2])
        if score >= CLEAR_MATCH_THRESHOLD or score <= CLEAR_MISMATCH_THRESHOLD:
            probabilities[rule.id] = score
        else:
            tasks.append(
                NameMatchTask(
                    rule_id=rule.id,
                    left_label=params.left,
                    left_value=left,
                    right_label=right_label,
                    right_value=right_value,
                )
            )
    return probabilities, tasks


def reconcile(pack: RulePack, facts: CaseFacts, *, investigator: Investigator) -> CaseFacts:
    name_match_probabilities, name_match_tasks = _resolve_name_match_tasks(pack, facts)

    registry_tasks: list[RegistryTask] = []
    for rule in pack.rules:
        if rule.kind not in _REGISTRY_KINDS or not _applies(rule, facts):
            continue
        task = _resolve_registry_task(rule, facts)
        if task is not None:
            registry_tasks.append(task)

    if not name_match_tasks and not registry_tasks:
        return facts.model_copy(update={"name_match_probabilities": name_match_probabilities})

    result = investigator.investigate(
        name_match_tasks=name_match_tasks, registry_tasks=registry_tasks
    )

    for conclusion in result.name_match_conclusions:
        name_match_probabilities[conclusion.rule_id] = conclusion.probability

    registry_results: dict[str, RegistryResult] = {}
    for registry_conclusion in result.registry_conclusions:
        task = next((t for t in registry_tasks if t.rule_id == registry_conclusion.rule_id), None)
        if task is None:
            continue
        query_key = _PRIMARY_QUERY_KEY[task.tool]
        audit_entry = next(
            (
                e
                for e in result.audit_log
                if e.tool_name == task.tool and e.query == task.query.get(query_key)
            ),
            None,
        )
        registry_results[registry_conclusion.rule_id] = RegistryResult(
            exists=registry_conclusion.exists,
            status=registry_conclusion.status,
            checks=registry_conclusion.checks,
            possible_match=registry_conclusion.possible_match,
            registry=task.tool,
            record_hash=audit_entry.record_hash if audit_entry else None,
            fetched_at=audit_entry.fetched_at if audit_entry else None,
        )

    return facts.model_copy(
        update={
            "name_match_probabilities": name_match_probabilities,
            "registry_results": registry_results,
        }
    )
