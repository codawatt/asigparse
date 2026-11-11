"""Deterministic validators and normalizers for Romanian document fields.

All functions are pure: they never guess or "repair" a value silently. When a
value looks like a common OCR confusion (e.g. letter O inside a VIN) the
validator returns a *suggestion* that the operator has to accept explicitly.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def strip_diacritics(text: str) -> str:
    """Return ASCII-folded text (Ș -> S, ă -> a, ...)."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


# OCR engines and older fonts emit the cedilla forms; Romanian orthography
# uses comma-below (Ș, Ț). Normalising avoids false "corrections".
_RO_COMMA = str.maketrans({"Ş": "Ș", "ş": "ș", "Ţ": "Ț", "ţ": "ț"})


def fix_ro_diacritics(text: str | None) -> str | None:
    return text.translate(_RO_COMMA) if text else text


def clean_spaces(text: str | None) -> str | None:
    if text is None:
        return None
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed or None


@dataclass
class ValidationResult:
    valid: bool
    code: str | None = None
    message: str | None = None
    suggestion: str | None = None
    details: dict = field(default_factory=dict)


OK = ValidationResult(valid=True)

# ---------------------------------------------------------------------------
# CNP (Cod Numeric Personal)
# ---------------------------------------------------------------------------

CNP_WEIGHTS = (2, 7, 9, 1, 4, 6, 3, 5, 8, 2, 7, 9)

# County codes valid in a CNP (01-46, 47/48 historical Bucharest sectors 7/8,
# 51 Calarasi, 52 Giurgiu, 70 residents registered regardless of county,
# 80-83 foreign citizens series introduced in 2024).
CNP_COUNTY_CODES = {f"{i:02d}" for i in range(1, 47)} | {"47", "48", "51", "52", "70", "80", "81", "82", "83"}


def cnp_check_digit(first12: str) -> int:
    total = sum(int(d) * w for d, w in zip(first12, CNP_WEIGHTS))
    rest = total % 11
    return 1 if rest == 10 else rest


def cnp_birth_date(cnp: str) -> date | None:
    """Return the birth date encoded in a structurally valid CNP, else None."""
    if not re.fullmatch(r"\d{13}", cnp):
        return None
    s = int(cnp[0])
    century = {1: 1900, 2: 1900, 3: 1800, 4: 1800, 5: 2000, 6: 2000}.get(s)
    if century is None:
        # 7/8 residents, 9 foreigners: century is not encoded unambiguously
        return None
    try:
        return date(century + int(cnp[1:3]), int(cnp[3:5]), int(cnp[5:7]))
    except ValueError:
        return None


def normalize_cnp(value: str | None) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"[\s.\-]", "", value)
    return digits or None


def validate_cnp(cnp: str | None) -> ValidationResult:
    if not cnp:
        return ValidationResult(False, "MISSING_VALUE", "CNP lipsă.")
    if not re.fullmatch(r"\d{13}", cnp):
        return ValidationResult(False, "CNP_INVALID_FORMAT", "CNP trebuie să aibă exact 13 cifre.")
    if cnp[0] == "0":
        return ValidationResult(False, "CNP_INVALID_FORMAT", "Prima cifră a CNP (sex/secol) nu poate fi 0.")
    s = int(cnp[0])
    if s in (1, 2, 3, 4, 5, 6):
        if cnp_birth_date(cnp) is None:
            return ValidationResult(False, "CNP_INVALID_DATE", "Data nașterii codificată în CNP nu este o dată validă.")
    else:
        # 7, 8, 9: only month/day can be checked
        try:
            date(2000, int(cnp[3:5]), int(cnp[5:7]))
        except ValueError:
            return ValidationResult(False, "CNP_INVALID_DATE", "Data nașterii codificată în CNP nu este o dată validă.")
    if cnp[7:9] not in CNP_COUNTY_CODES:
        return ValidationResult(False, "CNP_INVALID_COUNTY", f"Codul de județ {cnp[7:9]} din CNP nu este valid.")
    if cnp[9:12] == "000":
        return ValidationResult(False, "CNP_INVALID_FORMAT", "Numărul de ordine din CNP nu poate fi 000.")
    expected = cnp_check_digit(cnp[:12])
    if int(cnp[12]) != expected:
        return ValidationResult(
            False,
            "CNP_CHECKSUM_INVALID",
            "Cifra de control a CNP nu corespunde. Verificați fiecare cifră față de document.",
        )
    return OK


