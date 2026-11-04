"""Name normalization/similarity shared by app/eval/baseline_reconcile.py
(M3's non-LLM baseline) and app/reconcile/engine.py (M7's real
pipeline) - one implementation, so the "normalized exact match /
clear mismatch / ambiguous" bands SPEC.md section 7.5 describes can't
drift between the two.
"""

from __future__ import annotations

from rapidfuzz import fuzz

# SPEC.md section 7.5: "normalized exact match = pass; clear mismatch =
# fail; ambiguous -> Jev same_person score" (M7 uses the Investigator
# directly for the ambiguous band instead of a Jev pre-filter - see
# app/reconcile/engine.py's module docstring for why).
CLEAR_MATCH_THRESHOLD = 0.95
CLEAR_MISMATCH_THRESHOLD = 0.60


def normalize_name(name: str) -> str:
    return " ".join(name.lower().replace(".", "").replace(",", "").split())


def name_similarity(a: str, b: str) -> float:
    return fuzz.token_sort_ratio(normalize_name(a), normalize_name(b)) / 100.0
