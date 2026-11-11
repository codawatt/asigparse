"""Machine Readable Zone (ICAO 9303 TD2, 2x36) parser for the Romanian CI model 1997.

The MRZ is a strong, self-checking signal: every key field carries a check
digit, so OCR mistakes are detected rather than silently accepted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from ..ocr.base import OcrLine

_WEIGHTS = (7, 3, 1)


def _char_value(c: str) -> int:
    if c.isdigit():
        return int(c)
    if "A" <= c <= "Z":
        return ord(c) - 55
    return 0  # '<'


def check_digit(data: str) -> int:
    return sum(_char_value(c) * _WEIGHTS[i % 3] for i, c in enumerate(data)) % 10


def _clean(text: str) -> str:
    t = text.replace(" ", "")
    t = t.replace("«", "<<").replace("‹", "<").replace("(", "<").replace("{", "<").replace("[", "<")
    # The MRZ alphabet has no lower-case letters: OCR reading '<' as 's', 'c',
    # 'k'... is the usual failure, so lower-case letters become fillers.
    t = re.sub(r"[a-z]", "<", t)
    return re.sub(r"[^A-Z0-9<]", "", t.upper())


_TO_DIGIT = str.maketrans({"O": "0", "Q": "0", "D": "0", "U": "0", "I": "1", "L": "1", "Z": "2", "S": "5",
                           "B": "8", "G": "6", "T": "7"})
_TO_ALPHA = str.maketrans({"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G", "7": "T"})


def _repair_field(raw: str, kind: str) -> str:
    return raw.translate(_TO_DIGIT if kind == "digit" else _TO_ALPHA)


def _checked(raw: str, cd: str, kind: str = "digit") -> tuple[str, bool]:
    """Return the field and whether its check digit verifies. A character
    substitution (O->0 ...) is only accepted when it makes the check digit
    verify, so no unverified correction is ever introduced."""
    cd_fixed = cd.translate(_TO_DIGIT)
    if cd_fixed.isdigit() and check_digit(raw) == int(cd_fixed):
        return raw, True
    repaired = _repair_field(raw, kind) if kind != "docnum" else raw[:2].translate(_TO_ALPHA) + raw[2:].translate(_TO_DIGIT)
    if cd_fixed.isdigit() and check_digit(repaired) == int(cd_fixed):
        return repaired, True
    return raw, False


@dataclass
class MrzResult:
    line1: str
    line2: str
    confidence: float | None
    last_name: str | None = None
    first_name: str | None = None
    document_number: str | None = None
    document_number_valid: bool = False
    nationality: str | None = None
    birth_date: date | None = None
    birth_date_valid: bool = False
    sex: str | None = None
    expiry_date: date | None = None
    expiry_date_valid: bool = False
    optional_data: str | None = None
    composite_valid: bool = False
    problems: list[str] = field(default_factory=list)


def _yymmdd(s: str, *, future: bool) -> date | None:
    if not re.fullmatch(r"\d{6}", s):
        return None
    yy, mm, dd = int(s[:2]), int(s[2:4]), int(s[4:6])
    today = date.today()
    if future:
        year = 2000 + yy  # expiry dates of currently valid documents
    else:
        year = 2000 + yy if 2000 + yy <= today.year else 1900 + yy
    try:
        return date(year, mm, dd)
    except ValueError:
        return None


def find_mrz(lines: list[OcrLine]) -> MrzResult | None:
    candidates: list[tuple[str, OcrLine]] = []
    for ln in lines:
        c = _clean(ln.text)
        digits = sum(ch.isdigit() for ch in c)
        if len(c) >= 28 and (c.count("<") >= 2 or ("<" in c and digits >= 12)):
            candidates.append((c, ln))
    l1 = next(((c, ln) for c, ln in candidates if c.startswith(("ID", "1D", "I0", "IO")) and "ROU" in c[:8]), None)
    l2 = next(
        ((c, ln) for c, ln in candidates if (l1 is None or ln is not l1[1]) and sum(ch.isdigit() for ch in c) >= 12),
        None,
    )
    if not l1 and not l2:
        return None
    line1 = (l1[0] if l1 else "").ljust(36, "<")[:36]
    line2 = (l2[0] if l2 else "").ljust(36, "<")[:36]
    confs = [x[1].confidence for x in (l1, l2) if x and x[1].confidence is not None]
    res = MrzResult(line1=line1, line2=line2, confidence=round(sum(confs) / len(confs), 3) if confs else None)

    if l1:
        body = line1[5:]
        if "<<" in body:
            last, _, first = body.partition("<<")
            res.last_name = last.replace("<", " ").strip() or None
            # Compound given names are separated by '<' in the MRZ; whether the
            # printed form uses a space or a hyphen is unknown, so use a space.
            res.first_name = re.sub(r"<+", " ", first).strip() or None
        else:
            res.problems.append("MRZ line 1 has no name separator")

    if l2:
        docnum, res.document_number_valid = _checked(line2[0:9], line2[9], "docnum")
        res.document_number = docnum.replace("<", "") or None
        res.nationality = line2[10:13].translate(_TO_ALPHA)
        dob, dob_ok = _checked(line2[13:19], line2[19])
        res.birth_date = _yymmdd(dob, future=False)
        res.birth_date_valid = dob_ok and res.birth_date is not None
        res.sex = line2[20] if line2[20] in "MF" else None
        exp, exp_ok = _checked(line2[21:27], line2[27])
        res.expiry_date = _yymmdd(exp, future=True)
        res.expiry_date_valid = exp_ok and res.expiry_date is not None
        res.optional_data = line2[28:35].replace("<", "") or None
        composite = docnum + line2[9] + dob + line2[19] + exp + line2[27] + line2[28:35]
        cd_comp = line2[35].translate(_TO_DIGIT)
        res.composite_valid = cd_comp.isdigit() and check_digit(composite) == int(cd_comp)
        if not res.document_number_valid:
            res.problems.append("document number check digit")
        if not res.birth_date_valid:
            res.problems.append("birth date check digit")
        if not res.expiry_date_valid:
            res.problems.append("expiry date check digit")
    return res
