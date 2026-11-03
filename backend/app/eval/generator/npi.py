"""Deterministic synthetic NPI construction for eval fixtures.

Reuses app.rules.kinds.npi_check_digit — the same CMS Luhn/80840
implementation the rules engine validates against — so a "valid" synthetic
NPI here is guaranteed to also pass R-ID-001, and an "invalid" one is
guaranteed to fail it, with no risk of the two algorithms drifting apart.
"""

from app.rules.kinds import npi_check_digit

# CMS: an NPI's first digit is 1 (individual) or 2 (organizational). Starting
# every synthetic base at "1000000" + a two-digit sequence number keeps
# these obviously synthetic/sequential — nothing resembling a real issued
# NPI range.
_BASE_PREFIX = "1000000"


def synthetic_npi(sequence: int) -> str:
    """A well-formed 10-digit NPI with a valid Luhn/80840 check digit.

    `sequence` must be 0-99 to stay within the fixed-width synthetic base.
    """
    if not 0 <= sequence <= 99:
        raise ValueError("sequence must be 0-99 for this fixed-width synthetic base")
    base9 = f"{_BASE_PREFIX}{sequence:02d}"
    return base9 + str(npi_check_digit(base9))


def invalid_check_digit_npi(sequence: int) -> str:
    """A well-formed-*looking* 10-digit NPI (right length, all digits) with
    a deliberately wrong check digit — for D15."""
    valid = synthetic_npi(sequence)
    wrong_digit = (int(valid[-1]) + 1) % 10
    return valid[:-1] + str(wrong_digit)
