from app.utils.formatting import fmt_date, inr
from app.utils.validators import (
    mask_id,
    normalize_phone,
    sniff_mime,
    validate_aadhaar,
    validate_pan,
    verhoeff_check_digit,
    verhoeff_validate,
)
from tests.conftest import valid_aadhaar


def test_verhoeff_known_vectors():
    # Classic Verhoeff example: 236 -> check digit 3
    assert verhoeff_check_digit("236") == "3"
    assert verhoeff_validate("2363")
    assert not verhoeff_validate("2364")


def test_aadhaar_valid():
    num = valid_aadhaar()
    assert validate_aadhaar(num) is None


def test_aadhaar_bad_checksum():
    num = valid_aadhaar()
    bad = num[:-1] + str((int(num[-1]) + 1) % 10)
    assert "checksum" in validate_aadhaar(bad)


def test_aadhaar_length_and_prefix():
    assert "12 digits" in validate_aadhaar("12345")
    assert "12 digits" in validate_aadhaar("23456789012A")
    for p in ("0", "1"):
        prefix = p + "3456789012"
        assert "cannot start" in validate_aadhaar(prefix + verhoeff_check_digit(prefix))


def test_pan():
    assert validate_pan("ABCDE1234F") is None
    for bad in ("abcde1234f", "ABCD1234F", "ABCDE12345", "ABCDE1234", "1BCDE1234F", "ABCDE1234FF"):
        assert validate_pan(bad) is not None, bad


def test_phone_normalization():
    assert normalize_phone("9876543210") == "+919876543210"
    assert normalize_phone("+91 98765 43210") == "+919876543210"
    assert normalize_phone("919876543210") == "+919876543210"
    assert normalize_phone("09876543210") == "+919876543210"
    assert normalize_phone("12345") is None
    assert normalize_phone("5876543210") is None


def test_masking_and_formats():
    assert mask_id("AADHAAR", "4521") == "XXXX-XXXX-4521"
    assert inr(150000) == "₹1,50,000"
    assert inr(15750) == "₹15,750"
    assert inr(12345678) == "₹1,23,45,678"
    assert inr(999) == "₹999"
    from datetime import date
    assert fmt_date(date(2026, 11, 5)) == "05-Nov-2026"


def test_magic_bytes():
    assert sniff_mime(b"\xff\xd8\xff\xe0abc") == "image/jpeg"
    assert sniff_mime(b"\x89PNG\r\n\x1a\nxx") == "image/png"
    assert sniff_mime(b"%PDF-1.7") == "application/pdf"
    assert sniff_mime(b"MZ\x90\x00 fake.pdf") is None
