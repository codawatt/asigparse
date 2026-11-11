"""Mapping of parser output into the JSON contract + validation rules.

`build_from_extraction` turns raw parser results into (person, vehicle,
field_meta). `validate_payload` is used both right after OCR and again after
the operator's corrections, so the rules are identical in both phases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .parsing.common import Extracted
from .parsing.identity import IdentityExtraction
from .parsing.registration import RegistrationExtraction
from .schemas import FieldMeta, IdentityDocument, Issue, Party, Person, Validation, Vehicle
from .validation import validators as v

# (path, label, critical)
PERSON_FIELDS: list[tuple[str, str, bool]] = [
    ("person.last_name", "Nume", True),
    ("person.first_name", "Prenume", True),
    ("person.national_id", "CNP", False),
    ("person.identity_document.series", "Serie act", False),
    ("person.identity_document.number", "Număr act", False),
    ("person.identity_document.expiry_date", "Data expirării", False),
    ("person.address", "Domiciliu", False),
]
VEHICLE_FIELDS: list[tuple[str, str, bool]] = [
    ("vehicle.registration_number", "Număr înmatriculare (A)", True),
    ("vehicle.vin", "VIN (E)", True),
    ("vehicle.make", "Marcă (D.1)", True),
    ("vehicle.model", "Model (D.3)", True),
    ("vehicle.engine_cc", "Cilindree (P.1)", True),
    ("vehicle.power_kw", "Putere (P.2)", False),
    ("vehicle.fuel", "Combustibil (P.3)", False),
    ("vehicle.first_registration", "Prima înmatriculare (B)", False),
    ("vehicle.vehicle_type", "Tip (D.2)", False),
    ("vehicle.category", "Categorie (J)", False),
    ("vehicle.max_permissible_mass_kg", "Masa maximă (F.1)", False),
    ("vehicle.seats", "Locuri (S.1)", False),
    ("vehicle.color", "Culoare (R)", False),
    ("vehicle.certificate_holder.name", "Titular (C.1)", False),
    ("vehicle.certificate_holder.address", "Adresă titular (C.1.3)", False),
    ("vehicle.legal_owner.name", "Proprietar (C.2)", False),
    ("vehicle.legal_owner.address", "Adresă proprietar (C.2.3)", False),
]
ALL_FIELDS = PERSON_FIELDS + VEHICLE_FIELDS
FIELD_LABELS = {p: label for p, label, _ in ALL_FIELDS}
# Fields whose absence is reported only as info (optional on many certificates)
SOFT_OPTIONAL = {
    "vehicle.vehicle_type", "vehicle.category", "vehicle.max_permissible_mass_kg", "vehicle.seats",
    "vehicle.color", "vehicle.certificate_holder.address",
}


@dataclass
class Context:
    """Facts about the source documents needed by validation rules."""

    identity_provided: bool = False
    registration_provided: bool = False
    identity_type: str | None = None
    address_label_present: bool = True
    owner_present: bool = False
    holder_partial: bool = False
    mrz_birth_date: date | None = None
    mrz_sex: str | None = None
    mrz_last_name: str | None = None
    mrz_first_name: str | None = None
    fuel_raw: str | None = None
    national_id_excluded: bool = False
    confirmed: bool = False
    document_issues: list[Issue] = field(default_factory=list)


# ---------------------------------------------------------------------------
# helpers for dotted paths
# ---------------------------------------------------------------------------


def get_path(person: Person, vehicle: Vehicle, path: str):
    root, *rest = path.split(".")
    obj = person if root == "person" else vehicle
    for part in rest:
        if obj is None:
            return None
        obj = getattr(obj, part)
    return obj


def _meta(ex: Extracted | None, *, default_source: str | None = None) -> FieldMeta:
    if ex is None:
        return FieldMeta(source=default_source, confidence=None, status="missing")
    return FieldMeta(
        source=ex.source or default_source,
        confidence=round(ex.confidence, 3) if ex.confidence is not None else None,
        status="extracted" if ex.value not in (None, "") else "missing",
        reason=ex.note,
        checks=list(ex.checks),
    )


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


def build_from_extraction(
    ide: IdentityExtraction | None, reg: RegistrationExtraction | None
) -> tuple[Person, Vehicle, dict[str, FieldMeta], Context]:
    meta: dict[str, FieldMeta] = {}
    ctx = Context(identity_provided=ide is not None, registration_provided=reg is not None)

    if ide is not None:
        expiry = v.normalize_date(ide.expiry_date.value) if ide.expiry_date.value else None
        person = Person(
            first_name=v.normalize_name(ide.first_name.value),
            last_name=v.normalize_name(ide.last_name.value),
            national_id=v.normalize_cnp(ide.national_id.value),
            identity_document=IdentityDocument(
                type=ide.document_type, series=ide.series.value, number=ide.number.value, expiry_date=expiry
            ),
            address=ide.address.value,
        )
        meta["person.first_name"] = _meta(ide.first_name)
        meta["person.last_name"] = _meta(ide.last_name)
        meta["person.national_id"] = _meta(ide.national_id)
        meta["person.identity_document.series"] = _meta(ide.series)
        meta["person.identity_document.number"] = _meta(ide.number)
        meta["person.identity_document.expiry_date"] = _meta(ide.expiry_date)
        meta["person.address"] = _meta(ide.address, default_source=None)
        if not ide.address_label_present:
            meta["person.address"].source = None
        ctx.identity_type = ide.document_type
        ctx.address_label_present = ide.address_label_present
        if ide.mrz:
            if ide.mrz.birth_date_valid:
                ctx.mrz_birth_date = ide.mrz.birth_date
                ctx.mrz_sex = ide.mrz.sex
            if ide.mrz.last_name and "<" not in ide.mrz.last_name:
                ctx.mrz_last_name = ide.mrz.last_name
                ctx.mrz_first_name = ide.mrz.first_name
    else:
        person = Person(identity_document=IdentityDocument())
        for path, _, _ in PERSON_FIELDS:
            meta[path] = FieldMeta(source=None, status="missing", reason="Actul de identitate nu a fost încărcat.")

    if reg is not None:
        first_reg = v.normalize_date(reg.first_registration.value) if reg.first_registration.value else None
        holder = (
            Party(name=reg.holder_name.value, address=reg.holder_address.value)
            if (reg.holder_name.value or reg.holder_address.value)
            else None
        )
        owner = (
            Party(name=reg.owner_name.value, address=reg.owner_address.value)
            if (reg.owner_present or reg.owner_address.value)
            else None
        )
        vehicle = Vehicle(
            registration_number=reg.registration_number.value,
            vin=reg.vin.value,
            make=reg.make.value,
            model=reg.model.value,
            vehicle_type=reg.vehicle_type.value,
            category=reg.category.value,
            engine_cc=reg.engine_cc.value,
            power_kw=reg.power_kw.value,
            fuel=reg.fuel.value,
            first_registration=first_reg,
            max_permissible_mass_kg=reg.max_mass_kg.value,
            seats=reg.seats.value,
            color=reg.color.value,
            certificate_holder=holder,
            legal_owner=owner,
        )
        pairs = {
            "vehicle.registration_number": reg.registration_number,
            "vehicle.vin": reg.vin,
            "vehicle.make": reg.make,
            "vehicle.model": reg.model,
            "vehicle.vehicle_type": reg.vehicle_type,
            "vehicle.category": reg.category,
            "vehicle.engine_cc": reg.engine_cc,
            "vehicle.power_kw": reg.power_kw,
            "vehicle.fuel": reg.fuel,
            "vehicle.first_registration": reg.first_registration,
            "vehicle.max_permissible_mass_kg": reg.max_mass_kg,
            "vehicle.seats": reg.seats,
            "vehicle.color": reg.color,
            "vehicle.certificate_holder.name": reg.holder_name,
            "vehicle.certificate_holder.address": reg.holder_address,
            "vehicle.legal_owner.name": reg.owner_name,
            "vehicle.legal_owner.address": reg.owner_address,
        }
        for path, ex in pairs.items():
            meta[path] = _meta(ex)
        ctx.owner_present = reg.owner_present
        ctx.holder_partial = reg.holder_partial
        ctx.fuel_raw = reg.fuel_raw
    else:
        vehicle = Vehicle()
        for path, _, _ in VEHICLE_FIELDS:
            meta[path] = FieldMeta(
                source=None, status="missing", reason="Certificatul de înmatriculare nu a fost încărcat."
            )
    return person, vehicle, meta, ctx


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def validate_payload(
    person: Person,
    vehicle: Vehicle,
    meta: dict[str, FieldMeta],
    ctx: Context,
    *,
    threshold: float,
    today: date | None = None,
) -> Validation:
    today = today or date.today()
    issues: list[Issue] = list(ctx.document_issues)

    def add(path: str, res_or_code, severity="error", message=None, suggestion=None):
        if isinstance(res_or_code, v.ValidationResult):
            if res_or_code.valid:
                return
            issues.append(
                Issue(field=path, code=res_or_code.code or "INVALID", severity=severity,
                      message=res_or_code.message, suggestion=res_or_code.suggestion)
            )
        else:
            issues.append(Issue(field=path, code=res_or_code, severity=severity, message=message, suggestion=suggestion))

    electric = vehicle.fuel == "ELECTRIC"

    # -- missing values ----------------------------------------------------
    for path, label, critical in ALL_FIELDS:
        value = get_path(person, vehicle, path)
        if value not in (None, ""):
            continue
        m = meta.setdefault(path, FieldMeta(status="missing"))
        if path == "person.national_id" and ctx.national_id_excluded:
            m.status = "excluded"
            m.review_required = False
            continue
        if path == "person.address" and ctx.identity_provided and not ctx.address_label_present:
            m.status = "not_on_document"
            if ctx.identity_type == "CEI":
                add(path, "ADDRESS_NOT_ON_DOCUMENT", "info",
                    "Cartea electronică de identitate nu afișează domiciliul. Completați separat doar dacă "
                    "fluxul de ofertare o cere.")
            else:
                add(path, "MISSING_VALUE", "warning", "Domiciliul nu a fost găsit pe imagine.")
            continue
        if path.startswith("vehicle.legal_owner"):
            if path == "vehicle.legal_owner.name":
                m.status = "not_on_document" if ctx.registration_provided else "missing"
                if ctx.registration_provided and not ctx.owner_present:
                    add(path, "OWNER_NOT_STATED", "info",
                        "Câmpul C.2 (proprietar) nu a fost găsit: lipsește de pe certificat sau nu a putut fi citit. "
                        "Proprietarul NU este presupus a fi titularul (C.1); completați dacă fluxul o cere.")
                    m.reason = m.reason or "C.2 absent; proprietarul nu se deduce din C.1."
            continue
        if path == "vehicle.engine_cc" and electric:
            m.status = "not_on_document"
            continue
        if path in SOFT_OPTIONAL:
            continue
        severity = "error" if critical else "warning"
        add(path, "MISSING_VALUE", severity, f"{label}: valoare lipsă.")

    # -- format / checksum -------------------------------------------------
    if person.national_id:
        add("person.national_id", v.validate_cnp(person.national_id))
        bd = v.cnp_birth_date(person.national_id)
        if bd and ctx.mrz_birth_date and bd != ctx.mrz_birth_date:
            add("person.national_id", "CNP_MRZ_MISMATCH", "warning",
                "Data nașterii din CNP diferă de cea din zona MRZ a actului.")
        if ctx.mrz_sex and person.national_id[0] in "123456":
            cnp_sex = "M" if int(person.national_id[0]) % 2 == 1 else "F"
            if cnp_sex != ctx.mrz_sex:
                add("person.national_id", "CNP_MRZ_MISMATCH", "warning",
                    "Sexul codificat în CNP diferă de cel din zona MRZ.")
    for path, label in (("person.last_name", "Nume"), ("person.first_name", "Prenume")):
        value = get_path(person, vehicle, path)
        if value:
            add(path, v.validate_name(value, label), "warning")
    mrz_names = {"person.last_name": ctx.mrz_last_name, "person.first_name": ctx.mrz_first_name}
    for path, mrz_value in mrz_names.items():
        value = get_path(person, vehicle, path)
        if value and mrz_value and not v.names_equivalent(value, mrz_value):
            add(path, "NAME_MRZ_MISMATCH", "warning",
                f"Valoarea diferă de cea din MRZ ({mrz_value}); verificați.")
    doc = person.identity_document
    if doc.series:
        add("person.identity_document.series", v.validate_id_series(doc.series), "warning")
    if doc.number:
        add("person.identity_document.number", v.validate_id_number(doc.number), "warning")
    if doc.expiry_date:
        res = v.validate_iso_date(doc.expiry_date)
        add("person.identity_document.expiry_date", res)
        if res.valid and v.parse_date(doc.expiry_date) < today:
            add("person.identity_document.expiry_date", "DOCUMENT_EXPIRED", "warning",
                "Actul de identitate pare expirat.")
    if doc.type in ("CEI", "CIS"):
        add("person.identity_document.type", "DOCUMENT_TYPE_LIMITED", "warning",
            f"Tip de act {doc.type}: suport limitat în MVP (layout-ul este optimizat pentru CI model 1997).")

    if vehicle.vin:
        add("vehicle.vin", v.validate_vin(vehicle.vin))
    if vehicle.registration_number:
        res = v.validate_plate(vehicle.registration_number)
        add("vehicle.registration_number", res, "error" if res.code == "PLATE_INVALID_CHARS" else "warning")
    if vehicle.first_registration:
        add("vehicle.first_registration", v.validate_iso_date(vehicle.first_registration, not_future=True, today=today))
    if vehicle.engine_cc is not None:
        add("vehicle.engine_cc", v.validate_range(vehicle.engine_cc, 50, 10000, "Cilindreea", "cm³"))
    if vehicle.power_kw is not None:
        add("vehicle.power_kw", v.validate_range(vehicle.power_kw, 3, 1200, "Puterea", "kW"))
    if vehicle.max_permissible_mass_kg is not None:
        add("vehicle.max_permissible_mass_kg",
            v.validate_range(vehicle.max_permissible_mass_kg, 100, 60000, "Masa maximă", "kg"), "warning")
    if vehicle.seats is not None:
        add("vehicle.seats", v.validate_range(vehicle.seats, 1, 100, "Numărul de locuri", ""), "warning")
    if vehicle.fuel and vehicle.fuel not in v.FUEL_VALUES:
        add("vehicle.fuel", "FUEL_UNRECOGNIZED", "warning", f"Combustibil necunoscut: {vehicle.fuel}.")
    elif vehicle.fuel == "OTHER":
        add("vehicle.fuel", "FUEL_UNRECOGNIZED", "warning",
            f"Valoarea P.3 nu a putut fi mapată ({ctx.fuel_raw or 'necunoscut'}); selectați manual.")
    if vehicle.engine_cc and electric:
        add("vehicle.engine_cc", "ELECTRIC_WITH_ENGINE_CC", "info",
            "Vehicul electric cu cilindree declarată; verificați combustibilul (poate fi hibrid).")

    # -- cross-document ----------------------------------------------------
    holder_name = vehicle.certificate_holder.name if vehicle.certificate_holder else None
    person_name = " ".join(x for x in (person.last_name, person.first_name) if x) or None
    holder_tokens = set(v.strip_diacritics(holder_name or "").upper().replace("-", " ").split())
    person_tokens = set(v.strip_diacritics(person_name or "").upper().replace("-", " ").split())
    if ctx.holder_partial and not ctx.confirmed:
        add("vehicle.certificate_holder.name", "HOLDER_NAME_INCOMPLETE", "warning",
            "Numele titularului pare citit parțial (lipsește C.1.1 sau C.1.2). Verificați pe certificat.")
    elif holder_tokens and person_tokens and holder_tokens < person_tokens:
        add("vehicle.certificate_holder.name", "HOLDER_NAME_INCOMPLETE", "warning",
            "Titularul conține doar o parte din numele persoanei din CI; posibil citit parțial. Verificați.")
    if holder_name and person_name and not v.names_equivalent(holder_name, person_name):
        add("vehicle.certificate_holder.name", "HOLDER_DIFFERS_FROM_PERSON", "info",
            "Titularul certificatului (C.1) diferă de persoana din actul de identitate. Stabiliți cine este "
            "asiguratul/contractantul; datele NU au fost unificate.")

    # -- confidence / review flags -----------------------------------------
    issue_fields = {i.field for i in issues if i.severity in ("error", "warning")}
    for path, m in meta.items():
        value = get_path(person, vehicle, path)
        if ctx.confirmed:
            m.review_required = False
            continue
        low = m.confidence is not None and m.confidence < threshold and value not in (None, "")
        if low:
            protected = bool(m.checks)
            add(path, "LOW_CONFIDENCE", "info" if protected else "warning",
                f"Încredere OCR {m.confidence:.0%} sub pragul de {threshold:.0%}"
                + ("; valoarea trece însă verificarea de control." if protected else "; verificați valoarea."))
        missing_relevant = value in (None, "") and m.status in ("missing", "not_on_document") and path not in SOFT_OPTIONAL
        if path == "person.national_id" and ctx.national_id_excluded:
            missing_relevant = False
        m.review_required = bool(low or path in issue_fields or missing_relevant)
        if m.review_required and m.status == "extracted":
            m.status = "needs_review"

    passed = not any(i.severity in ("error", "warning") for i in issues)
    return Validation(passed=passed, issues=issues)


def has_blocking(validation: Validation) -> bool:
    return any(i.severity == "error" for i in validation.issues)