# ---------------------------------------------------------------------------
# VIN
# ---------------------------------------------------------------------------

VIN_ALLOWED = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
VIN_OCR_FIXES = {"O": "0", "Q": "0", "I": "1"}


def normalize_vin(value: str | None) -> str | None:
    if value is None:
        return None
    v = re.sub(r"[\s\-.]", "", value).upper()
    return v or None


def validate_vin(vin: str | None) -> ValidationResult:
    if not vin:
        return ValidationResult(False, "MISSING_VALUE", "VIN lipsă.")
    if len(vin) != 17:
        return ValidationResult(
            False, "VIN_INVALID_LENGTH", f"VIN trebuie să aibă exact 17 caractere (are {len(vin)})."
        )
    if not re.fullmatch(r"[A-Z0-9]{17}", vin):
        return ValidationResult(False, "VIN_INVALID_CHARS", "VIN poate conține doar litere A-Z și cifre.")
    bad = sorted({c for c in vin if c in "IOQ"})
    if bad:
        suggestion = "".join(VIN_OCR_FIXES.get(c, c) for c in vin)
        return ValidationResult(
            False,
            "VIN_INVALID_CHARS",
            f"VIN conține caractere nepermise ({', '.join(bad)}); probabil confuzie OCR. "
            "Nu s-a corectat automat.",
            suggestion=suggestion if VIN_ALLOWED.match(suggestion) else None,
        )
    return OK


# ---------------------------------------------------------------------------
# Registration number (număr de înmatriculare)
# ---------------------------------------------------------------------------

COUNTY_PLATE_CODES = {
    "AB", "AR", "AG", "BC", "BH", "BN", "BT", "BV", "BR", "BZ", "CS", "CL", "CJ", "CT", "CV",
    "DB", "DJ", "GL", "GR", "GJ", "HR", "HD", "IL", "IS", "IF", "MM", "MH", "MS", "NT", "OT",
    "PH", "SM", "SJ", "SB", "SV", "TR", "TM", "TL", "VS", "VL", "VN",
}
PLATE_STANDARD = re.compile(r"^(?:B(?P<b>\d{2,3})|(?P<county>[A-Z]{2})(?P<c>\d{2}))(?P<letters>[A-Z]{3})$")
PLATE_TEMPORARY = re.compile(r"^(?:B|[A-Z]{2})\d{3,6}$")  # provisional / long-term red plates
PLATE_SPECIAL = re.compile(r"^(?:CD|TC|CO|MAI|A|FA|ALA)\d{3,6}$")


def normalize_plate(value: str | None) -> str | None:
    if value is None:
        return None
    v = re.sub(r"[\s\-.·]", "", value).upper()
    v = strip_diacritics(v)
    return v or None


def validate_plate(plate: str | None) -> ValidationResult:
    if not plate:
        return ValidationResult(False, "MISSING_VALUE", "Număr de înmatriculare lipsă.")
    if not re.fullmatch(r"[A-Z0-9]{4,10}", plate):
        return ValidationResult(False, "PLATE_INVALID_CHARS", "Numărul de înmatriculare conține caractere neașteptate.")
    m = PLATE_STANDARD.match(plate)
    if m:
        if m.group("b") and len(m.group("b")) == 3 and m.group("b").startswith("0"):
            return ValidationResult(False, "PLATE_UNUSUAL_FORMAT", "Format neobișnuit pentru București.")
        county = m.group("county")
        if county and county not in COUNTY_PLATE_CODES:
            return ValidationResult(False, "PLATE_UNKNOWN_COUNTY", f"Indicativ de județ necunoscut: {county}.")
        letters = m.group("letters")
        if letters[0] in "IQ" or "Q" in letters:
            return ValidationResult(False, "PLATE_UNUSUAL_FORMAT", "Combinație de litere neutilizată (I/Q); verificați OCR.")
        return OK
    if PLATE_TEMPORARY.match(plate) or PLATE_SPECIAL.match(plate):
        return ValidationResult(
            False,
            "PLATE_UNUSUAL_FORMAT",
            "Număr provizoriu/special sau format istoric; acceptat, dar necesită verificare.",
        )
    return ValidationResult(False, "PLATE_UNUSUAL_FORMAT", "Formatul nu corespunde unui număr românesc uzual; verificați.")


