"""End-to-end tests with the REAL OCR engines on the synthetic samples.

Each available engine (OneOCR, Tesseract) is tested; an engine that is not
installed on this machine is skipped with the reason.
"""

import io
import json

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.config import settings
from app.ocr.registry import build_engines

ENGINES = build_engines(settings)
MANIFEST = json.loads((settings.samples_dir / "manifest.json").read_text(encoding="utf-8"))


def _ready(name):
    e = ENGINES[name]
    return e.is_available() and not e.missing_languages()


ENGINE_PARAMS = [
    pytest.param(name, marks=pytest.mark.skipif(not _ready(name), reason=f"{name} not available"))
    for name in ("oneocr", "tesseract")
]


def get(obj: dict, path: str):
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        cur = cur.get(part)
    return cur


@pytest.fixture(scope="module")
def client():
    return TestClient(main.app)


def upload(client, engine: str, ident: str, reg: str):
    sd = settings.samples_dir
    return client.post(
        f"/api/v1/extract?engine={engine}",
        files={
            "identity_image": (ident, io.BytesIO((sd / ident).read_bytes()), "application/octet-stream"),
            "registration_image": (reg, io.BytesIO((sd / reg).read_bytes()), "application/octet-stream"),
        },
    )


@pytest.mark.parametrize("engine", ENGINE_PARAMS)
@pytest.mark.parametrize("sample", MANIFEST["sets"], ids=[s["id"] for s in MANIFEST["sets"]])
def test_sample_extraction_matches_ground_truth(client, engine, sample):
    r = upload(client, engine, sample["identity"], sample["registration"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert {d["ocr_engine"] for d in body["documents"]} == {engine}
    mismatches = {
        path: (get(body, path), expected)
        for path, expected in sample["expected"].items()
        if get(body, path) != expected
    }
    assert not mismatches, mismatches


@pytest.mark.parametrize("engine", ENGINE_PARAMS)
def test_cei_sample_flags_cnp_and_missing_address(client, engine):
    s = next(s for s in MANIFEST["sets"] if s["id"] == "cei_issues")
    body = upload(client, engine, s["identity"], s["registration"]).json()
    codes = {(i["field"], i["code"]) for i in body["validation"]["issues"]}
    assert ("person.national_id", "CNP_CHECKSUM_INVALID") in codes
    assert ("person.address", "ADDRESS_NOT_ON_DOCUMENT") in codes
    assert body["person"]["address"] is None


@pytest.mark.parametrize("engine", ENGINE_PARAMS)
def test_unreadable_real_image_is_422(client, engine):
    data = (settings.samples_dir / MANIFEST["extra_files"]["unreadable"]).read_bytes()
    r = client.post(f"/api/v1/extract?engine={engine}", files={"identity_image": ("b.png", io.BytesIO(data), "image/png")})
    assert r.status_code == 422
    assert r.json()["error"]["code"] in ("UNREADABLE_DOCUMENT", "DOCUMENT_NOT_IDENTIFIED")


def test_health_lists_engines(client):
    body = client.get("/api/v1/health").json()
    assert set(body["engines"]) == {"oneocr", "tesseract"}
