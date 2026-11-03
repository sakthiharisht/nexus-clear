from app.core.redact import EIN_MASK, SSN_MASK, contains_sensitive_pattern, redact


def test_redacts_an_ssn_shaped_pattern_with_dashes() -> None:
    assert redact("SSN: 123-45-6789 on file") == f"SSN: {SSN_MASK} on file"


def test_redacts_an_ssn_shaped_pattern_with_spaces() -> None:
    assert redact("SSN: 123 45 6789 on file") == f"SSN: {SSN_MASK} on file"


def test_redacts_an_ssn_with_no_separator_at_all() -> None:
    assert redact("SSN: 123456789 on file") == f"SSN: {SSN_MASK} on file"


def test_redacts_the_synthetic_000_prefixed_tin() -> None:
    # app/eval/generator/provider.py's actual W9 fixture format:
    # f"000-{index:02d}-{(1000 + index):04d}" - "000" is an SSA area
    # number that's never issued, so this must still be masked even
    # though it could never be mistaken for a *valid* real SSN.
    assert redact("TIN: 000-02-1002  (synthetic, clearly-invalid format)") == (
        f"TIN: {SSN_MASK}  (synthetic, clearly-invalid format)"
    )


def test_redacts_an_ein_shaped_pattern_with_dash() -> None:
    assert redact("EIN 12-3456789") == f"EIN {EIN_MASK}"


def test_redacts_an_ein_shaped_pattern_with_space() -> None:
    assert redact("EIN 12 3456789") == f"EIN {EIN_MASK}"


def test_redacts_multiple_occurrences() -> None:
    text = "primary 123-45-6789, secondary 987-65-4321"
    assert redact(text) == f"primary {SSN_MASK}, secondary {SSN_MASK}"


def test_leaves_the_project_license_number_format_alone() -> None:
    # app/eval/generator/provider.py: f"LPC-{100000 + index}" - a
    # letter prefix, never SSN/EIN-shaped.
    text = "license LPC-100000 issued"
    assert redact(text) == text


# --- False positives the widened (separator-free) pattern must avoid ---


def test_does_not_redact_a_phone_number_dashed() -> None:
    assert redact("phone 555-123-4567") == "phone 555-123-4567"


def test_does_not_redact_a_phone_number_parenthesized() -> None:
    assert redact("phone (555) 123-4567") == "phone (555) 123-4567"


def test_does_not_redact_a_bare_10_digit_phone_number() -> None:
    # \b\d{9}\b can't land on the first 9 of a 10-digit run - there's
    # no word boundary between two adjacent digits.
    assert redact("call 5551234567 now") == "call 5551234567 now"


def test_does_not_redact_the_projects_policy_number_format() -> None:
    # app/eval/generator/provider.py: f"POL-{200000 + index}" - a
    # letter prefix, 6 digits, never 9.
    assert redact("policy POL-200000 covers this") == "policy POL-200000 covers this"


def test_does_not_redact_an_iso_date() -> None:
    assert redact("issued 2026-11-18") == "issued 2026-11-18"


def test_does_not_redact_a_bare_8_digit_date() -> None:
    assert redact("issued 20261118") == "issued 20261118"


def test_contains_sensitive_pattern_true_for_ssn_shaped_text() -> None:
    assert contains_sensitive_pattern("SSN 123-45-6789") is True


def test_contains_sensitive_pattern_true_for_an_unseparated_ssn() -> None:
    assert contains_sensitive_pattern("SSN 123456789") is True


def test_contains_sensitive_pattern_true_for_ein_shaped_text() -> None:
    assert contains_sensitive_pattern("EIN 12-3456789") is True


def test_contains_sensitive_pattern_false_for_clean_text() -> None:
    assert contains_sensitive_pattern("holder_name: Christopher Lee") is False


def test_contains_sensitive_pattern_false_for_a_phone_number() -> None:
    assert contains_sensitive_pattern("555-123-4567") is False


def test_contains_sensitive_pattern_false_for_a_date() -> None:
    assert contains_sensitive_pattern("2026-11-18") is False


def test_redact_is_idempotent() -> None:
    once = redact("SSN 123-45-6789")
    assert redact(once) == once