# ---------------------------------------------------------------------------
# Identity document series / number (CI model 1997)
# ---------------------------------------------------------------------------


def validate_id_series(series: str | None) -> ValidationResult:
    if not series:
        return ValidationResult(False, "MISSING_VALUE", "Seria actului lipsă.")
    if not re.fullmatch(r"[A-Z]{2}", series):
        return ValidationResult(False, "ID_SERIES_INVALID", "Seria CI trebuie să fie formată din 2 litere.")
    return OK


def validate_id_number(number: str | None, doc_type: str | None = None) -> ValidationResult:
    """CI model 1997: 6 digits. CEI: the document number is 2 letters + 7
    digits (stored here as series + number), older CEI batches may use 6."""
    if not number:
        return ValidationResult(False, "MISSING_VALUE", "Numărul actului lipsă.")
    pattern, label = (r"\d{6,7}", "6–7 cifre") if doc_type == "CEI" else (r"\d{6}", "6 cifre")
    if not re.fullmatch(pattern, number):
        return ValidationResult(False, "ID_NUMBER_INVALID", f"Numărul actului trebuie să fie format din {label}.")
    return OK


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

_DATE_DMY = re.compile(r"^\s*(\d{1,2})[./\-\s](\d{1,2})[./\-\s](\d{4})\s*$")
_DATE_ISO = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})\s*$")


