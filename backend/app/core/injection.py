"""Deterministic prompt-injection detection (SPEC.md section 7.3: "Flag
instruction-like text (R-SEC-001) and continue"; CLAUDE.md invariant 1:
no model output may directly set a finding's status for a presence
rule). R-SEC-001 (app/rules/kinds.py's `evaluate_injection_flag`) reads
`DocumentFact.contains_injection_text` - this module is the one place
that boolean gets computed, by regex over the document's own text,
never by asking a model whether it noticed anything. A model's
self-report would let it indirectly decide a presence-rule Finding,
exactly what invariant 1 forbids.

Shared between app/eval/baseline_extraction.py (M3, regex-only) and
the M6 Extract stage - both read real document text and must agree on
what counts as injection-like, so there's one implementation instead
of two that can drift.
"""

from __future__ import annotations

import re

_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore all (previous|prior) instructions",
        r"system instruction",
        r"disregard (all |the )?(previous|prior) instructions",
    ]
]


def contains_injection_text(text: str) -> bool:
    return any(pattern.search(text) for pattern in _INJECTION_PATTERNS)
