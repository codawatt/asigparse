"""Shared parsing primitives."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..ocr.base import OcrLine, OcrWord
from ..validation.validators import strip_diacritics


@dataclass
class Extracted:
    """One extracted field value together with its provenance."""

    value: object | None
    confidence: float | None
    source: str | None
    checks: list[str] = field(default_factory=list)  # e.g. ["mrz_check_digit"]
    note: str | None = None


def fold(text: str) -> str:
    """Lower-case ASCII folding used for label matching only."""
    return strip_diacritics(text).lower()


def words_confidence(words: list[OcrWord]) -> float | None:
    if not words:
        return None
    return round(sum(w.confidence for w in words) / len(words), 3)


def line_conf(line: OcrLine) -> float | None:
    c = line.confidence
    return round(c, 3) if c is not None else None


def substring_confidence(line: OcrLine, substring: str) -> float | None:
    """Mean confidence of the words in `line` that overlap `substring`."""
    if not substring:
        return None
    target = re.sub(r"\s+", "", substring).lower()
    picked = [w for w in line.words if re.sub(r"\s+", "", w.text).lower() in target or target in w.text.lower()]
    picked = [w for w in picked if w.text.strip()]
    return words_confidence(picked) if picked else line_conf(line)


def median_height(line: OcrLine) -> float:
    hs = sorted(w.bbox[3] for w in line.words) or [20]
    return float(hs[len(hs) // 2])


def split_chunks(line: OcrLine, gap_factor: float = 2.2) -> list[OcrLine]:
    """Split a visual row into column chunks at large horizontal gaps.

    Card-like documents put several label/value columns on one row
    ("IONESCU ......... M"); chunking keeps those apart."""
    if len(line.words) <= 1:
        return [line]
    limit = gap_factor * median_height(line)
    words = sorted(line.words, key=lambda w: w.bbox[0])
    out: list[list[OcrWord]] = [[words[0]]]
    for prev, w in zip(words, words[1:]):
        gap = w.bbox[0] - (prev.bbox[0] + prev.bbox[2])
        if gap > limit:
            out.append([w])
        else:
            out[-1].append(w)
    return [OcrLine(words=ws, page=line.page) for ws in out]


def aligned_chunk(line: OcrLine, left: int, tolerance: float) -> OcrLine | None:
    """Chunk of `line` that starts near x=`left` (same column)."""
    best = None
    for ch in split_chunks(line):
        d = abs(ch.left - left)
        if d <= tolerance and (best is None or d < abs(best.left - left)):
            best = ch
    return best


def value_after_label(line_text: str, label_regex: re.Pattern[str]) -> str | None:
    """Text following a label on the same line (stripping separators)."""
    m = label_regex.search(fold(line_text))
    if not m:
        return None
    # Map the folded index back: folding keeps length for Romanian diacritics
    rest = line_text[m.end():] if len(fold(line_text)) == len(line_text) else ""
    rest = rest.strip(" :/|.-_\t")
    return rest or None
