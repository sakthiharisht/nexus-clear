"""Date/money/name normalization in code (SPEC.md section 7.3: "the
model returns raw strings plus quotes" - these functions turn a raw
string into the normalized form CaseFacts expects, never the other way
around. Every function returns None on anything it can't confidently
parse rather than guessing (CLAUDE.md invariant 2) - a caller is
expected to demote the field to "unknown" when that happens.
"""

from __future__ import annotations

import re
from datetime import date, datetime

_DATE_FORMATS = (
    "%Y-%m-%d",  # ISO - what every synthetic fixture in this project renders
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%B %d, %Y",  # "March 15, 2024"
    "%B %d %Y",
    "%b %d, %Y",  # "Mar 15, 2024"
    "%b %d %Y",
)


def normalize_date(raw: str) -> date | None:
    text = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


_MONEY_CLEAN = re.compile(r"[$,\s]")
_MONEY_SHAPE = re.compile(r"^-?\d+(\.\d+)?$")


def normalize_money(raw: str) -> float | None:
    cleaned = _MONEY_CLEAN.sub("", raw.strip())
    if not cleaned or not _MONEY_SHAPE.match(cleaned):
        return None
    return float(cleaned)


def normalize_name(raw: str) -> str | None:
    """Whitespace/punctuation cleanup only - preserves case. Downstream
    name comparisons (app/eval/baseline_reconcile.py's `_normalize_name`
    + rapidfuzz) do their own case-folding; this is just cleaning up
    OCR/vision artifacts (doubled spaces, stray tabs) before a name
    reaches CaseFacts, not fuzzy-matching it."""
    cleaned = " ".join(raw.split())
    return cleaned or None
