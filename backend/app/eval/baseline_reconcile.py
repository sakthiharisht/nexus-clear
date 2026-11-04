"""Baseline reconcile (SPEC.md section 14, M3; a deterministic, non-LLM
slice of section 7.5's Reconcile stage): rapidfuzz name matching and
registry lookups against the generator's FIXTURE-mode JSON. No Jev, no
Claude, no MCP tools - fills in CaseFacts.name_match_probabilities /
registry_results so the name_match and registry_* rule kinds can actually
be decided at baseline, instead of always reporting unknown.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.reconcile.matching import CLEAR_MATCH_THRESHOLD, CLEAR_MISMATCH_THRESHOLD, name_similarity
from app.rules.context import CaseFacts, RegistryResult, get_path
from app.rules.schema import NameMatchParams, RulePack

# SPEC.md section 7.5: "normalized exact match = pass; clear mismatch =
# fail; ambiguous -> Jev same_person score". Baseline reconcile can only
# faithfully implement the first two - leaving the ambiguous middle band
# unresolved (never a guess) is exactly what that section reserves for
# Jev/Claude (M5/M7), not available here. This means e.g. a genuine
# nickname pair ("Jon" vs "Jonathan") without a nickname table scores in
# the ambiguous band and stays unknown at baseline - a real, reported
# limitation (see the eval report's reconcile note), not a bug.


def reconcile_name_matches(pack: RulePack, facts: CaseFacts) -> dict[str, float]:
    probabilities: dict[str, float] = {}
    for rule in pack.rules:
        if rule.kind != "name_match":
            continue
        params = NameMatchParams.model_validate(rule.params)
        left = get_path(facts, params.left)
        if not isinstance(left, str):
            continue

        candidates: list[float] = []
        right = get_path(facts, params.right)
        if isinstance(right, str):
            candidates.append(name_similarity(left, right))
        if params.alt_right:
            alt_right = get_path(facts, params.alt_right)
            if isinstance(alt_right, str):
                candidates.append(name_similarity(left, alt_right))
        if not candidates:
            continue

        score = max(candidates)
        if score >= CLEAR_MATCH_THRESHOLD or score <= CLEAR_MISMATCH_THRESHOLD:
            probabilities[rule.id] = score
    return probabilities


def load_registry_fixtures(fixtures_root: Path) -> dict[str, dict[str, Any]]:
    registry_dir = fixtures_root / "registry"
    fixtures: dict[str, dict[str, Any]] = {}
    for tool in ("nppes", "tx_license", "leie"):
        path = registry_dir / f"{tool}.json"
        fixtures[tool] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return fixtures


def reconcile_registry_results(
    pack: RulePack, facts: CaseFacts, registry_fixtures: dict[str, dict[str, Any]]
) -> dict[str, RegistryResult]:
    """Entity resolution (which lookup key a rule queries by) is hardcoded
    per kind, since the pack currently has exactly one rule of each
    registry_* kind: registry_status_check always queries the supervisor's
    license number (R-SUP-001's only current use), registry_flags_check
    the provider's own NPI (R-ID-002), registry_exclusion_check the
    provider's own legal name (R-EXC-001). A second rule of any of these
    kinds, or one querying a different entity, would need this
    generalized rather than extended with more special cases.
    """
    results: dict[str, RegistryResult] = {}
    for rule in pack.rules:
        if rule.kind == "registry_status_check":
            key = get_path(facts, "supervision.supervisor_license_number")
            entry = registry_fixtures["tx_license"].get(key) if isinstance(key, str) else None
            if entry is not None:
                results[rule.id] = RegistryResult(
                    status=entry.get("status"), registry="tx_license_lookup"
                )
        elif rule.kind == "registry_flags_check":
            npi = facts.profile.npi
            entry = registry_fixtures["nppes"].get(npi) if npi else None
            if entry is not None:
                results[rule.id] = RegistryResult(
                    checks={
                        "exists": bool(entry.get("exists", False)),
                        "name_consistent": bool(entry.get("name_consistent", False)),
                        "taxonomy_counselor": bool(entry.get("taxonomy_counselor", False)),
                    },
                    registry="nppes",
                )
        elif rule.kind == "registry_exclusion_check":
            legal_name = facts.profile.legal_name
            entry = registry_fixtures["leie"].get(legal_name) if legal_name else None
            if entry is not None:
                results[rule.id] = RegistryResult(
                    possible_match=entry.get("possible_match"), registry="leie"
                )
    return results
