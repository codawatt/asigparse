"""Orchestration: file -> OCR -> classification -> parsing -> payload; confirm."""

from __future__ import annotations

import copy
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import Settings
from .ocr.base import OcrDocument, OcrEngine
from .ocr.preprocess import FileRejectedError, assess_quality, decode_upload, preprocess, upscale_small
from .parsing.identity import IdentityExtraction, identity_score, parse_identity
from .parsing.registration import RegistrationExtraction, parse_registration, registration_score
from .pipeline import (
    ALL_FIELDS,
    Context,
    build_from_extraction,
    get_path,
    has_blocking,
    validate_payload,
)
from .schemas import (
    ConfirmRequest,
    DocumentInfo,
    ExtractionPayload,
    FieldMeta,
    IdentityDocument,
    Issue,
    Party,
    Person,
    QualityInfo,
    Vehicle,
)
from .store import ProcessingStore
from .validation import validators as v

log = logging.getLogger("asigparse.service")

MIN_TEXT_CHARS = 25
MIN_TYPE_SCORE = 4


class ProcessingError(Exception):
    def __init__(self, code: str, message: str, http_status: int, document: str | None = None, issues=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.document = document
        self.issues = issues


@dataclass
class OcrRun:
    slot: str
    doc: OcrDocument
    info: DocumentInfo
    identity_score: int
    registration_score: int


def run_ocr(slot: str, data: bytes, engine: OcrEngine, settings: Settings) -> OcrRun:
    try:
        decoded = decode_upload(data, max_pdf_pages=settings.max_pdf_pages, dpi=settings.pdf_render_dpi)
    except FileRejectedError as exc:
        raise ProcessingError(exc.code, exc.message, exc.http_status, document=slot) from exc

    doc = OcrDocument(engine=engine.name, pages=len(decoded.pages))
    qualities: list[QualityInfo] = []
    warnings = list(decoded.warnings)
    for page_no, page in enumerate(decoded.pages):
        q = assess_quality(page)
        qualities.append(QualityInfo(width=q.width, height=q.height, blur_score=q.blur_score, brightness=q.brightness))
        warnings.extend(q.warnings)
        mode = getattr(engine, "preprocessing", "full")
        prepared = preprocess(page) if mode == "full" else upscale_small(page) if mode == "upscale_small" else page
        lines, rotation = engine.recognize(prepared, page=page_no)
        doc.lines.extend(lines)
        doc.rotation_applied.append(rotation)

    mean_conf = doc.mean_confidence
    if doc.char_count < MIN_TEXT_CHARS:
        raise ProcessingError(
            "UNREADABLE_DOCUMENT",
            "Nu s-a putut citi text util din imagine. Refotografiați documentul: întreg în cadru, "
            "fără reflexii, bine iluminat și focalizat.",
            422,
            document=slot,
        )
    if mean_conf is not None and mean_conf < 0.6:
        warnings.append("Încrederea OCR medie este scăzută; rezultatele trebuie verificate atent sau refotografiați.")

    info = DocumentInfo(
        slot=slot,  # type: ignore[arg-type]
        file_type=decoded.mime,
        detected_type="UNKNOWN",
        pages_processed=len(decoded.pages),
        ocr_engine=engine.name,
        ocr_mean_confidence=round(mean_conf, 3) if mean_conf is not None else None,
        rotation_applied=doc.rotation_applied,
        quality=qualities,
        warnings=warnings,
    )
    return OcrRun(slot, doc, info, identity_score(doc), registration_score(doc))


def classify(run: OcrRun) -> str | None:
    if max(run.identity_score, run.registration_score) < MIN_TYPE_SCORE:
        return None
    return "identity" if run.identity_score >= run.registration_score else "registration"


def assign_documents(runs: list[OcrRun]) -> tuple[OcrRun | None, OcrRun | None, list[Issue]]:
    """Decide which upload is which document, by content (slots are a hint)."""
    issues: list[Issue] = []
    kinds: dict[str, OcrRun] = {}
    for run in runs:
        kind = classify(run)
        if kind is None:
            raise ProcessingError(
                "DOCUMENT_NOT_IDENTIFIED",
                "Documentul nu a putut fi identificat ca act de identitate sau certificat de înmatriculare "
                "românesc. Verificați fișierul sau calitatea fotografiei.",
                422,
                document=run.slot,
            )
        if kind in kinds:
            raise ProcessingError(
                "DUPLICATE_DOCUMENT_TYPE",
                "Ambele fișiere par a fi "
                + ("acte de identitate." if kind == "identity" else "certificate de înmatriculare.")
                + " Încărcați câte unul din fiecare.",
                422,
                document=run.slot,
            )
        kinds[kind] = run
        if kind != run.slot:
            issues.append(
                Issue(
                    field=f"documents.{run.slot}",
                    code="DOCUMENT_SLOT_SWAPPED",
                    severity="info",
                    message="Fișierul a fost încărcat în zona greșită; a fost atribuit automat după conținut.",
                )
            )
    return kinds.get("identity"), kinds.get("registration"), issues


def extract(
    files: dict[str, bytes],
    *,
    engine: OcrEngine,
    settings: Settings,
    store: ProcessingStore,
    include_ocr_text: bool = False,
) -> ExtractionPayload:
    started = time.perf_counter()
    processing_id = uuid.uuid4().hex[:12]
    runs = [run_ocr(slot, data, engine, settings) for slot, data in files.items()]
    id_run, reg_run, doc_issues = assign_documents(runs)

    ide: IdentityExtraction | None = parse_identity(id_run.doc) if id_run else None
    reg: RegistrationExtraction | None = parse_registration(reg_run.doc) if reg_run else None

    person, vehicle, meta, ctx = build_from_extraction(ide, reg)

    documents: list[DocumentInfo] = []
    for run, kind in ((id_run, "identity"), (reg_run, "registration")):
        if run is None:
            doc_issues.append(
                Issue(field=f"documents.{kind}", code="MISSING_DOCUMENT", severity="warning",
                      message=("Actul de identitate" if kind == "identity" else "Certificatul de înmatriculare")
                      + " nu a fost încărcat; câmpurile pot fi completate manual.")
            )
            continue
        run.info.slot = kind  # type: ignore[assignment]
        if kind == "identity" and ide is not None:
            run.info.detected_type = ide.document_type
            run.info.warnings.extend(ide.notes)
        if kind == "registration" and reg is not None:
            run.info.detected_type = "RO_REGISTRATION_CERTIFICATE"
            run.info.codes_found = reg.codes_found
            run.info.warnings.extend(reg.notes)
        if include_ocr_text:
            run.info.ocr_text = run.doc.text
        for w in run.info.warnings:
            doc_issues.append(Issue(field=f"documents.{kind}", code="DOCUMENT_QUALITY", severity="warning", message=w))
        documents.append(run.info)

    ctx.document_issues = doc_issues
    validation = validate_payload(person, vehicle, meta, ctx, threshold=settings.confidence_threshold)
    any_review = any(m.review_required for m in meta.values())
    status = "needs_review" if (any_review or not validation.passed) else "ready_for_confirmation"
    payload = ExtractionPayload(
        processing_id=processing_id,
        status=status,
        person=person,
        vehicle=vehicle,
        field_meta=meta,
        validation=validation,
        documents=documents,
        processing_time_ms=int((time.perf_counter() - started) * 1000),
    )
    stored = payload.model_copy(deep=True)
    for d in stored.documents:
        d.ocr_text = None  # never keep raw OCR text server-side
    store.put(stored, ctx)
    log.info(
        "extract id=%s docs=%s status=%s issues=%d ms=%d",
        processing_id,
        [d.detected_type for d in documents],
        status,
        len(validation.issues),
        payload.processing_time_ms,
    )
    return payload


# ---------------------------------------------------------------------------
# confirm
# ---------------------------------------------------------------------------


def _clean_upper(value: str | None) -> str | None:
    value = v.clean_spaces(value)
    return value.upper() if value else None


def _int_field(value, path: str, errors: list[Issue]) -> int | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    errors.append(Issue(field=path, code="NUMBER_INVALID", severity="error", message="Valoare numerică invalidă."))
    return None


def _party(p) -> Party | None:
    if p is None:
        return None
    name = v.normalize_name(p.name)
    address = v.fix_ro_diacritics(v.clean_spaces(p.address))
    if not name and not address:
        return None
    return Party(name=name, address=address)


def normalize_input(req: ConfirmRequest) -> tuple[Person, Vehicle, list[Issue]]:
    errors: list[Issue] = []
    p, cv = req.corrected_person, req.corrected_vehicle
    person = Person(
        first_name=v.normalize_name(p.first_name),
        last_name=v.normalize_name(p.last_name),
        national_id=None if req.exclude_national_id else v.normalize_cnp(p.national_id),
        identity_document=IdentityDocument(
            type=_clean_upper(p.identity_document.type),
            series=_clean_upper(p.identity_document.series),
            number=v.clean_spaces(p.identity_document.number),
            expiry_date=v.normalize_date(p.identity_document.expiry_date),
        ),
        address=v.fix_ro_diacritics(v.clean_spaces(p.address)),
    )
    vehicle = Vehicle(
        registration_number=v.normalize_plate(cv.registration_number),
        vin=v.normalize_vin(cv.vin),
        make=_clean_upper(cv.make),
        model=_clean_upper(cv.model),
        vehicle_type=_clean_upper(cv.vehicle_type),
        category=_clean_upper(cv.category),
        engine_cc=_int_field(cv.engine_cc, "vehicle.engine_cc", errors),
        power_kw=_int_field(cv.power_kw, "vehicle.power_kw", errors),
        fuel=v.normalize_fuel(cv.fuel),
        first_registration=v.normalize_date(cv.first_registration),
        max_permissible_mass_kg=_int_field(cv.max_permissible_mass_kg, "vehicle.max_permissible_mass_kg", errors),
        seats=_int_field(cv.seats, "vehicle.seats", errors),
        color=_clean_upper(cv.color),
        certificate_holder=_party(cv.certificate_holder),
        legal_owner=_party(cv.legal_owner),
    )
    return person, vehicle, errors


def confirm(req: ConfirmRequest, *, settings: Settings, store: ProcessingStore, dry_run: bool = False) -> ExtractionPayload:
    """Apply operator corrections. With dry_run=True only re-validates (used by
    the review screen) and never raises for unresolved errors."""
    stored = store.get(req.processing_id)
    if stored is None:
        raise ProcessingError(
            "PROCESSING_NOT_FOUND",
            "Sesiunea de procesare nu există sau a expirat (datele nu sunt păstrate permanent). "
            "Reîncărcați documentele.",
            404,
        )
    original = stored.payload
    person, vehicle, input_errors = normalize_input(req)

    meta: dict[str, FieldMeta] = {}
    for path, _, _ in ALL_FIELDS:
        old_meta = original.field_meta.get(path, FieldMeta(status="missing"))
        m = old_meta.model_copy(deep=True)
        new_value = get_path(person, vehicle, path)
        old_value = get_path(original.person, original.vehicle, path)
        if new_value != old_value and not (path == "person.national_id" and req.exclude_national_id):
            m.status = "corrected"
            m.source = "operator"
            m.confidence = None
            m.checks = []
            m.reason = "Valoare introdusă/corectată de operator."
        elif new_value not in (None, ""):
            m.status = "confirmed"
        meta[path] = m

    ctx: Context = copy.deepcopy(stored.context)
    ctx.confirmed = True
    ctx.national_id_excluded = req.exclude_national_id
    ctx.document_issues = [
        i.model_copy(update={"severity": "info"}) for i in stored.context.document_issues
    ]
    validation = validate_payload(person, vehicle, meta, ctx, threshold=settings.confidence_threshold)
    validation.issues = input_errors + validation.issues
    if input_errors:
        validation.passed = False

    if dry_run:
        return ExtractionPayload(
            processing_id=original.processing_id,
            status="needs_review" if not validation.passed else "ready_for_confirmation",
            person=person,
            vehicle=vehicle,
            field_meta=meta,
            validation=validation,
            documents=[d.model_copy(update={"ocr_text": None}) for d in original.documents],
            processing_time_ms=original.processing_time_ms,
        )

    if has_blocking(validation) and not req.acknowledge_issues:
        raise ProcessingError(
            "UNRESOLVED_ERRORS",
            "Există erori nerezolvate. Corectați-le sau confirmați explicit că exportați cu erori.",
            422,
            issues=[i for i in validation.issues if i.severity == "error"],
        )

    payload = ExtractionPayload(
        processing_id=original.processing_id,
        status="confirmed",
        person=person,
        vehicle=vehicle,
        field_meta=meta,
        validation=validation,
        confirmed_by_operator=True,
        confirmed_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        documents=[d.model_copy(update={"ocr_text": None}) for d in original.documents],
        processing_time_ms=original.processing_time_ms,
    )
    corrected = sum(1 for m in meta.values() if m.status == "corrected")
    log.info("confirm id=%s corrected_fields=%d issues=%d", req.processing_id, corrected, len(validation.issues))
    return payload
