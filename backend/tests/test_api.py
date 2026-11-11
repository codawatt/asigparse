"""API tests: error handling of /extract and /confirm, plus the confirm flow.

A fake OCR engine is injected so these tests are deterministic and run
without Tesseract. Real-OCR end-to-end tests live in test_ocr_e2e.py.
"""

import dataclasses
import io

import pytest
from fastapi.testclient import TestClient

import app.main as main
from tests.helpers import CI_ROWS, TALON_ROWS, FakeEngine, make_doc, png_bytes

ID_IMG = png_bytes(1000, 500)  # aspect 0.5 -> identity OCR output
REG_IMG = png_bytes(1000, 700)  # aspect 0.7 -> registration OCR output
TEXT_IMG = png_bytes(1000, 300)  # aspect 0.3 -> unrelated text
BLANK_IMG = png_bytes(1000, 900)  # aspect 0.9 -> no text at all


@pytest.fixture
def client(monkeypatch):
    engine = FakeEngine(
        {
            0.5: make_doc(CI_ROWS),
            0.7: make_doc(TALON_ROWS),
            0.3: make_doc(["Lorem ipsum dolor sit amet", "consectetur adipiscing elit sed do eiusmod"]),
        }
    )
    monkeypatch.setattr(main, "engine", engine)
    return TestClient(main.app)


def files(identity=ID_IMG, registration=REG_IMG, id_name="ci.png", reg_name="talon.png"):
    out = {}
    if identity is not None:
        out["identity_image"] = (id_name, io.BytesIO(identity), "image/png")
    if registration is not None:
        out["registration_image"] = (reg_name, io.BytesIO(registration), "image/png")
    return out


def err(resp):
    return resp.json()["error"]["code"]


# --- errors ---------------------------------------------------------------------


def test_health(client):
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok" and body["ocr"]["available"]


def test_extract_without_files_is_400(client):
    r = client.post("/api/v1/extract")
    assert r.status_code == 400 and err(r) == "NO_FILES"


def test_unsupported_file_type_is_400(client):
    r = client.post("/api/v1/extract", files={"identity_image": ("x.txt", io.BytesIO(b"hello world"), "text/plain")})
    assert r.status_code == 400 and err(r) == "UNSUPPORTED_FILE_TYPE"
    assert r.json()["error"]["document"] == "identity"


def test_extension_is_not_trusted(client):
    # a text file renamed to .png is still rejected (magic-byte sniffing)
    r = client.post("/api/v1/extract", files={"identity_image": ("fake.png", io.BytesIO(b"GIF89a...."), "image/png")})
    assert r.status_code == 400 and err(r) == "UNSUPPORTED_FILE_TYPE"


def test_corrupt_png_is_400(client):
    data = ID_IMG[:40]
    r = client.post("/api/v1/extract", files={"identity_image": ("c.png", io.BytesIO(data), "image/png")})
    assert r.status_code == 400 and err(r) == "CORRUPT_FILE"


def test_corrupt_pdf_is_400(client):
    r = client.post(
        "/api/v1/extract", files={"registration_image": ("t.pdf", io.BytesIO(b"%PDF-1.4 garbage"), "application/pdf")}
    )
    assert r.status_code == 400 and err(r) == "CORRUPT_FILE"


def test_too_large_is_413(client, monkeypatch):
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, max_upload_bytes=1000))
    r = client.post("/api/v1/extract", files=files(registration=None))
    assert r.status_code == 413 and err(r) == "FILE_TOO_LARGE"


def test_empty_file_is_400(client):
    r = client.post("/api/v1/extract", files={"identity_image": ("e.png", io.BytesIO(b""), "image/png")})
    assert r.status_code == 400


def test_unreadable_image_is_422(client):
    r = client.post("/api/v1/extract", files=files(identity=BLANK_IMG, registration=None))
    assert r.status_code == 422 and err(r) == "UNREADABLE_DOCUMENT"


def test_unidentifiable_document_is_422(client):
    r = client.post("/api/v1/extract", files=files(identity=TEXT_IMG, registration=None))
    assert r.status_code == 422 and err(r) == "DOCUMENT_NOT_IDENTIFIED"


def test_two_identity_cards_is_422(client):
    r = client.post("/api/v1/extract", files=files(identity=ID_IMG, registration=ID_IMG))
    assert r.status_code == 422 and err(r) == "DUPLICATE_DOCUMENT_TYPE"


def test_ocr_unavailable_is_500(client, monkeypatch):
    monkeypatch.setattr(main, "engine", FakeEngine(available=False))
    r = client.post("/api/v1/extract", files=files())
    assert r.status_code == 500 and err(r) == "OCR_UNAVAILABLE"


def test_error_responses_do_not_echo_sensitive_input(client):
    r = client.post("/api/v1/confirm", json={"processing_id": 5, "corrected_person": "1800101400016"})
    assert r.status_code == 422 and err(r) == "INVALID_REQUEST"
    assert "1800101400016" not in r.text


