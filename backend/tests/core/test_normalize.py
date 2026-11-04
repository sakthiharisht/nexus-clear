from __future__ import annotations

from datetime import date

from app.core.normalize import normalize_date, normalize_money, normalize_name


def test_normalize_date_parses_iso() -> None:
    assert normalize_date("2024-03-15") == date(2024, 3, 15)


def test_normalize_date_parses_us_slash_format() -> None:
    assert normalize_date("03/15/2024") == date(2024, 3, 15)


def test_normalize_date_parses_long_month_name() -> None:
    assert normalize_date("March 15, 2024") == date(2024, 3, 15)


def test_normalize_date_returns_none_for_unparseable_text() -> None:
    assert normalize_date("sometime last spring") is None


def test_normalize_money_strips_dollar_sign_and_commas() -> None:
    assert normalize_money("$1,000,000.00") == 1_000_000.0


def test_normalize_money_handles_bare_number() -> None:
    assert normalize_money("300000") == 300000.0


def test_normalize_money_returns_none_for_non_numeric_text() -> None:
    assert normalize_money("one million dollars") is None


def test_normalize_name_collapses_whitespace() -> None:
    assert normalize_name("Jane   \t Doe") == "Jane Doe"


def test_normalize_name_preserves_case() -> None:
    assert normalize_name("Jane Doe") == "Jane Doe"


def test_normalize_name_returns_none_for_empty_string() -> None:
    assert normalize_name("   ") is None
