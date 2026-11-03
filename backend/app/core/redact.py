"""PII redaction (SPEC.md sections 7.1, 11): masks SSN/TIN-shaped
patterns in text before it could leave the process to a model. M5
(Classify) and M6 (Extract) are the stages that actually send document
text to a model - this module exists now so both can call it on every
string before it reaches a prompt, per SPEC 7.1: "Redaction before any
model sees content."

Matches on structure (NNN-NN-NNNN - the grouping SSNs and ITINs share;
NN-NNNNNNN for EINs), not on SSA area-number validity ranges. This
project's own synthetic W9 fixtures use 000-xx-xxxx TINs
(app/eval/generator/provider.py: "the SSA has stated the 000 area is
never issued, so 000-xx-xxxx can't collide with a real SSN") -
filtering out "invalid" area numbers would make the redactor miss
exactly the synthetic data it's tested against. Redaction is meant to
over-mask, not to validate that a number is a genuine identity number.

No redaction map is built or returned. SPEC 7.1 says "keep the
redaction map out of logs" - the simplest way to guarantee that
absolutely is to never materialize one as a value a caller could
accidentally log in the first place.
"""

from __future__ import annotations

import re

SSN_MASK = "[REDACTED-SSN]"
EIN_MASK = "[REDACTED-EIN]"

_SSN_OR_ITIN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_EIN = re.compile(r"\b\d{2}-\d{7}\b")


def redact(text: str) -> str:
    """Masks every SSN/ITIN-shaped and EIN-shaped substring in `text`."""
    text = _SSN_OR_ITIN.sub(SSN_MASK, text)
    text = _EIN.sub(EIN_MASK, text)
    return text


def contains_sensitive_pattern(text: str) -> bool:
    """True if `text` has anything `redact` would mask - for a caller
    that wants to flag/reject input rather than silently mask it."""
    return bool(_SSN_OR_ITIN.search(text) or _EIN.search(text))
