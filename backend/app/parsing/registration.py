"""Field mapping for the Romanian vehicle registration certificate (talon).

The certificate uses harmonised EU codes (Directive 1999/37/EC) printed next
to each value: A, B, C.1.x, C.2.x, D.x, E, F.1, J, P.x, R, S.1 ...
The parser splits OCR lines into (code -> value) segments, so it tolerates
both "code above value" and "several codes on one line" layouts.

Holder (C.1) and owner (C.2) are always kept separate; C.1 is never used as a
substitute for a missing C.2.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..ocr.base import OcrDocument, OcrLine, OcrWord
from ..validation.validators import (
    normalize_fuel,
    normalize_name,
    normalize_plate,
    normalize_vin,
    parse_positive_int,
)
from .common import Extracted, fold, median_height, split_chunks, substring_confidence, words_confidence

# A code token, with separators ("D.1", "c.1.3", "C.2:3") ...
SEP_CODE = re.compile(r"^\(?(?P<code>[CcGg](?:[.,:]\s?[12][.,:]?|[12][.,:])\s?[1-3]|[DdFfPpSsVv][.,:]\s?[1-9])\)?[.:]?$")
# ... without separators, only trusted at the start of a column chunk ("S1", "C13")
BARE_CODE = re.compile(r"^\(?(?P<code>[Cc][12][1-3]|[DdFfPpSs][1-3])\)?[.:]?$")
# ... glued to its value by OCR ("P.11598", "F.11820", "P.3MOTORINA")
GLUED_CODE = re.compile(r"^(?P<code>[CcGg][.,:][12][.,:][1-3]|[DdFfPpSs][.,:][1-3])(?P<value>[0-9A-Z].*)$")
SINGLE_CODE = re.compile(r"^\(?([ABEJKR])\)?[.:]?$")
ADDRESS_CODES = {"C.1.3", "C.2.3"}
DESCRIPTOR = re.compile(r"^[A-Za-zĂÂÎȘŞȚŢăâîșşțţ ./]{2,40}:\s*")
GARBLED_CODE = re.compile(r"^(?=.*[0-9.,:])[A-Z][A-Z0-9.,:]{1,5}$")

PLATE_ANYWHERE = re.compile(r"(?<![A-Z0-9])((?:B\s?\d{2,3}|[A-Z]{2}\s?\d{2})\s?[A-Z]{3})(?![A-Z0-9])")
COMPANY = re.compile(
    r"(?<![A-Z])(S\.?C|S\.?R\.?L|S\.?A|IFN|PFA|I\.I|SCS|SNC|R\.A|COMPANIA|SOCIETATEA|BANCA|LEASING|ASOCIA[TȚ]IA"
    r"|PRIM[AĂ]RIA|MINISTERUL)(?![A-Z])"
)
VIN_ANYWHERE = re.compile(r"(?<![A-Z0-9])([A-Z0-9]{17})(?![A-Z0-9])")
# group headers / check boxes that end the previous field: "C.2", "C.3C.3.1", "C2=C1"
GROUP_HEADER = re.compile(r"^C[.,:]?[1-3](C[.,:]?3.*)?$|^C[1-3]=C1$", re.I)
# "D.1" misread as "0.1" (no real code starts with 0)
ZERO_D_CODE = re.compile(r"^[0O][.,:]\s?([1-3])[.:]?$")
# right-hand column / footer words that never belong to a value
VALUE_STOP = re.compile(
    r"\s+(?:Observa\w*|INSPEC\w*|ANEXA\b|Num[aă]r\w*\s+(?:certif|de\s+[îi]nmatric)\w*|Data\s+urm\w*|FILTRU\b|"
    r"ANV\.?\s?OPT\b|REPREZENTAN\w*|Nr\.?\s*CINT\w*|C[23]\s*=\s*C1).*$",
    re.I,
)
# single-letter codes found anywhere on a line by the shape of their value
TYPED_SINGLE = {
    "A": re.compile(r"(?<![\w.(])A\s+((?:B|[A-Z]{2})[\s-]?\d{2,3}[\s-]?[A-Z]{3})(?![A-Z0-9])"),
    "B": re.compile(r"(?<![\w.(])B\s+(\d{2}[./-]\d{2}[./-]\d{4})"),
    "E": re.compile(r"(?<![\w.(])E\s+([A-Z0-9]{17})(?![A-Z0-9])"),
    "J": re.compile(r"(?<![\w.(])J\s+(?:[A-ZĂÂÎȘŞȚŢ]+\s+)?([MNO][1-4]|L[1-7]E?|T[1-5])(?![A-Z0-9])"),
    "R": re.compile(r"(?<![\w.(])R\s+([A-ZĂÂÎȘŞȚŢ]{3,})(?![A-Z0-9])"),
}
CATEGORY_CODE = re.compile(r"(?<![A-Z0-9])([MNO][1-4]|L[1-7]E?|T[1-5])(?![A-Z0-9])")
BODY_CATEGORY = re.compile(
    r"\b(?:AUTOTURISM|AUTOUTILITAR[AĂ]|AUTOCAMION|MOTOCICLET[AĂ]|AUTOBUZ|REMORC[AĂ]|TRACTOR)\s+([MNOLT]\d[A-Z]?)\b"
)
C2_EQ_C1 = re.compile(r"C\s*\.?\s*2\s*=\s*C\s*\.?\s*1", re.I)


def _canonical(code: str) -> str:
    c = re.sub(r"[().,:\s]", "", code.upper())
    if c.startswith("G"):  # common OCR confusion C -> G in "C.2.1"
        c = "C" + c[1:]
    return ".".join(c) if len(c) > 1 else c


def _code_of(token: str, first_in_chunk: bool, allow_single: bool = True) -> tuple[str | None, str | None]:
    """Return (canonical code, glued value) for a token, or (None, None)."""
    t = token.strip()
    if "(" in t or ")" in t:
        # legend on the back/second page: "(D.1) Marca", "E) Numărul ..."
        return ("_LEGEND", None) if re.search(r"[A-Z]\)|\([A-Z]", t) else (None, None)
    if GROUP_HEADER.match(t):
        return "_GROUP", None
    if first_in_chunk:
        m = ZERO_D_CODE.match(t)
        if m:
            return f"D.{m.group(1)}", None
    m = SEP_CODE.match(t)
    if m:
        return _canonical(m.group("code")), None
    if first_in_chunk:
        m = BARE_CODE.match(t)
        if m:
            return _canonical(m.group("code")), None
        m = SINGLE_CODE.match(t)
        if m and allow_single:
            return m.group(1), None
    m = GLUED_CODE.match(t)
    if m:
        return _canonical(m.group("code")), m.group("value")
    return None, None


@dataclass
class Segment:
    code: str
    words: list[OcrWord] = field(default_factory=list)
    extra_lines: list[OcrLine] = field(default_factory=list)

    @property
    def text(self) -> str:
        parts = [" ".join(w.text for w in self.words)] + [ln.text for ln in self.extra_lines]
        t = re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip(" :|")
        t = VALUE_STOP.sub("", t)
        return DESCRIPTOR.sub("", t).strip()

    @property
    def confidence(self) -> float | None:
        ws = list(self.words) + [w for ln in self.extra_lines for w in ln.words]
        return words_confidence(ws)


def segment_lines(lines: list[OcrLine]) -> dict[str, Segment]:
    return segment_lines_with_orphans(lines)[0]


def segment_lines_with_orphans(lines: list[OcrLine]) -> tuple[dict[str, Segment], list[tuple[str, str]]]:
    """Split rows into column chunks, then chunks into code -> value segments.

    Handles: "E VIN" on one line, several codes per row ("P.1 1598 P.2 85"),
    two-column layouts, and a small code printed *above* its value."""
    segments: dict[str, Segment] = {}
    rows = [split_chunks(ln) for ln in lines]
    # (row index, chunk left x, segment) for segments still waiting for a value
    pending: list[tuple[int, int, float, Segment]] = []

    def register(code: str) -> Segment:
        seg = Segment(code)
        if code.startswith("_"):  # legend / group header: swallow text, never stored
            return seg
        if code not in segments or not segments[code].text:
            segments[code] = seg
        return seg

    orphans: list[tuple[str, str]] = []  # (illegible code-like text, following value)
    garbled_row: str | None = None
    for r, chunks in enumerate(rows):
        pending = [p for p in pending if r - p[0] <= 2]
        prev_garbled, garbled_row = garbled_row, None
        if (
            len(chunks) == 1
            and GARBLED_CODE.match(chunks[0].text.strip())
            and not _code_of(chunks[0].text, True)[0]
            and not any(not p[3].text and 1 <= r - p[0] <= 2 and abs(chunks[0].left - p[1]) <= p[2] for p in pending)
        ):
            garbled_row = chunks[0].text.strip()
            continue
        row_open: Segment | None = None  # code chunk on this row still without value
        for ch in chunks:
            tol = 3.0 * median_height(ch)
            attach = row_open is not None
            # a value printed under a code (e.g. plate "B 99 XYZ" under "A")
            # must not be read as the one-letter code "B"
            awaited = any(not p[3].text and 1 <= r - p[0] <= 2 and abs(ch.left - p[1]) <= p[2] for p in pending)
            current: Segment | None = row_open
            chunk_codes = 0
            for idx, w in enumerate(ch.words):
                # a chunk right after a value-less code chunk is that code's
                # value: do not read its first letter as a one-letter code
                code, glued = _code_of(w.text, first_in_chunk=(idx == 0 and not attach), allow_single=not awaited)
                if code:
                    chunk_codes += 1
                    current = register(code)
                    if glued:
                        current.words.append(OcrWord(glued, w.confidence, w.bbox))
                    continue
                # skip stray punctuation before the value, keep it inside ("SD / SDAAH")
                if current is not None and (current.words or re.search(r"[0-9A-Za-zĂÂÎȘŞȚŢăâîșşțţ]", w.text)):
                    current.words.append(w)
            if attach and row_open is not None and row_open.words:
                pending = [p for p in pending if p[3] is not row_open]
                if row_open.code in ADDRESS_CODES:
                    pending.append((r, min(w.bbox[0] for w in row_open.words), tol, row_open))
            if chunk_codes:
                # a new code in the same column closes any open address above
                pending = [p for p in pending if not (p[3].text and abs(p[1] - ch.left) <= p[2])]
                if current is not None and not current.words:
                    pending.append((r, ch.left, tol, current))
                    row_open = current
                else:
                    row_open = None
                    if current is not None and current.code in ADDRESS_CODES:
                        # a wrapped address line may start under the value or
                        # back under the code: accept anything in that span
                        value_left = min(w.bbox[0] for w in current.words)
                        span_mid = (ch.left + value_left) / 2
                        pending.append((r, span_mid, (value_left - ch.left) / 2 + tol, current))
                continue
            if attach:
                row_open = None
                continue
            # chunk without code: value of a code printed just above it, or
            # continuation of a multi-line address. Prefer the closest row.
            candidates = [p for p in pending if 1 <= r - p[0] <= 2 and abs(ch.left - p[1]) <= p[2]]
            if prev_garbled is not None and (not candidates or max(candidates, key=lambda p: p[0])[3].text):
                orphans.append((prev_garbled, ch.text.strip()))
                continue
            if not candidates:
                continue
            match = max(candidates, key=lambda p: p[0])
            pending.remove(match)
            seg = match[3]
            if not seg.text:
                seg.extra_lines.append(ch)
            elif seg.code in ADDRESS_CODES and len(seg.extra_lines) < 3 and not GARBLED_CODE.match(ch.text.strip()):
                seg.extra_lines.append(ch)
            else:
                continue
            if seg.code in ADDRESS_CODES:
                pending.append((r, match[1], match[2], seg))
    return segments, orphans


@dataclass
class RegistrationExtraction:
    registration_number: Extracted
    first_registration: Extracted
    holder_name: Extracted
    holder_address: Extracted
    owner_present: bool
    owner_name: Extracted
    owner_address: Extracted
    make: Extracted
    vehicle_type: Extracted
    model: Extracted
    vin: Extracted
    max_mass_kg: Extracted
    category: Extracted
    engine_cc: Extracted
    power_kw: Extracted
    fuel: Extracted
    fuel_raw: str | None
    color: Extracted
    seats: Extracted
    codes_found: list[str]
    notes: list[str] = field(default_factory=list)
    holder_partial: bool = False
    c2_eq_c1_box: bool = False
    owner_partial: bool = False


def _seg(segments: dict[str, Segment], code: str, transform=lambda v: v) -> Extracted:
    seg = segments.get(code)
    src = f"registration.{code}"
    if seg is None or not seg.text:
        return Extracted(None, None, src)
    value = transform(seg.text)
    return Extracted(value if value not in ("", None) else None, seg.confidence, src)


def _join_name(a: Extracted, b: Extracted, source: str) -> Extracted:
    parts = [p.value for p in (a, b) if p.value]
    if not parts:
        return Extracted(None, None, source)
    confs = [p.confidence for p in (a, b) if p.value and p.confidence is not None]
    return Extracted(
        normalize_name(" ".join(str(p) for p in parts)),
        round(sum(confs) / len(confs), 3) if confs else None,
        source,
    )


def _date_dmy(text: str) -> str | None:
    m = re.search(r"(\d{2})[.\-/ ](\d{2})[.\-/ ](\d{4})", text)
    if m:
        return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
    return text.strip() or None  # keep raw so the validator flags it


# Colours used on Romanian certificates (field R). Used only to accept an
# "R <word>" match on a line without any other field code.
COLORS = {
    "ALB", "NEGRU", "GRI", "ARGINTIU", "ARGINTI", "ROSU", "ALBASTRU", "VERDE", "GALBEN", "PORTOCALIU", "MARO",
    "BEJ", "VIOLET", "MOV", "AURIU", "BORDO", "GRENA", "CAFENIU", "CREM", "ROZ", "TURCOAZ", "BLEU", "MULTICOLOR",
}
_ANY_CODE = re.compile(r"(?<![\w(])(?:[CDFPSV][.,:]\d|[ABEJK]\s)")


def _typed(lines: list[OcrLine], code: str) -> Extracted | None:
    """Value of a one-letter code found anywhere on a line, by its shape."""
    for ln in lines:
        text = ln.text.upper()
        m = TYPED_SINGLE[code].search(text)
        if m and code == "R":
            # a colour must sit on a data row (another field code on the line)
            # or be a known colour word; legend/footer words are rejected
            word = fold(m.group(1)).upper()
            if word not in COLORS and not _ANY_CODE.search(text[: m.start()] + " " + text[m.end():]):
                continue
        if m:
            return Extracted(m.group(1), substring_confidence(ln, m.group(1)), f"registration.{code}")
    return None


_NAME_TAIL = re.compile(r"\s+[YZHIKQX]\s+\S.*$")  # "POPESCU Y X000000 Z ..." -> "POPESCU"


def _name_part(ex: Extracted) -> Extracted:
    if isinstance(ex.value, str):
        ex.value = _NAME_TAIL.sub("", ex.value).strip() or None
    return ex


def parse_registration(doc: OcrDocument) -> RegistrationExtraction:
    segments, orphans = segment_lines_with_orphans(doc.lines)
    notes: list[str] = [
        f"Cod ilizibil „{code}” urmat de textul „{value}” — nealocat automat; verificați manual "
        "(poate fi de ex. proprietarul C.2)."
        for code, value in orphans
    ]

    plate = _typed(doc.lines, "A")
    if plate is not None:
        plate.value = normalize_plate(plate.value)
    else:
        plate = _seg(segments, "A", normalize_plate)
    if plate.value is None:
        for ln in doc.lines:
            m = PLATE_ANYWHERE.search(ln.text.upper())
            if m:
                plate = Extracted(normalize_plate(m.group(1)), ln.confidence, "registration.text",
                                  note="Găsit fără eticheta A; verificați.")
                break

    vin = _typed(doc.lines, "E") or _seg(
        segments, "E", lambda t: normalize_vin(t.split(" ")[0] if len(t.replace(" ", "")) > 17 else t)
    )
    if vin.value is None:
        for ln in doc.lines:
            m = VIN_ANYWHERE.search(ln.text.upper().replace(" ", ""))
            if m and sum(ch.isdigit() for ch in m.group(1)) >= 3:
                vin = Extracted(m.group(1), ln.confidence, "registration.text",
                                note="Găsit fără eticheta E; verificați.")
                break

    c11, c12 = _name_part(_seg(segments, "C.1.1")), _name_part(_seg(segments, "C.1.2"))
    holder_name = _join_name(c11, c12, "registration.C.1")
    # a natural person has both C.1.1 (surname) and C.1.2 (given name); a
    # company has only C.1.1. One part alone for a person = partially read.
    holder_partial = bool(c12.value) and not c11.value or (
        bool(c11.value) and not c12.value and not COMPANY.search(str(c11.value).upper())
    )
    if holder_partial:
        holder_name.note = "Numele titularului pare citit parțial (lipsește C.1.1 sau C.1.2)."
    owner_last = _name_part(_seg(segments, "C.2.1"))
    owner_first = _name_part(_seg(segments, "C.2.2"))
    owner_present = bool(owner_last.value or owner_first.value)
    owner_partial = bool(owner_first.value) and not owner_last.value or (
        bool(owner_last.value) and not owner_first.value and not COMPANY.search(str(owner_last.value).upper())
    )
    owner_name = _join_name(owner_last, owner_first, "registration.C.2")

    fuel_seg = _seg(segments, "P.3")
    fuel_raw = fuel_seg.value if isinstance(fuel_seg.value, str) else None
    fuel = Extracted(normalize_fuel(fuel_raw), fuel_seg.confidence, fuel_seg.source)

    def as_int(code: str) -> Extracted:
        return _seg(segments, code, parse_positive_int)

    def as_upper(code: str) -> Extracted:
        return _seg(segments, code, lambda t: re.sub(r"\s+", " ", t).upper().strip())

    if not segments:
        notes.append("Nu a fost recunoscut niciun cod armonizat (A, B, C.1, D.1, E, P.1 ...).")

    first_reg = _typed(doc.lines, "B")
    if first_reg is not None:
        first_reg.value = _date_dmy(first_reg.value)
    else:
        first_reg = _seg(segments, "B", _date_dmy)

    category = _typed(doc.lines, "J")
    if category is None:
        category = _seg(segments, "J", lambda t: (CATEGORY_CODE.search(t.upper()) or re.match(r"(.*)", t.upper())).group(1))
    if category.value is None:
        for ln in doc.lines:
            m = BODY_CATEGORY.search(ln.text.upper())
            if m:
                category = Extracted(m.group(1), substring_confidence(ln, m.group(1)), "registration.J")
                break

    color = _typed(doc.lines, "R") or _seg(segments, "R", lambda t: re.sub(r"\s+", " ", t).upper().split(" ")[0])

    # New-format certificates print C.2 and a "C2=C1" check box instead of a
    # separate C.1 block. OCR cannot tell ticked from unticked reliably, so the
    # owner is only *suggested* as holder (operator confirms), never copied.
    c2_eq_c1_box = holder_name.value is None and owner_present and any(C2_EQ_C1.search(ln.text) for ln in doc.lines)

    return RegistrationExtraction(
        registration_number=plate,
        first_registration=first_reg,
        holder_name=holder_name,
        holder_address=_seg(segments, "C.1.3"),
        owner_present=owner_present,
        owner_name=owner_name,
        owner_address=_seg(segments, "C.2.3"),
        make=as_upper("D.1"),
        vehicle_type=as_upper("D.2"),
        model=as_upper("D.3"),
        vin=vin,
        max_mass_kg=as_int("F.1"),
        category=category,
        engine_cc=as_int("P.1"),
        power_kw=as_int("P.2"),
        fuel=fuel,
        fuel_raw=fuel_raw,
        color=color,
        seats=as_int("S.1"),
        codes_found=sorted(segments.keys()),
        notes=notes,
        holder_partial=holder_partial,
        c2_eq_c1_box=c2_eq_c1_box,
        owner_partial=owner_partial,
    )


def registration_score(doc: OcrDocument) -> int:
    t = fold(doc.text)
    score = 0
    for kw in ("certificat de inmatriculare", "inmatriculare", "registration certificate", "certificat"):
        if kw in t:
            score += 3
    segs = segment_lines(doc.lines)
    score += len([c for c in segs if "." in c or c in {"A", "B", "E"}])
    return score
