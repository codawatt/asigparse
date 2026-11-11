"""File sniffing, decoding (JPG/PNG/PDF) and image preprocessing.

Everything happens in memory; nothing is written to disk by this module.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 60_000_000  # decompression-bomb guard

SUPPORTED_TYPES = {"image/jpeg", "image/png", "application/pdf"}


class FileRejectedError(Exception):
    def __init__(self, code: str, message: str, http_status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def sniff_mime(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:1024].lstrip().startswith(b"%PDF-"):
        return "application/pdf"
    return None


@dataclass
class DecodedFile:
    mime: str
    pages: list[Image.Image]
    total_pdf_pages: int | None = None
    warnings: list[str] = field(default_factory=list)


def decode_upload(data: bytes, *, max_pdf_pages: int, dpi: int) -> DecodedFile:
    mime = sniff_mime(data)
    if mime is None:
        raise FileRejectedError(
            "UNSUPPORTED_FILE_TYPE", "Tip de fișier nesuportat. Acceptăm doar JPG, PNG sau PDF.", 400
        )
    if mime == "application/pdf":
        return _decode_pdf(data, max_pdf_pages=max_pdf_pages, dpi=dpi)
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Image.DecompressionBombError:
        raise FileRejectedError("IMAGE_TOO_LARGE", "Imaginea are prea mulți pixeli.", 413)
    except (UnidentifiedImageError, OSError):
        raise FileRejectedError("CORRUPT_FILE", "Imaginea nu poate fi citită (fișier corupt sau incomplet).", 400)
    img = ImageOps.exif_transpose(img)
    return DecodedFile(mime=mime, pages=[img])


def _decode_pdf(data: bytes, *, max_pdf_pages: int, dpi: int) -> DecodedFile:
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(data)
    except Exception:
        raise FileRejectedError("CORRUPT_FILE", "PDF-ul nu poate fi deschis (corupt sau protejat cu parolă).", 400)
    try:
        total = len(pdf)
        if total == 0:
            raise FileRejectedError("CORRUPT_FILE", "PDF-ul nu conține pagini.", 400)
        warnings: list[str] = []
        if total > max_pdf_pages:
            warnings.append(
                f"PDF-ul are {total} pagini; au fost procesate doar primele {max_pdf_pages}."
            )
        pages = []
        for i in range(min(total, max_pdf_pages)):
            page = pdf[i]
            pages.append(page.render(scale=dpi / 72).to_pil())
            page.close()
        return DecodedFile(mime="application/pdf", pages=pages, total_pdf_pages=total, warnings=warnings)
    finally:
        pdf.close()


# ---------------------------------------------------------------------------
# Preprocessing & quality
# ---------------------------------------------------------------------------

TARGET_MIN_WIDTH = 1800
MAX_WIDTH = 3500


def preprocess(img: Image.Image) -> Image.Image:
    """Grayscale, normalise size, stretch contrast. Kept deliberately simple
    and deterministic; Tesseract does its own binarisation."""
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    gray = img.convert("L")
    w, h = gray.size
    if w < TARGET_MIN_WIDTH:
        scale = TARGET_MIN_WIDTH / w
        gray = gray.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    elif w > MAX_WIDTH:
        scale = MAX_WIDTH / w
        gray = gray.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    return gray


def upscale_small(img: Image.Image, min_width: int = 900, target: int = TARGET_MIN_WIDTH) -> Image.Image:
    """Light preprocessing for neural OCR engines: keep colours/contrast, only
    enlarge images whose text would otherwise be a few pixels high."""
    if img.width >= min_width:
        return img
    scale = target / img.width
    return img.convert("RGB").resize((int(img.width * scale), int(img.height * scale)), Image.Resampling.LANCZOS)


@dataclass
class QualityReport:
    width: int
    height: int
    blur_score: float
    brightness: float
    warnings: list[str] = field(default_factory=list)


def assess_quality(img: Image.Image) -> QualityReport:
    gray = img.convert("L")
    w, h = gray.size
    # Laplacian variance on a normalised-size copy (resolution independent-ish)
    probe = gray.copy()
    probe.thumbnail((1200, 1200))
    a = np.asarray(probe, dtype=np.float32)
    lap = (
        -4 * a[1:-1, 1:-1] + a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:]
    )
    blur = float(lap.var()) if lap.size else 0.0
    brightness = float(a.mean()) if a.size else 0.0
    warnings: list[str] = []
    if min(w, h) < 500:
        warnings.append("Rezoluție mică: fotografiați documentul mai de aproape (minim ~1000 px pe latura mare).")
    if blur < 60:
        warnings.append("Imaginea pare neclară (blur). Refotografiați cu focalizare corectă.")
    if brightness < 60:
        warnings.append("Imaginea este foarte întunecată.")
    elif brightness > 245:
        warnings.append("Imaginea este supraexpusă sau are reflexii puternice.")
    return QualityReport(width=w, height=h, blur_score=round(blur, 1), brightness=round(brightness, 1), warnings=warnings)
