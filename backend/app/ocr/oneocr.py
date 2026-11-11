"""OneOCR adapter: the local OCR engine shipped with Windows 11 Snipping Tool.

The engine is called through its native DLL with ctypes (interface documented
by community reverse engineering: github.com/b1tg/win11-oneocr and
github.com/AuroraWright/oneocr). It is undocumented and unsupported by
Microsoft and may break with a Snipping Tool update, so it is optional and
Tesseract remains the portable fallback.

The DLLs and model are NOT part of this repository. Copy them from your own
Snipping Tool installation with scripts/setup_oneocr.ps1.
"""

from __future__ import annotations

import ctypes
import logging
import math
import os
import sys
import threading
from ctypes import POINTER, Structure, byref, c_char, c_char_p, c_float, c_int32, c_int64, c_ubyte
from pathlib import Path

from PIL import Image

from .base import OcrLine, OcrUnavailableError, OcrWord

log = logging.getLogger("asigparse.ocr")

REQUIRED_FILES = ("oneocr.dll", "oneocr.onemodel", "onnxruntime.dll")
# Model decryption key published by the reverse-engineering projects above.
_MODEL_KEY = b'kj)TGtrK>f]b[Piow.gU+nC@s""""""4'


class _Image(Structure):
    _fields_ = [
        ("type", c_int32),
        ("width", c_int32),
        ("height", c_int32),
        ("_reserved", c_int32),
        ("step_size", c_int64),
        ("data_ptr", POINTER(c_ubyte)),
    ]


class _BBox(Structure):
    _fields_ = [(n, c_float) for n in ("x1", "y1", "x2", "y2", "x3", "y3", "x4", "y4")]


_i64p = POINTER(c_int64)
_SIGNATURES = [
    ("CreateOcrInitOptions", [_i64p], c_int64),
    ("OcrInitOptionsSetUseModelDelayLoad", [c_int64, c_char], c_int64),
    ("CreateOcrPipeline", [c_char_p, c_char_p, c_int64, _i64p], c_int64),
    ("CreateOcrProcessOptions", [_i64p], c_int64),
    ("OcrProcessOptionsSetMaxRecognitionLineCount", [c_int64, c_int64], c_int64),
    ("RunOcrPipeline", [c_int64, POINTER(_Image), c_int64, _i64p], c_int64),
    ("GetImageAngle", [c_int64, POINTER(c_float)], c_int64),
    ("GetOcrLineCount", [c_int64, _i64p], c_int64),
    ("GetOcrLine", [c_int64, c_int64, _i64p], c_int64),
    ("GetOcrLineWordCount", [c_int64, _i64p], c_int64),
    ("GetOcrWord", [c_int64, c_int64, _i64p], c_int64),
    ("GetOcrWordContent", [c_int64, POINTER(c_char_p)], c_int64),
    ("GetOcrWordBoundingBox", [c_int64, POINTER(POINTER(_BBox))], c_int64),
    ("GetOcrWordConfidence", [c_int64, POINTER(c_float)], c_int64),
    ("ReleaseOcrResult", [c_int64], None),
]


def default_oneocr_dir() -> Path | None:
    explicit = os.getenv("ASIGPARSE_ONEOCR_DIR")
    if explicit:
        return Path(explicit)
    vendored = Path(__file__).resolve().parents[2] / "vendor" / "oneocr"
    return vendored if vendored.exists() else None


