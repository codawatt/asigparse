"""OCR engine registry and default-engine selection."""

from __future__ import annotations

from ..config import Settings
from .oneocr import OneOcrEngine
from .tesseract import TesseractEngine

ENGINE_NAMES = ("oneocr", "tesseract")


def build_engines(settings: Settings) -> dict:
    return {
        "oneocr": OneOcrEngine(settings.oneocr_dir),
        "tesseract": TesseractEngine(settings.tesseract_cmd, settings.ocr_languages),
    }


def pick_default(engines: dict, preference: str):
    """`auto` prefers OneOCR (more accurate and faster on our benchmark, see
    docs/OCR_BENCHMARK.md) and falls back to Tesseract when OneOCR is missing."""
    if preference in engines:
        return engines[preference]
    if engines["oneocr"].is_available():
        return engines["oneocr"]
    return engines["tesseract"]
