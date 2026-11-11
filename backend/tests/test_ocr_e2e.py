"""End-to-end tests with the real Tesseract engine on the synthetic samples.

Skipped automatically when Tesseract (with ron/eng data) is not installed.
"""

import io
import json

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.config import settings
from app.ocr.tesseract import TesseractEngine

ENGINE = TesseractEngine(settings.tesseract_cmd, settings.ocr_languages)
pytestmark = pytest.mark.skipif(
    not ENGINE.is_available() or ENGINE.missing_languages(), reason="Tesseract with ron+eng not installed"
)

MANIFEST = json.loads((settings.samples_dir / "manifest.json").read_text(encoding="utf-8"))


def get(obj: dict, path: str):
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        cur = cur.get(part)
    return cur


@pytest.fixture(scope="module")
def client():
    main.engine = ENGINE
    return TestClient(main.app)


def upload(client, ident: str, reg: str):
    sd = settings.samples_dir
    return client.post(
        "/api/v1/extract",
        files={
            "identity_image": (ident, io.BytesIO((sd / ident).read_bytes()), "application/octet-stream"),
            "registration_image": (reg, io.BytesIO((sd / reg).read_bytes()), "application/octet-stream"),
        },
    )


@pytest.mark.parametrize("sample", MANIFEST["sets"], ids=[s["id"] for s in MANIFEST["sets"]])
def test_sample_extraction_matches_ground_truth(client, sample):
    r = upload(client, sample["identity"], sample["registration"])
    assert r.status_code == 200, r.text
    body = r.json()
    mismatches = {
        path: (get(body, path), expected)
        for path, expected in sample["expected"].items()
        if get(body, path) != expected
    }
    assert not mismatches, mismatches


def test_cei_sample_flags_cnp_and_missing_address(client):
    s = next(s for s in MANIFEST["sets"] if s["id"] == "cei_issues")
    body = upload(client, s["identity"], s["registration"]).json()
    codes = {(i["field"], i["code"]) for i in body["validation"]["issues"]}
    assert ("person.national_id", "CNP_CHECKSUM_INVALID") in codes
    assert ("person.address", "ADDRESS_NOT_ON_DOCUMENT") in codes
    assert body["person"]["address"] is None


def test_unreadable_real_image_is_422(client):
    data = (settings.samples_dir / MANIFEST["extra_files"]["unreadable"]).read_bytes()
    r = client.post("/api/v1/extract", files={"identity_image": ("b.png", io.BytesIO(data), "image/png")})
    assert r.status_code == 422
    assert r.json()["error"]["code"] in ("UNREADABLE_DOCUMENT", "DOCUMENT_NOT_IDENTIFIED")
