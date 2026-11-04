from __future__ import annotations

from app.backends.extract_types import ExtractedField
from app.core.citations import (
    quote_found_in_text,
    verify_bool_field,
    verify_date_field,
    verify_money_field,
    verify_name_field,
    verify_text_field,
)

DOC_TEXT = "Name: Jane Doe\n\nLicense Number: LPC-12345\nExpiration Date: 2024-03-15\n"


def test_quote_found_in_text_tolerates_line_wrap_whitespace() -> None:
    assert quote_found_in_text("License Number:\nLPC-12345", DOC_TEXT) is True


def test_quote_found_in_text_rejects_a_near_quote() -> None:
    assert quote_found_in_text("License Number: LPC-99999", DOC_TEXT) is False


def test_verify_field_with_no_quote_is_unknown() -> None:
    field = ExtractedField(value="Jane Doe", page=1, quote=None)
    result = verify_name_field(field, DOC_TEXT)
    assert result.status == "unknown"
    assert result.value is None


def test_verify_field_with_no_value_is_unknown() -> None:
    field = ExtractedField(value=None, page=1, quote="Name: Jane Doe")
    result = verify_name_field(field, DOC_TEXT)
    assert result.status == "unknown"


def test_verify_field_demotes_to_unknown_when_quote_not_in_text() -> None:
    field = ExtractedField(value="Jane Doe", page=1, quote="Name: John Smith")
    result = verify_name_field(field, DOC_TEXT)
    assert result.status == "unknown"
    assert result.quote_verified is False


def test_verify_field_known_and_verified_for_a_real_text_layer_match() -> None:
    field = ExtractedField(value="Jane Doe", page=1, quote="Name: Jane Doe")
    result = verify_name_field(field, DOC_TEXT)
    assert result.status == "known"
    assert result.value == "Jane Doe"
    assert result.quote_verified is True


def test_verify_date_field_normalizes_in_code() -> None:
    field = ExtractedField(value="March 15, 2024", page=1, quote="Expiration Date: 2024-03-15")
    result = verify_date_field(field, DOC_TEXT)
    assert result.status == "known"
    assert result.value == "2024-03-15"


def test_verify_date_field_unknown_when_value_unparseable() -> None:
    field = ExtractedField(
        value="sometime last spring", page=1, quote="Expiration Date: 2024-03-15"
    )
    result = verify_date_field(field, DOC_TEXT)
    assert result.status == "unknown"


def test_verify_money_field_normalizes_currency_string() -> None:
    doc_text = "Aggregate: $1,000,000.00"
    field = ExtractedField(value="$1,000,000.00", page=1, quote="Aggregate: $1,000,000.00")
    result = verify_money_field(field, doc_text)
    assert result.status == "known"
    assert result.value == "1000000.0"


def test_verify_text_field_an_image_has_no_text_layer_marks_unverified_but_known() -> None:
    """SPEC 7.3: images get quote_verified=False, surfaced, but are not
    auto-demoted to unknown the way a failed text-layer check is."""
    field = ExtractedField(value="LPC-12345", page=1, quote="License Number: LPC-12345")
    result = verify_text_field(field, None)
    assert result.status == "known"
    assert result.quote_verified is False


def test_verify_text_field_empty_text_layer_still_fails_verification() -> None:
    """document_text == "" is a real (if empty) text layer, not the
    "no text layer at all" case - a claimed quote against it must still
    fail verification rather than being waved through as unverifiable."""
    field = ExtractedField(value="LPC-12345", page=1, quote="License Number: LPC-12345")
    result = verify_text_field(field, "")
    assert result.status == "unknown"


def test_verify_bool_field_normalizes_yes_no_to_true_false() -> None:
    doc_text = "TIN present: yes"
    field = ExtractedField(value="yes", page=1, quote="TIN present: yes")
    result = verify_bool_field(field, doc_text)
    assert result.status == "known"
    assert result.value == "true"
