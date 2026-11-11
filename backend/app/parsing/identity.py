"""Field mapping for Romanian identity cards (CI model 1997; CEI/CIS detected only).

Strategy, in order of trust:
  1. Visual inspection zone (VIZ): bilingual labels -> value on the same or next line.
  2. MRZ (check-digit protected) as fallback / cross-check.
Missing values stay None. Nothing is inferred from other fields (e.g. the
birth date is *not* derived from the CNP and the address is never guessed).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..ocr.base import OcrDocument, OcrLine
from ..validation.validators import (
    cnp_check_digit,
    normalize_name,
)
from .common import Extracted, aligned_chunk, fold, line_conf, median_height, split_chunks, substring_confidence
from .mrz import MrzResult, find_mrz

LBL_FIRST = re.compile(r"prenume|prenom|first\s*name|given\s*name")
LBL_LAST = re.compile(r"(?<![a-z])(nume|nom)(?![a-z])|last\s*name|surname")
LBL_ADDRESS = re.compile(r"domicil|adresse|address")
LBL_VALIDITY = re.compile(r"valabil|validit|expir")
LBL_STOP = re.compile(
    r"prenume|prenom|first\s*name|(?<![a-z])(nume|nom)(?![a-z])|last\s*name|cetatenie|nationalit|"
    r"(?<![a-z])sex(e)?(?![a-z])|loc\s*nast|lieu\s*de|place\s*of|domicil|adresse|address|emis|delivr|issued|"
    r"valabil|validit|expir|(?<![a-z])cnp(?![a-z])|seria|carte\s*de|identity|roumanie|romania"
)
LABEL_WORDS = {
    "nume", "nom", "last", "name", "prenume", "prenom", "first", "given", "surname",
    "domiciliu", "adresse", "address", "/", "|",
}


@dataclass
class IdentityExtraction:
    document_type: str  # CI_1997 | CEI | CIS | UNKNOWN_ID
    first_name: Extracted
    last_name: Extracted
    national_id: Extracted
    series: Extracted
    number: Extracted
    expiry_date: Extracted
    address: Extracted
    address_label_present: bool
    mrz: MrzResult | None
    notes: list[str] = field(default_factory=list)


def _missing(source: str | None = None, note: str | None = None) -> Extracted:
    return Extracted(value=None, confidence=None, source=source, note=note)


def detect_identity_subtype(doc: OcrDocument) -> str:
    t = fold(doc.text)
    if "electronic" in t or "eid" in t.split():
        return "CEI"
    if "simpl" in t and "carte de identitate" in t:
        return "CIS"
    return "CI_1997"


def _strip_label_words(text: str) -> str:
    """Remove trilingual label words ("Nume/Nom/Last name") from a chunk."""
    tokens = [t for t in re.split(r"[\s/|]+", text) if t]
    kept = [t for t in tokens if fold(t).strip(":.") not in LABEL_WORDS]
    return " ".join(kept).strip(" :|.-")


def _is_value_text(t: str) -> bool:
    t = t.strip()
    if not t or LBL_STOP.search(fold(t)):
        return False
    if t.count("<") >= 3:  # MRZ
        return False
    return bool(re.search(r"[A-Za-zĂÂÎȘŞȚŢăâîșşțţ]{2,}", t))


def _label_chunks(lines: list[OcrLine], label: re.Pattern[str], exclude: re.Pattern[str] | None):
    """Yield (line_index, chunk) for every column chunk that holds the label."""
    for i, ln in enumerate(lines):
        for ch in split_chunks(ln):
            f = fold(ch.text)
            if label.search(f) and not (exclude is not None and exclude.search(f)):
                yield i, ch


def _below(lines: list[OcrLine], i: int, ch: OcrLine, max_lines: int) -> list[OcrLine]:
    """Value chunks in the same column directly below a label chunk."""
    tol = 3.0 * median_height(ch)
    out = []
    for nxt in lines[i + 1 : i + 1 + max_lines]:
        c = aligned_chunk(nxt, ch.left, tol)
        if c is None:
            break
        out.append(c)
    return out


def _name_after_label(lines: list[OcrLine], label: re.Pattern[str], exclude: re.Pattern[str] | None, source: str) -> Extracted | None:
    for i, ch in _label_chunks(lines, label, exclude):
        same = _strip_label_words(ch.text)
        if same and re.fullmatch(r"[A-Za-zĂÂÎȘŞȚŢăâîșşțţ \-']{2,}", same) and not LBL_STOP.search(fold(same)):
            return Extracted(normalize_name(same), substring_confidence(ch, same), source)
        for c in _below(lines, i, ch, 1):
            if _is_value_text(c.text):
                value = re.sub(r"[^A-Za-zĂÂÎȘŞȚŢăâîșşțţ \-']", "", c.text).strip()
                if len(value) >= 2:
                    return Extracted(normalize_name(value), line_conf(c), source)
    return None


def _find_cnp(lines: list[OcrLine]) -> Extracted:
    candidates: list[Extracted] = []
    for ln in lines:
        f = fold(ln.text)
        squashed = re.sub(r"(?<=\d)[\s.](?=\d)", "", ln.text)
        for m in re.finditer(r"(?<!\d)([1-9]\d{12})(?!\d)", squashed):
            near_label = "cnp" in f
            ex = Extracted(m.group(1), substring_confidence(ln, m.group(1)), "identity.CNP" if near_label else "identity.text")
            if cnp_check_digit(m.group(1)[:12]) == int(m.group(1)[12]):
                ex.checks.append("cnp_checksum")
            candidates.append(ex)
    if not candidates:
        return _missing("identity.CNP")
    # Prefer a value next to the CNP label, then checksum-valid ones.
    candidates.sort(key=lambda e: (e.source != "identity.CNP", "cnp_checksum" not in e.checks))
    return candidates[0]


def _find_series_number(lines: list[OcrLine], mrz: MrzResult | None) -> tuple[Extracted, Extracted]:
    for ln in lines:
        t = ln.text.upper()
        m = re.search(r"SER[I1L]A\s*[:.]?\s*([A-Z]{2})\s*N[RO]\.?\s*[:.]?\s*(\d{6})(?!\d)", t)
        if m:
            conf = line_conf(ln)
            return (
                Extracted(m.group(1), substring_confidence(ln, m.group(1)) or conf, "identity.SERIA"),
                Extracted(m.group(2), substring_confidence(ln, m.group(2)) or conf, "identity.NR"),
            )
    if mrz and mrz.document_number and re.fullmatch(r"[A-Z]{2}\d{6}", mrz.document_number):
        checks = ["mrz_check_digit"] if mrz.document_number_valid else []
        note = None if mrz.document_number_valid else "Cifra de control MRZ pentru numărul documentului nu se potrivește."
        return (
            Extracted(mrz.document_number[:2], mrz.confidence, "identity.MRZ", list(checks), note),
            Extracted(mrz.document_number[2:], mrz.confidence, "identity.MRZ", list(checks), note),
        )
    return _missing("identity.SERIA"), _missing("identity.NR")


def _find_address(lines: list[OcrLine]) -> tuple[Extracted, bool]:
    for i, ch in _label_chunks(lines, LBL_ADDRESS, None):
        parts: list[str] = []
        confs: list[float] = []
        same = _strip_label_words(ch.text)
        if same and len(same) > 3 and not LBL_STOP.search(fold(same)):
            parts.append(same)
            if ch.confidence is not None:
                confs.append(ch.confidence)
        for nxt in _below(lines, i, ch, 3):
            t = nxt.text.strip()
            if not t or LBL_STOP.search(fold(t)) or t.count("<") >= 3:
                break
            parts.append(t)
            if nxt.confidence is not None:
                confs.append(nxt.confidence)
        if parts:
            value = re.sub(r"\s+", " ", " ".join(parts)).strip()
            return Extracted(value, round(sum(confs) / len(confs), 3) if confs else None, "identity.Domiciliu"), True
        return _missing("identity.Domiciliu", "Eticheta de domiciliu există, dar valoarea nu a fost citită."), True
    return _missing(None), False


def _find_expiry(lines: list[OcrLine], mrz: MrzResult | None) -> Extracted:
    for i, ch in _label_chunks(lines, LBL_VALIDITY, None):
        for cand in (ch, *_below(lines, i, ch, 1), *lines[i + 1 : i + 2]):
            dates = re.findall(r"(\d{2})[.\-/](\d{2})[.\-/](\d{4})(?!\d)", cand.text)
            if dates:
                d, m, y = dates[-1]
                return Extracted(f"{d}.{m}.{y}", line_conf(cand), "identity.Valabilitate")
    if mrz and mrz.expiry_date:
        checks = ["mrz_check_digit"] if mrz.expiry_date_valid else []
        note = None if mrz.expiry_date_valid else "Cifra de control MRZ pentru data expirării nu se potrivește."
        return Extracted(mrz.expiry_date.isoformat(), mrz.confidence, "identity.MRZ", checks, note)
    return _missing("identity.Valabilitate")


def parse_identity(doc: OcrDocument) -> IdentityExtraction:
    lines = doc.lines
    mrz = find_mrz(lines)
    subtype = detect_identity_subtype(doc)
    notes: list[str] = []

    last = _name_after_label(lines, LBL_LAST, LBL_FIRST, "identity.Nume")
    first = _name_after_label(lines, LBL_FIRST, None, "identity.Prenume")

    if mrz:
        if last is None and mrz.last_name:
            last = Extracted(normalize_name(mrz.last_name), mrz.confidence, "identity.MRZ",
                             note="Preluat din MRZ (fără diacritice).")
        if first is None and mrz.first_name:
            first = Extracted(normalize_name(mrz.first_name), mrz.confidence, "identity.MRZ",
                              note="Preluat din MRZ (fără diacritice; prenumele compuse pot fi separate diferit).")
        if mrz.problems:
            notes.append("MRZ citit parțial / cu cifre de control nepotrivite: " + ", ".join(mrz.problems))

    series, number = _find_series_number(lines, mrz)
    address, label_present = _find_address(lines)
    if not label_present:
        address.note = (
            "Domiciliul nu apare pe acest tip de act (CEI) — nu poate fi extras prin OCR."
            if subtype == "CEI"
            else "Câmpul de domiciliu nu a fost găsit pe imagine."
        )

    return IdentityExtraction(
        document_type=subtype,
        first_name=first or _missing("identity.Prenume"),
        last_name=last or _missing("identity.Nume"),
        national_id=_find_cnp(lines),
        series=series,
        number=number,
        expiry_date=_find_expiry(lines, mrz),
        address=address,
        address_label_present=label_present,
        mrz=mrz,
        notes=notes,
    )


def identity_score(doc: OcrDocument) -> int:
    t = fold(doc.text)
    score = 0
    for kw, pts in (
        ("carte de identitate", 4), ("identity card", 4), ("carte d'identite", 3), ("idrou", 4),
        ("cnp", 2), ("prenume", 2), ("domiciliu", 2), ("valabilitate", 2), ("seria", 2),
        ("cetatenie", 1), ("loc nastere", 1), ("emisa de", 1),
    ):
        if kw in t:
            score += pts
    if find_mrz(doc.lines):
        score += 3
    return score