class OneOcrEngine:
    name = "oneocr"
    # Benchmark (docs/OCR_BENCHMARK.md): full Tesseract-style preprocessing
    # hurts OneOCR on blur/JPEG, but upscaling tiny images helps. So: keep the
    # image as-is, only enlarge small ones.
    preprocessing = "upscale_small"

    MIN_SIDE = 50
    MAX_SIDE = 10000

    def __init__(self, directory: Path | None):
        self.directory = directory
        self._lock = threading.Lock()  # the native pipeline is not documented as thread-safe
        self._dll = None
        self._pipeline = None
        self._options = None
        self._error: str | None = None
        self._tried = False

    # -- lifecycle ------------------------------------------------------
    def _init(self) -> None:
        if self._tried:
            return
        self._tried = True
        if sys.platform != "win32":
            self._error = "OneOCR rulează doar pe Windows."
            return
        if self.directory is None:
            self._error = "Fișierele OneOCR nu sunt configurate (rulați scripts/setup_oneocr.ps1)."
            return
        missing = [f for f in REQUIRED_FILES if not (self.directory / f).is_file()]
        if missing:
            self._error = f"Lipsesc fișierele OneOCR: {', '.join(missing)} în {self.directory}."
            return
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            # so oneocr.dll resolves the onnxruntime.dll shipped next to it
            kernel32.AddDllDirectory.restype = ctypes.c_void_p
            kernel32.AddDllDirectory(str(self.directory))
            dll = ctypes.WinDLL(str(self.directory / "oneocr.dll"), winmode=0x00001000 | 0x00000100)
            for fname, args, res in _SIGNATURES:
                fn = getattr(dll, fname)
                fn.argtypes, fn.restype = args, res
            init = c_int64()
            self._check(dll.CreateOcrInitOptions(byref(init)), "CreateOcrInitOptions")
            self._check(dll.OcrInitOptionsSetUseModelDelayLoad(init, 0), "SetUseModelDelayLoad")
            pipeline = c_int64()
            self._check(
                dll.CreateOcrPipeline(
                    ctypes.create_string_buffer(str(self.directory / "oneocr.onemodel").encode()),
                    ctypes.create_string_buffer(_MODEL_KEY),
                    init,
                    byref(pipeline),
                ),
                "CreateOcrPipeline",
            )
            opts = c_int64()
            self._check(dll.CreateOcrProcessOptions(byref(opts)), "CreateOcrProcessOptions")
            self._check(dll.OcrProcessOptionsSetMaxRecognitionLineCount(opts, 1000), "SetMaxLineCount")
            self._dll, self._pipeline, self._options = dll, pipeline, opts
        except (OSError, AttributeError, RuntimeError) as exc:
            self._error = f"OneOCR nu a putut fi inițializat ({type(exc).__name__}: {exc})."
            log.warning("oneocr init failed: %s", type(exc).__name__)

    @staticmethod
    def _check(code: int, what: str) -> None:
        if code != 0:
            raise RuntimeError(f"{what} returned {code}")

    def is_available(self) -> bool:
        self._init()
        return self._dll is not None

    def unavailable_reason(self) -> str | None:
        self._init()
        return self._error

    def version(self) -> str | None:
        src = self.directory / "SOURCE.txt" if self.directory else None
        if src and src.exists():
            return src.read_text(encoding="utf-8-sig").strip()
        return "Snipping Tool OneOCR" if self.is_available() else None

    def missing_languages(self) -> list[str]:
        return []  # OneOCR's model is multilingual (Latin script incl. Romanian diacritics)

    # -- recognition ----------------------------------------------------
    def recognize(self, image: Image.Image, page: int = 0) -> tuple[list[OcrLine], int]:
        if not self.is_available():
            raise OcrUnavailableError(self._error or "OneOCR indisponibil.")
        w, h = image.size
        if min(w, h) < self.MIN_SIDE or max(w, h) > self.MAX_SIDE:
            scale = min(self.MAX_SIDE / max(w, h), 1.0) if max(w, h) > self.MAX_SIDE else self.MIN_SIDE / min(w, h)
            image = image.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
        rgba = image.convert("RGBA")
        r, g, b, a = rgba.split()
        data = Image.merge("RGBA", (b, g, r, a)).tobytes()  # engine expects BGRA
        buf = (c_ubyte * len(data)).from_buffer_copy(data)
        img = _Image(type=3, width=rgba.width, height=rgba.height, _reserved=0, step_size=rgba.width * 4, data_ptr=buf)

        with self._lock:
            dll = self._dll
            result = c_int64()
            if dll.RunOcrPipeline(self._pipeline, byref(img), self._options, byref(result)) != 0:
                raise OcrUnavailableError("OneOCR a eșuat la procesarea imaginii.")
            try:
                angle = c_float()
                text_angle = angle.value if dll.GetImageAngle(result, byref(angle)) == 0 else 0.0
                raw_lines = self._read_lines(dll, result)
            finally:
                dll.ReleaseOcrResult(result)
        return group_into_rows(raw_lines, text_angle, page), 0

    @staticmethod
    def _read_lines(dll, result) -> list[list[tuple[str, float, tuple[float, ...]]]]:
        count = c_int64()
        if dll.GetOcrLineCount(result, byref(count)) != 0:
            return []
        lines = []
        for li in range(count.value):
            line = c_int64()
            if dll.GetOcrLine(result, li, byref(line)) != 0:
                continue
            wc = c_int64()
            if dll.GetOcrLineWordCount(line, byref(wc)) != 0:
                continue
            words = []
            for wi in range(wc.value):
                word = c_int64()
                if dll.GetOcrWord(line, wi, byref(word)) != 0:
                    continue
                content = c_char_p()
                if dll.GetOcrWordContent(word, byref(content)) != 0 or not content.value:
                    continue
                bbox_p = POINTER(_BBox)()
                if dll.GetOcrWordBoundingBox(word, byref(bbox_p)) != 0 or not bbox_p:
                    continue
                bb = bbox_p.contents
                conf = c_float()
                confidence = conf.value if dll.GetOcrWordConfidence(word, byref(conf)) == 0 else 0.0
                words.append(
                    (content.value.decode("utf-8", errors="replace"), float(confidence),
                     (bb.x1, bb.y1, bb.x2, bb.y2, bb.x3, bb.y3, bb.x4, bb.y4))
                )
            if words:
                lines.append(words)
        return lines


