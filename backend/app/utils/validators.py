"""Validation helpers: Aadhaar (Verhoeff), PAN, Indian phone numbers, file magic bytes."""
import re

# Verhoeff tables
_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]
_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def verhoeff_validate(number: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def verhoeff_check_digit(number: str) -> str:
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return str(_INV[c])


PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


def normalize_id_number(id_type: str, value: str) -> str:
    value = (value or "").strip()
    if id_type == "AADHAAR":
        return re.sub(r"[\s-]", "", value)
    return value.upper().replace(" ", "")


def validate_aadhaar(value: str) -> str | None:
    """Return an error message, or None when valid."""
    if not re.fullmatch(r"\d{12}", value):
        return "Aadhaar number must be exactly 12 digits"
    if value[0] in "01":
        return "Aadhaar number cannot start with 0 or 1"
    if not verhoeff_validate(value):
        return "Aadhaar number is invalid (checksum failed)"
    return None


def validate_pan(value: str) -> str | None:
    if not PAN_RE.fullmatch(value):
        return "PAN must look like ABCDE1234F (5 letters, 4 digits, 1 letter)"
    return None


def validate_id(id_type: str, value: str) -> str | None:
    if id_type == "AADHAAR":
        return validate_aadhaar(value)
    if id_type == "PAN":
        return validate_pan(value)
    return "ID type must be AADHAAR or PAN"


def mask_id(id_type: str | None, last4: str | None) -> str:
    if not last4:
        return "—"
    if id_type == "PAN":
        return f"XXXXXX{last4}"
    return f"XXXX-XXXX-{last4}"


def normalize_phone(raw: str) -> str | None:
    """Normalize to E.164. Bare 10-digit numbers are treated as Indian mobiles."""
    if not raw:
        return None
    raw = raw.strip()
    plus = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)
    if not plus:
        if len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if len(digits) == 10:
            if digits[0] not in "6789":
                return None
            return "+91" + digits
        if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
            return "+" + digits
        return None
    if digits.startswith("91") and (len(digits) != 12 or digits[2] not in "6789"):
        return None
    if not 8 <= len(digits) <= 15:
        return None
    return "+" + digits


# ---------- file type sniffing ----------
ALLOWED_DOC_TYPES = {"image/jpeg": "jpg", "image/png": "png", "application/pdf": "pdf"}
ALLOWED_PHOTO_TYPES = {"image/jpeg": "jpg", "image/png": "png"}


def sniff_mime(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None
