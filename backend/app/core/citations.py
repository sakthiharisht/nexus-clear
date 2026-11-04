"""Deterministic citation verification (SPEC.md section 7.3:
"Deterministic verification in code: for text-layer PDFs, a quote must
be a substring of the document text or the field is demoted to
unknown. For images (no text layer) mark quote_verified=false and
surface it.") This is the code half of CLAUDE.md invariant 2 - the
model's claimed quote is never trusted on its own; it only becomes
evidence once code has actually found it in the real document text.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date

from app.backends.extract_types import ExtractedField, VerifiedField
from app.core.normalize import normalize_date, normalize_money, normalize_name

_WHITESPACE = re.compile(r"\s+")

_Normalizer = Callable[[str], object | None]


def _collapse_whitespace(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def quote_found_in_text(quote: str, document_text: str) -> bool:
    """Substring check, tolerant only of whitespace differences (a PDF
    text layer often wraps a quote across a line break that the model
    reads as a single space) - never tolerant of character
    substitution, so this can't be talked into matching a near-quote.
    """
    return _collapse_whitespace(quote) in _collapse_whitespace(document_text)


def _as_str(value: object) -> str:
    return value.isoformat() if isinstance(value, date) else str(value)


def verify_field(
    field: ExtractedField,
    document_text: str | None,
    *,
    normalize: _Normalizer = normalize_name,
) -> VerifiedField:
    """`document_text` is None for a document with no text layer (an
    image) - quote_verified stays False and status is decided on the
    model's say-so alone, per SPEC 7.3's explicit split between PDFs
    and images. `document_text` == "" (a text-layer doc that happens to
    have no page-1 text) is treated the same as a real text layer: a
    quote claimed against it will correctly fail verification rather
    than being waved through as unverifiable.
    """
    if field.value is None or field.quote is None:
        return VerifiedField(status="unknown")

    if document_text is not None and not quote_found_in_text(field.quote, document_text):
        return VerifiedField(status="unknown")

    normalized_value = normalize(field.value)
    if normalized_value is None:
        return VerifiedField(status="unknown")

    return VerifiedField(
        status="known",
        value=_as_str(normalized_value),
        confidence=field.confidence,
        page=field.page,
        quote=field.quote,
        quote_verified=document_text is not None,
    )


def verify_date_field(field: ExtractedField, document_text: str | None) -> VerifiedField:
    return verify_field(field, document_text, normalize=normalize_date)


def verify_money_field(field: ExtractedField, document_text: str | None) -> VerifiedField:
    return verify_field(field, document_text, normalize=normalize_money)


def verify_name_field(field: ExtractedField, document_text: str | None) -> VerifiedField:
    return verify_field(field, document_text, normalize=normalize_name)


def verify_text_field(field: ExtractedField, document_text: str | None) -> VerifiedField:
    """For fields with no further normalization (license_number,
    license_type, status, issuing_board, carrier, policy_number) -
    still goes through normalize_name's whitespace cleanup, since
    that's the only generic "clean up OCR artifacts" normalizer, not
    because these are names."""
    return verify_field(field, document_text, normalize=normalize_name)


def verify_bool_field(field: ExtractedField, document_text: str | None) -> VerifiedField:
    """tin_present/signed (w9) - the model reports "yes"/"no"/"true" as
    a string; normalized to "true"/"false" in code, never guessed from
    absence of a quote."""

    def _normalize_bool(raw: str) -> str | None:
        lowered = raw.strip().lower()
        if lowered in {"true", "yes", "y"}:
            return "true"
        if lowered in {"false", "no", "n"}:
            return "false"
        return None

    return verify_field(field, document_text, normalize=_normalize_bool)
