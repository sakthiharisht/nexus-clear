from app.core.redact import EIN_MASK, SSN_MASK, contains_sensitive_pattern, redact


def test_redacts_an_ssn_shaped_pattern() -> None:
    assert redact("SSN: 123-45-6789 on file") == f"SSN: {SSN_MASK} on file"


def test_redacts_the_synthetic_000_prefixed_tin() -> None:
    # app/eval/generator/provider.py's actual W9 fixture format:
    # f"000-{index:02d}-{(1000 + index):04d}" - "000" is an SSA area
    # number that's never issued, so this must still be masked even
    # though it could never be mistaken for a *valid* real SSN.
    assert redact("TIN: 000-02-1002  (synthetic, clearly-invalid format)") == (
        f"TIN: {SSN_MASK}  (synthetic, clearly-invalid format)"
    )


def test_redacts_an_ein_shaped_pattern() -> None:
    assert redact("EIN 12-3456789") == f"EIN {EIN_MASK}"


def test_redacts_multiple_occurrences() -> None:
    text = "primary 123-45-6789, secondary 987-65-4321"
    assert redact(text) == f"primary {SSN_MASK}, secondary {SSN_MASK}"


def test_leaves_non_matching_text_alone() -> None:
    text = "license LPC-100000 issued 2020-11-18, phone 555-123-4567"
    assert redact(text) == text


def test_does_not_match_a_bare_9_digit_run_without_the_ssn_grouping() -> None:
    # Deliberately conservative: a contiguous digit run (e.g. part of a
    # longer account/ID number) isn't SSN-shaped on its own.
    assert redact("account 123456789") == "account 123456789"


def test_contains_sensitive_pattern_true_for_ssn_shaped_text() -> None:
    assert contains_sensitive_pattern("SSN 123-45-6789") is True


def test_contains_sensitive_pattern_true_for_ein_shaped_text() -> None:
    assert contains_sensitive_pattern("EIN 12-3456789") is True


def test_contains_sensitive_pattern_false_for_clean_text() -> None:
    assert contains_sensitive_pattern("holder_name: Christopher Lee") is False


def test_redact_is_idempotent() -> None:
    once = redact("SSN 123-45-6789")
    assert redact(once) == once
