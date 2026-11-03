import pytest

from app.eval.generator.npi import invalid_check_digit_npi, synthetic_npi
from app.rules.kinds import npi_luhn_80840_valid


def test_synthetic_npi_passes_the_real_luhn_check() -> None:
    for sequence in range(10):
        assert npi_luhn_80840_valid(synthetic_npi(sequence))


def test_synthetic_npis_are_distinct() -> None:
    npis = [synthetic_npi(i) for i in range(10)]
    assert len(set(npis)) == len(npis)


def test_invalid_check_digit_npi_fails_the_real_luhn_check() -> None:
    assert not npi_luhn_80840_valid(invalid_check_digit_npi(0))


def test_invalid_check_digit_npi_is_still_well_formed() -> None:
    npi = invalid_check_digit_npi(0)
    assert len(npi) == 10
    assert npi.isdigit()


def test_sequence_out_of_range_is_rejected() -> None:
    with pytest.raises(ValueError, match="0-99"):
        synthetic_npi(100)
    with pytest.raises(ValueError, match="0-99"):
        synthetic_npi(-1)
