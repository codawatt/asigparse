"""Tesseract adapter (local, offline)."""

from __future__ import annotations

import logging
import re

import pytesseract
from PIL import Image

from .base import OcrLine, OcrUnavailableError, OcrWord

log = logging.getLogger("asigparse.ocr")


class TesseractEngine:
    name = "tesseract"
    preprocessing = "full"

    def __init__(self, cmd: str | None, languages: str = "ron+eng", psm: int = 6):
        self.cmd = cmd
        self.languages = languages
        self.psm = psm
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
        self._available: bool | None = None
        self._langs: list[str] = []

    # -- availability --------------------------------------------------
    def is_available(self) -> bool:
        if self._available is None:
            try:
                pytesseract.get_tesseract_version()
                self._langs = pytesseract.get_languages(config="")
                self._available = True
            except Exception:  # pragma: no cover - depends on host
                self._available = False
        return self._available

    def unavailable_reason(self) -> str | None:
        if not self.is_available():
            return "Tesseract nu este instalat sau nu poate fi executat."
        missing = self.missing_languages()
        return f"Lipsesc datele de limbă Tesseract: {', '.join(missing)}." if missing else None

    def version(self) -> str | None:
        try:
            return str(pytesseract.get_tesseract_version())
        except Exception:
            return None

    def effective_languages(self) -> str:
        if not self.is_available():
            raise OcrUnavailableError("Tesseract nu este instalat sau nu poate fi executat.")
        wanted = [lang for lang in self.languages.split("+") if lang]
        present = [lang for lang in wanted if lang in self._langs]
        if not present:
            raise OcrUnavailableError(
                f"Niciunul dintre limbajele OCR cerute ({self.languages}) nu este instalat în Tesseract."
            )
        return "+".join(present)

    def missing_languages(self) -> list[str]:
        if not self.is_available():
            return self.languages.split("+")
        return [lang for lang in self.languages.split("+") if lang and lang not in self._langs]

    # -- orientation ---------------------------------------------------
    def detect_rotation(self, image: Image.Image) -> int:
        """Return clockwise rotation suggested by Tesseract OSD (0 if unsure)."""
        if "osd" not in self._langs:
            return 0
        try:
            osd = pytesseract.image_to_osd(image, config="--psm 0")
        except pytesseract.TesseractError:
            return 0
        rot = re.search(r"Rotate:\s+(\d+)", osd)
        conf = re.search(r"Orientation confidence:\s+([\d.]+)", osd)
        if rot and conf and float(conf.group(1)) >= 2.0:
            return int(rot.group(1)) % 360
        return 0

    # -- recognition ---------------------------------------------------
    def recognize(self, image: Image.Image, page: int = 0) -> tuple[list[OcrLine], int]:
        langs = self.effective_languages()
        rotation = self.detect_rotation(image)
        if rotation:
            # OSD 'Rotate' is the clockwise rotation needed; PIL rotates counter-clockwise
            image = image.rotate(-rotation, expand=True)
        try:
            data = pytesseract.image_to_data(
                image,
                lang=langs,
                config=f"--psm {self.psm} -c preserve_interword_spaces=1",
                output_type=pytesseract.Output.DICT,
            )
        except pytesseract.TesseractError as exc:
            # never include image content in logs; the stderr of tesseract is fine
            log.warning("tesseract failed: status=%s", getattr(exc, "status", "?"))
            raise OcrUnavailableError("Motorul OCR a eșuat la procesarea imaginii.") from exc
        lines: dict[tuple[int, int, int], list[OcrWord]] = {}
        for i, text in enumerate(data["text"]):
            text = (text or "").strip()
            conf = float(data["conf"][i])
            if not text or conf < 0:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(
                OcrWord(
                    text=text,
                    confidence=max(0.0, min(1.0, conf / 100.0)),
                    bbox=(data["left"][i], data["top"][i], data["width"][i], data["height"][i]),
                )
            )
        # keep Tesseract's reading order (block -> paragraph -> line); it is
        # column-aware, which matters for "label on one line, value below".
        result = [OcrLine(words=words, page=page) for words in lines.values() if words]
        return result, rotation