# --- happy path + confirm ---------------------------------------------------------


def test_extract_contract_keys(client):
    r = client.post("/api/v1/extract", files=files())
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("schema_version", "processing_id", "status", "purpose", "person", "vehicle", "field_meta",
                "validation", "confirmed_by_operator"):
        assert key in body
    assert body["schema_version"] == "1.0.0"
    assert body["person"]["last_name"] == "IONESCU"
    assert body["vehicle"]["vin"] == "UU1TEST9X00000001"
    assert body["vehicle"]["legal_owner"] is None  # never copied from holder
    assert body["field_meta"]["vehicle.vin"]["source"] == "registration.E"
    assert body["confirmed_by_operator"] is False
    assert all(d["ocr_text"] is None for d in body["documents"])


def test_swapped_slots_are_reassigned(client):
    r = client.post("/api/v1/extract", files=files(identity=REG_IMG, registration=ID_IMG))
    assert r.status_code == 200
    body = r.json()
    assert body["person"]["last_name"] == "IONESCU"
    assert any(i["code"] == "DOCUMENT_SLOT_SWAPPED" for i in body["validation"]["issues"])


def test_single_document_allowed_with_missing_warning(client):
    r = client.post("/api/v1/extract", files=files(registration=None))
    assert r.status_code == 200
    issues = {(i["field"], i["code"]) for i in r.json()["validation"]["issues"]}
    assert ("documents.registration", "MISSING_DOCUMENT") in issues
    assert r.json()["status"] == "needs_review"


def _confirm_body(extracted, **overrides):
    body = {
        "processing_id": extracted["processing_id"],
        "corrected_person": extracted["person"],
        "corrected_vehicle": extracted["vehicle"],
    }
    body.update(overrides)
    return body


def test_confirm_records_operator_correction(client):
    extracted = client.post("/api/v1/extract", files=files()).json()
    body = _confirm_body(extracted)
    body["corrected_vehicle"] = dict(extracted["vehicle"], model="logan mcv", engine_cc="1461")
    r = client.post("/api/v1/confirm", json=body)
    assert r.status_code == 200, r.text
    payload = r.json()["payload"]
    assert r.json()["status"] == "confirmed" and payload["status"] == "confirmed"
    assert payload["confirmed_by_operator"] is True
    assert payload["vehicle"]["model"] == "LOGAN MCV"
    assert payload["vehicle"]["engine_cc"] == 1461
    assert payload["field_meta"]["vehicle.model"]["status"] == "corrected"
    assert payload["field_meta"]["vehicle.model"]["source"] == "operator"
    assert payload["field_meta"]["vehicle.make"]["status"] == "confirmed"


def test_confirm_blocks_on_errors_unless_acknowledged(client):
    extracted = client.post("/api/v1/extract", files=files()).json()
    body = _confirm_body(extracted)
    body["corrected_vehicle"] = dict(extracted["vehicle"], vin="UU1TEST9XO000000")  # 16 chars + O
    r = client.post("/api/v1/confirm", json=body)
    assert r.status_code == 422 and err(r) == "UNRESOLVED_ERRORS"
    assert any(i["field"] == "vehicle.vin" for i in r.json()["error"]["issues"])
    body["acknowledge_issues"] = True
    r = client.post("/api/v1/confirm", json=body)
    assert r.status_code == 200
    assert r.json()["payload"]["validation"]["passed"] is False


def test_confirm_can_exclude_cnp(client):
    extracted = client.post("/api/v1/extract", files=files()).json()
    r = client.post("/api/v1/confirm", json=_confirm_body(extracted, exclude_national_id=True))
    assert r.status_code == 200
    payload = r.json()["payload"]
    assert payload["person"]["national_id"] is None
    assert payload["field_meta"]["person.national_id"]["status"] == "excluded"


def test_confirm_unknown_processing_id_is_404(client):
    r = client.post("/api/v1/confirm", json={"processing_id": "nope", "corrected_person": {}, "corrected_vehicle": {}})
    assert r.status_code == 404 and err(r) == "PROCESSING_NOT_FOUND"


def test_samples_listing_and_whitelist(client):
    body = client.get("/api/v1/samples").json()
    assert body["synthetic"] is True and len(body["sets"]) >= 3
    assert client.get("/api/v1/samples/..%2Fapp%2Fmain.py").status_code == 404
    assert client.get("/api/v1/samples/manifest.json").status_code == 404


def test_validate_is_dry_run(client):
    extracted = client.post("/api/v1/extract", files=files()).json()
    body = _confirm_body(extracted)
    body["corrected_vehicle"] = dict(extracted["vehicle"], vin="UU1TEST9X0000000")
    r = client.post("/api/v1/validate", json=body)
    assert r.status_code == 200
    payload = r.json()
    assert payload["confirmed_by_operator"] is False
    assert any(i["code"] == "VIN_INVALID_LENGTH" for i in payload["validation"]["issues"])
    assert payload["field_meta"]["vehicle.vin"]["status"] == "corrected"