def group_into_rows(raw_lines, angle_deg: float, page: int = 0) -> list[OcrLine]:
    """OneOCR returns one line per text *segment*; label/value parsers expect
    visual rows (like Tesseract --psm 6). Merge segments whose vertical centres
    overlap, measured in a frame de-rotated by the detected text angle so a
    slightly tilted photo still groups correctly."""
    theta = math.radians(angle_deg or 0.0)
    cos, sin = math.cos(theta), math.sin(theta)

    segs = []
    for words in raw_lines:
        ws: list[OcrWord] = []
        ys, hs = [], []
        for text, conf, q in words:
            xs, yq = q[0::2], q[1::2]
            left, top = min(xs), min(yq)
            width, height = max(xs) - left, max(yq) - top
            cx, cy = sum(xs) / 4, sum(yq) / 4
            ys.append(-sin * cx + cos * cy)  # de-rotated centre y
            hs.append(height)
            ws.append(OcrWord(text, max(0.0, min(1.0, conf)), (int(left), int(top), max(1, int(width)), max(1, int(height)))))
        segs.append((sum(ys) / len(ys), sorted(hs)[len(hs) // 2], ws))

    segs.sort(key=lambda s: s[0])
    rows: list[list] = []  # [centre_y, height, words]
    for cy, h, ws in segs:
        if rows and abs(cy - rows[-1][0]) <= 0.5 * max(h, rows[-1][1]):
            row = rows[-1]
            row[2].extend(ws)
            n = len(row[2])
            row[0] = (row[0] * (n - len(ws)) + cy * len(ws)) / n
            row[1] = max(row[1], h)
        else:
            rows.append([cy, h, list(ws)])
    return [OcrLine(words=sorted(r[2], key=lambda w: w.bbox[0]), page=page) for r in rows]
