"""Runtime configuration (environment variables, all optional)."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path


def _find_tesseract() -> str | None:
    explicit = os.getenv("ASIGPARSE_TESSERACT_CMD")
    if explicit:
        return explicit
    found = shutil.which("tesseract")
    if found:
        return found
    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        r"C:\msys64\ucrt64\bin\tesseract.exe",
        r"C:\msys64\mingw64\bin\tesseract.exe",
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/opt/homebrew/bin/tesseract",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


@dataclass(frozen=True)
class Settings:
    tesseract_cmd: str | None = field(default_factory=_find_tesseract)
    ocr_languages: str = os.getenv("ASIGPARSE_OCR_LANGS", "ron+eng")
    confidence_threshold: float = float(os.getenv("ASIGPARSE_CONFIDENCE_THRESHOLD", "0.85"))
    max_upload_bytes: int = int(os.getenv("ASIGPARSE_MAX_UPLOAD_MB", "10")) * 1024 * 1024
    max_pdf_pages: int = 2
    pdf_render_dpi: int = 300
    processing_ttl_seconds: int = int(os.getenv("ASIGPARSE_TTL_SECONDS", "1800"))
    cors_origins: tuple[str, ...] = tuple(
        o.strip()
        for o in os.getenv("ASIGPARSE_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
        if o.strip()
    )
    samples_dir: Path = Path(__file__).resolve().parent.parent / "samples"


settings = Settings()
