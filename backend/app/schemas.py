"""Pydantic models for the AsigParse JSON contract (schema_version 1.0.0).

Keys from docs/AsigParse_exemplu_payload.json are kept verbatim. Additional
keys (expiry_date, technical fields, documents, field_meta.status/reason ...)
are additive extensions; absent values are always `null`, never invented.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0.0"

Severity = Literal["error", "warning", "info"]
FieldStatus = Literal["extracted", "missing", "needs_review", "not_on_document", "corrected", "confirmed", "excluded"]


class IdentityDocument(BaseModel):
    type: str | None = None  # CI_1997 | CEI | CIS
    series: str | None = None
    number: str | None = None
    expiry_date: str | None = None  # YYYY-MM-DD


class Person(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    national_id: str | None = None  # CNP - sensitive, never logged
    identity_document: IdentityDocument = Field(default_factory=IdentityDocument)
    address: str | None = None


class Party(BaseModel):
    name: str | None = None
    address: str | None = None


class Vehicle(BaseModel):
    registration_number: str | None = None  # A
    vin: str | None = None  # E
    make: str | None = None  # D.1
    model: str | None = None  # D.3
    vehicle_type: str | None = None  # D.2
    category: str | None = None  # J
    engine_cc: int | None = None  # P.1 (cm3)
    power_kw: int | None = None  # P.2 (kW)
    fuel: str | None = None  # P.3, normalised enum
    first_registration: str | None = None  # B, YYYY-MM-DD
    max_permissible_mass_kg: int | None = None  # F.1
    seats: int | None = None  # S.1
    color: str | None = None  # R
    certificate_holder: Party | None = None  # C.1
    legal_owner: Party | None = None  # C.2 - never copied from C.1


class FieldMeta(BaseModel):
    source: str | None = None
    confidence: float | None = None
    review_required: bool = False
    status: FieldStatus = "extracted"
    reason: str | None = None
    checks: list[str] = Field(default_factory=list)


class Issue(BaseModel):
    field: str
    code: str
    severity: Severity = "warning"
    message: str | None = None
    suggestion: str | None = None


class Validation(BaseModel):
    passed: bool
    issues: list[Issue] = Field(default_factory=list)


class QualityInfo(BaseModel):
    width: int
    height: int
    blur_score: float
    brightness: float


class DocumentInfo(BaseModel):
    slot: Literal["identity", "registration"]
    filename_provided: bool = True
    file_type: str
    detected_type: str
    pages_processed: int
    ocr_engine: str
    ocr_mean_confidence: float | None
    rotation_applied: list[int] = Field(default_factory=list)
    quality: list[QualityInfo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    codes_found: list[str] | None = None
    ocr_text: str | None = None  # only when explicitly requested; never logged


class ExtractionPayload(BaseModel):
    schema_version: str = SCHEMA_VERSION
    processing_id: str
    status: Literal["needs_review", "ready_for_confirmation", "confirmed"]
    purpose: str = "insurance_quote_prefill"
    person: Person
    vehicle: Vehicle
    field_meta: dict[str, FieldMeta]
    validation: Validation
    confirmed_by_operator: bool = False
    confirmed_at: str | None = None
    documents: list[DocumentInfo] = Field(default_factory=list)
    processing_time_ms: int | None = None
    disclaimer: str = (
        "Date extrase automat prin OCR și verificate de operator. Operațiunea nu dovedește identitatea "
        "persoanei și nu verifică oficial datele."
    )


# --- confirm ----------------------------------------------------------------


class PartyInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str | None = None
    address: str | None = None


class IdentityDocumentInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str | None = None
    series: str | None = None
    number: str | None = None
    expiry_date: str | None = None


class PersonInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    first_name: str | None = None
    last_name: str | None = None
    national_id: str | None = None
    identity_document: IdentityDocumentInput = Field(default_factory=IdentityDocumentInput)
    address: str | None = None


class VehicleInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    registration_number: str | None = None
    vin: str | None = None
    make: str | None = None
    model: str | None = None
    vehicle_type: str | None = None
    category: str | None = None
    engine_cc: int | str | None = None
    power_kw: int | str | None = None
    fuel: str | None = None
    first_registration: str | None = None
    max_permissible_mass_kg: int | str | None = None
    seats: int | str | None = None
    color: str | None = None
    certificate_holder: PartyInput | None = None
    legal_owner: PartyInput | None = None


class ConfirmRequest(BaseModel):
    processing_id: str
    corrected_person: PersonInput
    corrected_vehicle: VehicleInput
    acknowledge_issues: bool = False
    exclude_national_id: bool = False


class ConfirmResponse(BaseModel):
    status: Literal["confirmed"] = "confirmed"
    payload: ExtractionPayload


class ErrorBody(BaseModel):
    code: str
    message: str
    document: str | None = None
    issues: list[Issue] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
