"""Unit tests for deterministic validators (synthetic values only)."""

from datetime import date

import pytest

from app.parsing.mrz import check_digit
from app.validation import validators as v

VALID_CNP = "1800101400016"  # synthetic, checksum-valid


def make_cnp(first12: str) -> str:
    return first12 + str(v.cnp_check_digit(first12))


# --- CNP ----------------------------------------------------------------------


def test_cnp_valid():
    assert v.validate_cnp(VALID_CNP).valid
    assert v.validate_cnp(make_cnp("285031512001")).valid
    assert v.validate_cnp(make_cnp("502123146001")).valid  # born 2002


def test_cnp_checksum_invalid_detected():
    bad = VALID_CNP[:12] + str((int(VALID_CNP[12]) + 1) % 10)
    res = v.validate_cnp(bad)
    assert not res.valid and res.code == "CNP_CHECKSUM_INVALID"


def test_cnp_checksum_rest_10_maps_to_1():
    # find a synthetic prefix whose weighted sum % 11 == 10
    for serial in range(1, 999):
        prefix = f"180010140{serial:03d}"
        if sum(int(d) * w for d, w in zip(prefix, v.CNP_WEIGHTS)) % 11 == 10:
            assert v.cnp_check_digit(prefix) == 1
            assert v.validate_cnp(prefix + "1").valid
            return
    pytest.fail("no prefix with rest 10 found")


@pytest.mark.parametrize(
    "value,code",
    [
        ("180010140001", "CNP_INVALID_FORMAT"),  # 12 digits
        ("18001014000166", "CNP_INVALID_FORMAT"),  # 14 digits
        ("18001014000A6", "CNP_INVALID_FORMAT"),
        ("0800101400016", "CNP_INVALID_FORMAT"),
        (make_cnp("180023040001"), "CNP_INVALID_DATE"),  # 30 Feb
        (make_cnp("180010199001"), "CNP_INVALID_COUNTY"),
        (make_cnp("180010140000")[:12] + "0", "CNP_INVALID_FORMAT"),  # serial 000
        ("", "MISSING_VALUE"),
        (None, "MISSING_VALUE"),
    ],
)
def test_cnp_invalid(value, code):
    res = v.validate_cnp(value)
    assert not res.valid
    assert res.code == code


def test_cnp_birth_date_and_normalize():
    assert v.cnp_birth_date(VALID_CNP) == date(1980, 1, 1)
    assert v.cnp_birth_date(make_cnp("502123146001")) == date(2002, 12, 31)
    assert v.normalize_cnp(" 1800101 400016 ") == VALID_CNP


# --- VIN ----------------------------------------------------------------------


def test_vin_valid():
    assert v.validate_vin("UU1TEST9X00000001").valid
    assert v.validate_vin("UU1AAAAAAAAAAAAAA").valid  # example from the contract


@pytest.mark.parametrize("length", [0, 1, 10, 16, 18, 20, 25])
def test_vin_wrong_length_always_flagged(length):
    vin = ("UU1TEST9X00000001" * 2)[:length]
    res = v.validate_vin(vin or None)
    assert not res.valid
    assert res.code in ("VIN_INVALID_LENGTH", "MISSING_VALUE")


@pytest.mark.parametrize("vin", ["UU1TEST9XO0000001", "UU1TEST9XQ0000001", "UU1TEST9XI0000001"])
def test_vin_forbidden_letters_flagged_not_autocorrected(vin):
    res = v.validate_vin(vin)
    assert not res.valid and res.code == "VIN_INVALID_CHARS"
    assert res.suggestion is not None and res.suggestion != vin
    assert v.validate_vin(res.suggestion).valid
    # the validator never mutates the value: normalisation keeps the letters
    assert v.normalize_vin(vin) == vin


def test_vin_special_chars_and_normalization():
    assert v.validate_vin("UU1TEST9X0000000#").code == "VIN_INVALID_CHARS"
    assert v.normalize_vin(" uu1-test9x 00000001 ") == "UU1TEST9X00000001"


# --- registration number -------------------------------------------------------


@pytest.mark.parametrize("plate", ["B99XYZ", "B123DMO", "CJ99TST", "IF01ABC"])
def test_plate_valid(plate):
    assert v.validate_plate(plate).valid


def test_plate_normalization():
    assert v.normalize_plate("cj 99-tst") == "CJ99TST"


@pytest.mark.parametrize(
    "plate,code",
    [
        ("XX99ABC", "PLATE_UNKNOWN_COUNTY"),
        ("B123456", "PLATE_UNUSUAL_FORMAT"),  # temporary plates: accepted with warning
        ("B99QAB", "PLATE_UNUSUAL_FORMAT"),
        ("B99ABC!", "PLATE_INVALID_CHARS"),
        (None, "MISSING_VALUE"),
    ],
)
def test_plate_flags(plate, code):
    res = v.validate_plate(plate)
    assert not res.valid and res.code == code


# --- dates, numbers, fuel, names ----------------------------------------------


def test_date_normalization_and_validation():
    assert v.normalize_date("10.03.2020") == "2020-03-10"
    assert v.normalize_date("2020-03-10") == "2020-03-10"
    assert v.normalize_date("10.03.20") == "10.03.20"  # ambiguous year kept, not guessed
    assert not v.validate_iso_date("10.03.20").valid
    assert not v.validate_iso_date("2020-02-30").valid
    assert v.validate_iso_date("2099-01-01", not_future=True).code == "DATE_IN_FUTURE"
    assert v.validate_iso_date("2020-03-10", not_future=True).valid


def test_ranges():
    assert v.validate_range(999, 50, 10000, "Cilindreea", "cm³").valid
    assert v.validate_range(0, 50, 10000, "Cilindreea", "cm³").code == "NUMBER_NOT_POSITIVE"
    assert v.validate_range(25000, 50, 10000, "Cilindreea", "cm³").code == "NUMBER_IMPLAUSIBLE"
    assert v.parse_positive_int("1 598 cm3") == 1598
    assert v.parse_positive_int("66 kW") == 66
    assert v.parse_positive_int("n/a") is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("BENZINA", "PETROL"), ("Benzină", "PETROL"), ("MOTORINA", "DIESEL"), ("ELECTRIC", "ELECTRIC"),
        ("BENZINA/ELECTRIC", "HYBRID_PETROL"), ("HIBRID MOTORINA", "HYBRID_DIESEL"), ("BENZINA+GPL", "LPG"),
        ("ABC", "OTHER"), (None, None), ("", None),
    ],
)
def test_fuel_normalization(raw, expected):
    assert v.normalize_fuel(raw) == expected


def test_names():
    assert v.normalize_name(" maria - elena ") == "MARIA-ELENA"
    assert v.validate_name("ȘTEFĂNESCU", "Nume").valid
    assert v.validate_name("I0NESCU", "Nume").code == "NAME_CONTAINS_DIGITS"
    assert v.names_equivalent("POPESCU MARIA-ELENA", "MARIA ELENA POPESCU")
    assert v.names_equivalent("ȘTEFAN", "STEFAN")
    assert not v.names_equivalent("IONESCU ALEX", "SC EXEMPLU FLOTA SRL")


def test_mrz_check_digit_icao_example():
    # ICAO 9303 specimen values
    assert check_digit("L898902C3") == 6
    assert check_digit("740812") == 2
    assert check_digit("120415") == 9
