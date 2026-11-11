"""FastAPI application: AsigParse OCR MVP."""

from __future__ import annotations

import logging
import re

from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from .config import settings
from .ocr.base import OcrUnavailableError
from .ocr.tesseract import TesseractEngine
from .samples import SAMPLE_SETS, sample_path
from .schemas import ConfirmRequest, ConfirmResponse, ErrorResponse, ExtractionPayload
from .service import ProcessingError, confirm, extract
from .store import ProcessingStore


class RedactingFilter(logging.Filter):
    """Defence in depth: mask CNP-like and VIN-like tokens in any log line."""

    CNP = re.compile(r"(?<!\d)[1-9]\d{12}(?!\d)")
    VIN = re.compile(r"(?<![A-Z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-Z0-9])")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        masked = self.VIN.sub("[VIN]", self.CNP.sub("[CNP]", msg))
        if masked != msg:
            record.msg, record.args = masked, ()
        return True


def _configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger("asigparse")
    root.setLevel(logging.INFO)
    root.handlers = [handler]
    root.propagate = False


_configure_logging()
log = logging.getLogger("asigparse.api")

app = FastAPI(
    title="AsigParse OCR API",
    version="1.0.0",
    description="Extracție OCR + validare pentru CI românească și certificat de înmatriculare (MVP demonstrativ).",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

engine = TesseractEngine(settings.tesseract_cmd, settings.ocr_languages)
store = ProcessingStore(settings.processing_ttl_seconds)


def error_response(status: int, code: str, message: str, document: str | None = None, issues=None) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "document": document}}
    if issues:
        body["error"]["issues"] = [i.model_dump() for i in issues]
    return JSONResponse(status_code=status, content=body)


@app.exception_handler(ProcessingError)
async def _processing_error(_: Request, exc: ProcessingError):
    return error_response(exc.http_status, exc.code, exc.message, exc.document, exc.issues)


@app.exception_handler(OcrUnavailableError)
async def _ocr_unavailable(_: Request, exc: OcrUnavailableError):
    return error_response(500, "OCR_UNAVAILABLE", f"{exc} Consultați README pentru instalarea Tesseract.")


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError):
    # Do not echo request bodies (may contain CNP) back or into logs.
    fields = sorted({".".join(str(p) for p in e.get("loc", [])) for e in exc.errors()})
    return error_response(422, "INVALID_REQUEST", "Cerere invalidă: " + ", ".join(fields))


@app.exception_handler(Exception)
async def _unexpected(_: Request, exc: Exception):
    log.error("unexpected error type=%s", type(exc).__name__)
    return error_response(500, "PROCESSING_ERROR", "Eroare internă la procesare. Încercați din nou.")


# ---------------------------------------------------------------------------


@app.get("/api/v1/health")
def health():
    available = engine.is_available()
    return {
        "status": "ok",
        "ocr": {
            "engine": engine.name,
            "available": available,
            "version": engine.version() if available else None,
            "languages": settings.ocr_languages,
            "missing_languages": engine.missing_languages(),
        },
        "confidence_threshold": settings.confidence_threshold,
        "max_upload_mb": settings.max_upload_bytes // (1024 * 1024),
    }


async def _read_limited(upload: UploadFile, slot: str) -> bytes:
    data = await upload.read(settings.max_upload_bytes + 1)
    await upload.close()
    if len(data) > settings.max_upload_bytes:
        raise ProcessingError(
            "FILE_TOO_LARGE",
            f"Fișierul depășește limita de {settings.max_upload_bytes // (1024 * 1024)} MB.",
            413,
            document=slot,
        )
    if not data:
        raise ProcessingError("EMPTY_FILE", "Fișierul este gol.", 400, document=slot)
    return data


@app.post(
    "/api/v1/extract",
    response_model=ExtractionPayload,
    response_model_exclude_none=False,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 422: {"model": ErrorResponse},
               500: {"model": ErrorResponse}},
)
async def extract_endpoint(
    identity_image: UploadFile | None = File(default=None),
    registration_image: UploadFile | None = File(default=None),
    include_ocr_text: bool = Query(default=False, description="Returnează textul OCR brut (doar în răspuns, nelogat)."),
):
    files: dict[str, bytes] = {}
    if identity_image is not None and identity_image.filename:
        files["identity"] = await _read_limited(identity_image, "identity")
    if registration_image is not None and registration_image.filename:
        files["registration"] = await _read_limited(registration_image, "registration")
    if not files:
        raise ProcessingError(
            "NO_FILES", "Încărcați cel puțin un document (identity_image și/sau registration_image).", 400
        )
    if not engine.is_available():
        raise OcrUnavailableError("Tesseract nu este instalat sau nu poate fi executat.")
    return await run_in_threadpool(
        extract, files, engine=engine, settings=settings, store=store, include_ocr_text=include_ocr_text
    )


@app.post(
    "/api/v1/confirm",
    response_model=ConfirmResponse,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def confirm_endpoint(req: ConfirmRequest):
    payload = confirm(req, settings=settings, store=store)
    return ConfirmResponse(payload=payload)


@app.post("/api/v1/validate", response_model=ExtractionPayload, responses={404: {"model": ErrorResponse}})
def validate_endpoint(req: ConfirmRequest):
    """Re-validate operator edits without confirming (no state change)."""
    return confirm(req, settings=settings, store=store, dry_run=True)


@app.delete("/api/v1/processing/{processing_id}")
def discard(processing_id: str):
    return {"deleted": store.delete(processing_id)}


@app.get("/api/v1/schema")
def schema():
    return ExtractionPayload.model_json_schema()


@app.get("/api/v1/samples")
def list_samples():
    return {"synthetic": True, "sets": SAMPLE_SETS}


@app.get("/api/v1/samples/{filename}")
def get_sample(filename: str):
    path = sample_path(filename)
    if path is None:
        return error_response(404, "SAMPLE_NOT_FOUND", "Fișier demo inexistent. Rulați scripts/generate_samples.py.")
    return FileResponse(path)
