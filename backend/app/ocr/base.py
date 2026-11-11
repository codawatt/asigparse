"""Engine-neutral OCR data model.

The parsers only see `OcrDocument`; any engine (Tesseract, PaddleOCR, a cloud
API) can be plugged in by implementing `OcrEngine.recognize`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from PIL import Image


@dataclass
class OcrWord:
    text: str
    confidence: float  # 0..1
    bbox: tuple[int, int, int, int]  # left, top, width, height (in processed image pixels)


@dataclass
class OcrLine:
    words: list[OcrWord]
    page: int = 0

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def confidence(self) -> float | None:
        if not self.words:
            return None
        return sum(w.confidence for w in self.words) / len(self.words)

    @property
    def top(self) -> int:
        return min(w.bbox[1] for w in self.words) if self.words else 0

    @property
    def left(self) -> int:
        return min(w.bbox[0] for w in self.words) if self.words else 0


@dataclass
class OcrDocument:
    lines: list[OcrLine] = field(default_factory=list)
    engine: str = "unknown"
    pages: int = 1
    rotation_applied: list[int] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def mean_confidence(self) -> float | None:
        words = [w for line in self.lines for w in line.words]
        if not words:
            return None
        return sum(w.confidence for w in words) / len(words)

    @property
    def char_count(self) -> int:
        return sum(len(w.text) for line in self.lines for w in line.words)


class OcrEngine(Protocol):
    name: str

    def is_available(self) -> bool: ...

    def recognize(self, image: Image.Image, page: int = 0) -> tuple[list[OcrLine], int]:
        """Return recognised lines and the clockwise rotation (degrees) applied."""
        ...


class OcrUnavailableError(RuntimeError):
    """Raised when the configured OCR engine cannot be executed."""