def parse_date(value: str | None) -> date | None:
    """Parse DD.MM.YYYY / DD-MM-YYYY / YYYY-MM-DD. Two-digit years are rejected
    (ambiguous) — callers decide explicitly how to treat them."""
    if not value:
        return None
    m = _DATE_ISO.match(value)
    if m:
        y, mo, d = (int(x) for x in m.groups())
    else:
        m = _DATE_DMY.match(value)
        if not m:
            return None
        d, mo, y = (int(x) for x in m.groups())
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def normalize_date(value: str | None) -> str | None:
    """Return YYYY-MM-DD for unambiguous input; otherwise the trimmed input
    unchanged so the validator can flag it (never guessed)."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    parsed = parse_date(value)
    return parsed.isoformat() if parsed else value


def validate_iso_date(value: str | None, *, not_future: bool = False, today: date | None = None) -> ValidationResult:
    if not value:
        return ValidationResult(False, "MISSING_VALUE", "Dată lipsă.")
    parsed = parse_date(value)
    if parsed is None or not _DATE_ISO.match(value):
        return ValidationResult(False, "DATE_INVALID", "Data nu este într-un format neambiguu (AAAA-LL-ZZ).")
    if parsed.year < 1900:
        return ValidationResult(False, "DATE_IMPLAUSIBLE", "Data este anterioară anului 1900.")
    today = today or date.today()
    if not_future and parsed > today:
        return ValidationResult(False, "DATE_IN_FUTURE", "Data este în viitor.")
    return OK


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------


def parse_positive_int(value: str | int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    m = re.search(r"\d[\d\s.]*", value)
    if not m:
        return None
    digits = re.sub(r"[\s.]", "", m.group(0))
    try:
        return int(digits)
    except ValueError:
        return None


def validate_range(value: int | None, low: int, high: int, label: str, unit: str) -> ValidationResult:
    if value is None:
        return ValidationResult(False, "MISSING_VALUE", f"{label} lipsă.")
    if value <= 0:
        return ValidationResult(False, "NUMBER_NOT_POSITIVE", f"{label} trebuie să fie > 0 {unit}.")
    if not (low <= value <= high):
        return ValidationResult(
            False, "NUMBER_IMPLAUSIBLE", f"{label} = {value} {unit} este în afara intervalului plauzibil {low}-{high}."
        )
    return OK


# ---------------------------------------------------------------------------
# Fuel
# ---------------------------------------------------------------------------

FUEL_VALUES = ("PETROL", "DIESEL", "LPG", "CNG", "ELECTRIC", "HYBRID_PETROL", "HYBRID_DIESEL", "HYDROGEN", "OTHER")


def normalize_fuel(value: str | None) -> str | None:
    """Map Romanian P.3 wording to a neutral enum. Unknown wording -> OTHER
    (flagged for review by the caller), never a guess between real values."""
    if value is None:
        return None
    v = strip_diacritics(value).upper().strip()
    if not v:
        return None
    if v in FUEL_VALUES:
        return v
    has_el = "ELECTRIC" in v or v in {"EL", "E"}
    if "HIBRID" in v or "HYBRID" in v or ("/" in v and has_el):
        if "MOTORIN" in v or "DIESEL" in v:
            return "HYBRID_DIESEL"
        return "HYBRID_PETROL"
    if "BENZIN" in v and ("GPL" in v or "LPG" in v):
        return "LPG"
    if "GPL" in v or "LPG" in v:
        return "LPG"
    if "GNC" in v or "CNG" in v or "METAN" in v:
        return "CNG"
    if "MOTORIN" in v or "DIESEL" in v:
        return "DIESEL"
    if "BENZIN" in v or "PETROL" in v or "GASOLINE" in v:
        return "PETROL"
    if has_el:
        return "ELECTRIC"
    if "HIDROGEN" in v or "HYDROGEN" in v:
        return "HYDROGEN"
    return "OTHER"


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


def normalize_name(value: str | None) -> str | None:
    if value is None:
        return None
    v = clean_spaces(value)
    if not v:
        return None
    v = re.sub(r"\s*-\s*", "-", v)
    return fix_ro_diacritics(v.upper())


def validate_name(value: str | None, label: str) -> ValidationResult:
    if not value:
        return ValidationResult(False, "MISSING_VALUE", f"{label} lipsă.")
    if re.search(r"\d", value):
        return ValidationResult(False, "NAME_CONTAINS_DIGITS", f"{label} conține cifre; probabil eroare OCR.")
    if re.search(r"ROMANIA|ROUMANIE|IDENTIT|CARTE|CARD|PRENUME|NUME|SURNAME|GIVEN|NATIONAL",
                 strip_diacritics(value).upper()):
        return ValidationResult(False, "NAME_LOOKS_LIKE_LABEL",
                                f"{label} conține text tipărit al actului (etichetă/antet); probabil citit greșit.")
    if len(re.sub(r"[^A-Za-zĂÂÎȘŞȚŢăâîșşțţ]", "", value)) < 2:
        return ValidationResult(False, "NAME_TOO_SHORT", f"{label} are sub 2 litere; probabil citit parțial.")
    if not re.fullmatch(r"[A-ZĂÂÎȘŞȚŢÁÉÍÓÖÜŐŰÇ' \-.]+", value):
        return ValidationResult(False, "NAME_UNUSUAL_CHARS", f"{label} conține caractere neobișnuite.")
    return OK


VEHICLE_CATEGORY = re.compile(r"^(?:[MNO][1-4]G?|L[1-7]E?|T[1-5]|R[1-4]|S[12])$")


def validate_category(value: str | None) -> ValidationResult:
    if not value:
        return OK
    if not VEHICLE_CATEGORY.match(value):
        return ValidationResult(False, "CATEGORY_UNUSUAL",
                                f"Categoria „{value}” nu este un cod de categorie UE (ex. M1, N1, L3e); verificați.")
    return OK


def names_equivalent(a: str | None, b: str | None) -> bool:
    """Compare two person names ignoring order, diacritics and hyphens."""
    if not a or not b:
        return False

    def tokens(s: str) -> set[str]:
        return set(re.split(r"[\s\-]+", strip_diacritics(s).upper().strip())) - {""}

    return tokens(a) == tokens(b)
