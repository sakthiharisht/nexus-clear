r"""PII redaction (SPEC.md sections 7.1, 11): masks SSN/TIN-shaped
patterns in text before it could leave the process to a model. M5
(Classify) and M6 (Extract) are the stages that actually send document
text to a model - this module exists now so both can call it on every
string before it reaches a prompt, per SPEC 7.1: "Redaction before any
model sees content."

Matches on structure, not on SSA area-number validity ranges. This
project's own synthetic W9 fixtures use 000-xx-xxxx TINs
(app/eval/generator/provider.py: "the SSA has stated the 000 area is
never issued, so 000-xx-xxxx can't collide with a real SSN") -
filtering out "invalid" area numbers would make the redactor miss
exactly the synthetic data it's tested against. Redaction is meant to
over-mask, not to validate that a number is a genuine identity number.

Three structural patterns, checked in this order so an already-masked
span can't be re-matched by a later, looser pattern:
1. SSN/ITIN with a separator: NNN-NN-NNNN or NNN NN NNNN (3-2-4).
2. EIN with a separator: NN-NNNNNNN or NN NNNNNNN (2-7).
3. Nine bare contiguous digits, no separator at all - covers an
   unseparated SSN/ITIN/EIN alike, since they're structurally
   identical once punctuation is stripped. This is also the shape of
   a US bank routing number, which this redactor can't distinguish
   from an SSN - over-redaction is the acceptable failure direction.
   `\b` on both sides keeps this from matching inside a longer
   alphanumeric token or a 10+ digit run (a phone number written as
   one block, for instance): there's no word boundary between two
   adjacent digits, so `\d{9}\b` cannot land on the first 9 digits of
   a 10-digit string.

No redaction map is built or returned. SPEC 7.1 says "keep the
redaction map out of logs" - the simplest way to guarantee that
absolutely is to never materialize one as a value a caller could
accidentally log in the first place.
"""

from __future__ import annotations

import re

SSN_MASK = "[REDACTED-SSN]"
EIN_MASK = "[REDACTED-EIN]"

_SSN_OR_ITIN_SEPARATED = re.compile(r"\b\d{3}[- ]\d{2}[- ]\d{4}\b")
_EIN_SEPARATED = re.compile(r"\b\d{2}[- ]\d{7}\b")
_NINE_DIGITS_BARE = re.compile(r"\b\d{9}\b")


def redact(text: str) -> str:
    """Masks every SSN/ITIN-shaped, EIN-shaped, and bare-9-digit
    substring in `text`."""
    text = _SSN_OR_ITIN_SEPARATED.sub(SSN_MASK, text)
    text = _EIN_SEPARATED.sub(EIN_MASK, text)
    text = _NINE_DIGITS_BARE.sub(SSN_MASK, text)
    return text


def contains_sensitive_pattern(text: str) -> bool:
    """True if `text` has anything `redact` would mask - for a caller
    that wants to flag/reject input rather than silently mask it."""
    return bool(
        _SSN_OR_ITIN_SEPARATED.search(text)
        or _EIN_SEPARATED.search(text)
        or _NINE_DIGITS_BARE.search(text)
    )
