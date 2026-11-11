"""Benchmark OCR engines on REAL documents described by a local ground-truth file.

The documents and the ground truth contain personal data and live in a
gitignored folder (default: docs/acte/). This script writes:

  * an ANONYMISED markdown report (no field values, no file names) that is
    safe to commit, e.g. docs/OCR_BENCHMARK_REAL.md
  * a detailed per-field log WITH values into backend/benchmarks/real/
    (gitignored) for local debugging only

Ground-truth format (docs/acte/ground_truth.json):
  {"documents": [{"id": "CEI-1", "file": "ci/x.pdf", "kind": "identity",
                  "doc": "CEI", "source": "scan PDF", "expected": {"person.last_name": "...", ...}}]}

Each document is also re-run under simulated capture conditions (phone photo,
blur, glare, rotation ...) applied to every page.

Usage (from backend/):
  python scripts/benchmark_real.py --out ../docs/OCR_BENCHMARK_REAL.md
"""

from __future__ import annotations

import argparse
import io
import json
import re
import statistics
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_ocr import blur, dark_low_contrast, glare, jpeg_heavy, perspective, phone_photo  # noqa: E402

from app.config import settings  # noqa: E402
from app.ocr.preprocess import decode_upload  # noqa: E402
from app.ocr.registry import build_engines  # noqa: E402
from app.service import ProcessingError, extract  # noqa: E402
from app.store import ProcessingStore  # noqa: E402

CRITICAL = {
    "person.last_name", "person.first_name", "person.national_id", "vehicle.registration_number", "vehicle.vin",
    "vehicle.make", "vehicle.model", "vehicle.engine_cc",
}


def low_res_50(img):
    return img.resize((max(60, img.width // 2), max(60, img.height // 2)), Image.Resampling.BILINEAR), None


def rotated_90(img):
    return img.convert("RGB").rotate(90, expand=True), 90


CONDITIONS = {
    "original": None,
    "phone_photo": phone_photo,
    "perspective": perspective,
    "glare": glare,
    "dark_low_contrast": dark_low_contrast,
    "blur_2px": blur,
    "jpeg_q18": jpeg_heavy,
    "low_res_50pct": low_res_50,
    "rotated_90": rotated_90,
}
CONDITION_NOTES = {
    "original": "fișierul exact cum a fost primit",
    "phone_photo": "fundal, rotire 3,5°, blur 1,3 px, zgomot, scalare 65%, JPEG q70",
    "perspective": "distorsiune trapez (~6%)",
    "glare": "reflexie luminoasă eliptică",
    "dark_low_contrast": "contrast ×0,45, luminozitate ×0,5",
    "blur_2px": "blur gaussian 2,2 px",
    "jpeg_q18": "scalare 60%, JPEG calitate 18",
    "low_res_50pct": "rezoluție înjumătățită",
    "rotated_90": "document rotit 90° (fotografiat lateral)",
}


def render(path: Path, condition: str) -> bytes:
    data = path.read_bytes()
    fn = CONDITIONS[condition]
    if fn is None:
        return data
    pages = decode_upload(data, max_pdf_pages=settings.max_pdf_pages, dpi=200).pages
    out = []
    for p in pages:
        img, q = fn(p.convert("RGB"))
        if q:  # emulate the JPEG round-trip of that condition
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=q)
            img = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
        out.append(img.convert("RGB"))
    buf = io.BytesIO()
    if len(out) == 1:
        out[0].save(buf, format="PNG")
    else:  # keep multi-page documents multi-page
        out[0].save(buf, format="PDF", save_all=True, append_images=out[1:], resolution=200)
    return buf.getvalue()


# ---------------------------------------------------------------------------


def get(obj: dict, path: str):
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        cur = cur.get(part)
    return cur


def lenient(v) -> str | None:
    """Case-, diacritics-, spacing- and punctuation-insensitive form."""
    if v is None:
        return None
    s = unicodedata.normalize("NFKD", str(v))
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    return re.sub(r"[^A-Z0-9]", "", s)


@dataclass
class Tally:
    strict: int = 0
    lenient_ok: int = 0
    flagged: int = 0  # wrong (lenient) but flagged for review
    silent: int = 0  # wrong (lenient) and NOT flagged
    total: int = 0
    crit_ok: int = 0
    crit_total: int = 0
    rejected: int = 0
    docs: int = 0
    ms: list[float] = field(default_factory=list)

    def add(self, o: "Tally"):
        for k in ("strict", "lenient_ok", "flagged", "silent", "total", "crit_ok", "crit_total", "rejected", "docs"):
            setattr(self, k, getattr(self, k) + getattr(o, k))
        self.ms += o.ms


FIELD_STATS: dict[str, dict[str, list[int]]] = {}  # engine -> field -> [ok, total]


def run_doc(engine, doc: dict, base: Path, condition: str, log: list[str]) -> Tally:
    t = Tally(docs=1)
    data = render(base / doc["file"], condition)
    started = time.perf_counter()
    try:
        body = extract({doc["kind"]: data}, engine=engine, settings=settings, store=ProcessingStore(60)).model_dump()
    except ProcessingError as exc:
        t.rejected = 1
        for path in doc["expected"]:
            FIELD_STATS.setdefault(engine.name, {}).setdefault(path, [0, 0])[1] += 1
            t.total += 1
            t.flagged += 1
            t.crit_total += path in CRITICAL
        log.append(f"{doc['id']} {condition} {engine.name}: REJECTED {exc.code}")
        return t
    t.ms.append((time.perf_counter() - started) * 1000)
    flagged_fields = {i["field"] for i in body["validation"]["issues"] if i["severity"] in ("error", "warning")}
    for path, exp in doc["expected"].items():
        got = get(body, path)
        meta = body["field_meta"].get(path) or {}
        t.total += 1
        fs = FIELD_STATS.setdefault(engine.name, {}).setdefault(path, [0, 0])
        fs[1] += 1
        fs[0] += lenient(got) == lenient(exp)
        crit = path in CRITICAL
        t.crit_total += crit
        if got == exp:
            t.strict += 1
        if lenient(got) == lenient(exp):
            t.lenient_ok += 1
            t.crit_ok += crit
            if got != exp:
                log.append(f"{doc['id']} {condition} {engine.name}: {path} ~ok got {got!r} exp {exp!r}")
            continue
        if meta.get("review_required") or path in flagged_fields or got is None:
            t.flagged += 1
            log.append(f"{doc['id']} {condition} {engine.name}: {path} FLAGGED got {got!r} exp {exp!r}")
        else:
            t.silent += 1
            log.append(f"{doc['id']} {condition} {engine.name}: {path} SILENT got {got!r} exp {exp!r}")
    return t


def pct(a, b):
    return f"{100 * a / b:.1f}%" if b else "–"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth", type=Path, default=ROOT.parent / "docs" / "acte" / "ground_truth.json")
    ap.add_argument("--engines", nargs="*", default=None)
    ap.add_argument("--conditions", nargs="*", default=list(CONDITIONS))
    ap.add_argument("--out", type=Path, default=None, help="anonymised markdown report")
    ap.add_argument("--label", default="", help="free text shown in the report header (e.g. parser version)")
    args = ap.parse_args()

    truth = json.loads(args.truth.read_text(encoding="utf-8"))
    base = args.truth.parent
    all_engines = build_engines(settings)
    names = args.engines or [n for n, e in all_engines.items() if e.is_available()]
    log: list[str] = []
    res: dict[str, dict[str, dict[str, Tally]]] = {}  # engine -> condition -> doc id -> tally
    for name in names:
        eng = all_engines[name]
        res[name] = {}
        for cond in args.conditions:
            res[name][cond] = {}
            for doc in truth["documents"]:
                res[name][cond][doc["id"]] = run_doc(eng, doc, base, cond, log)
            tot = Tally()
            for v in res[name][cond].values():
                tot.add(v)
            print(f"{name:10s} {cond:18s} lenient {pct(tot.lenient_ok, tot.total):>6s} strict {pct(tot.strict, tot.total):>6s} "
                  f"silent {tot.silent:2d} rejected {tot.rejected} ms/doc {statistics.mean(tot.ms) if tot.ms else 0:6.0f}",
                  flush=True)

    details = ROOT / "benchmarks" / "real"
    details.mkdir(parents=True, exist_ok=True)
    (details / "details.log").write_text("\n".join(log) + "\n", encoding="utf-8")
    if args.out:
        args.out.write_text(report(res, truth, all_engines, args), encoding="utf-8")
        print(f"report written to {args.out}; detailed log (with values, gitignored) in {details / 'details.log'}")


def report(res, truth, all_engines, args) -> str:
    docs = truth["documents"]
    n_fields = sum(len(d["expected"]) for d in docs)
    engines = list(res)
    L = [
        "# Benchmark OCR pe documente reale: OneOCR vs Tesseract",
        "",
        f"_Generat de `backend/scripts/benchmark_real.py` la {date.today().isoformat()}. {args.label}_",
        "",
        "Raport **anonimizat**: nu conține valori, nume de fișiere sau date personale. Documentele și valorile de "
        "referință sunt doar local, în `docs/acte/` (exclus din git).",
        "",
        "## Set de date",
        "",
        "| ID | Document | Sursă | Câmpuri verificate |",
        "|---|---|---|---|",
    ]
    L += [f"| {d['id']} | {d['doc']} | {d['source']} | {len(d['expected'])} |" for d in docs]
    L += [
        "",
        f"{len(docs)} fișiere, {n_fields} câmpuri de referință per condiție, {len(args.conditions)} condiții "
        f"→ {n_fields * len(args.conditions)} verificări per motor. Fiecare rulare trece prin tot fluxul "
        "(decodare → OCR → parsare → validare).",
        "",
        "- **corect (strict)** = identic cu valoarea de pe act (inclusiv diacritice);",
        "- **corect (normalizat)** = identic ignorând diacriticele, majusculele, spațiile și punctuația;",
        "- **semnalat** = greșit/lipsă, dar marcat pentru verificare (operatorul e avertizat);",
        "- **tăcut** = greșit și **nesemnalat**; cazul periculos.",
        "",
        "## Rezumat (toate condițiile)",
        "",
        "| Motor | Corect (normalizat) | Corect (strict) | Câmpuri critice corecte | Semnalate | **Tăcute** | Documente respinse | ms / document |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for e in engines:
        t = Tally()
        for c in res[e].values():
            for v in c.values():
                t.add(v)
        L.append(
            f"| {e} | {pct(t.lenient_ok, t.total)} | {pct(t.strict, t.total)} | {pct(t.crit_ok, t.crit_total)} | "
            f"{t.flagged} | **{t.silent}** | {t.rejected}/{t.docs} | {statistics.mean(t.ms):.0f} |"
            if t.ms else f"| {e} | – | – | – | {t.flagged} | {t.silent} | {t.rejected}/{t.docs} | – |"
        )
    L += ["", "## Pe condiție de captură (corect normalizat · tăcute · respinse)", "",
          "| Condiție | " + " | ".join(engines) + " |", "|---|" + "---|" * len(engines)]
    for c in args.conditions:
        cells = []
        for e in engines:
            t = Tally()
            for v in res[e][c].values():
                t.add(v)
            cells.append(f"{pct(t.lenient_ok, t.total)} · {t.silent} · {t.rejected}")
        L.append(f"| `{c}` | " + " | ".join(cells) + " |")
    L += ["", "Condiții:", ""] + [f"- `{c}`: {CONDITION_NOTES[c]}" for c in args.conditions]
    L += ["", "## Pe document, fișierul original (corect normalizat · ms)", "",
          "| ID | Sursă | " + " | ".join(engines) + " |", "|---|---|" + "---|" * len(engines)]
    for d in docs:
        cells = []
        for e in engines:
            t = res[e].get("original", {}).get(d["id"])
            if t is None:
                cells.append("–")
            elif t.rejected:
                cells.append("respins")
            else:
                cells.append(f"{pct(t.lenient_ok, t.total)} · {t.ms[0]:.0f} ms")
        L.append(f"| {d['id']} | {d['source']} | " + " | ".join(cells) + " |")
    L += ["", "## Pe document, media tuturor condițiilor (corect normalizat)", "",
          "| ID | " + " | ".join(engines) + " |", "|---|" + "---|" * len(engines)]
    for d in docs:
        cells = []
        for e in engines:
            t = Tally()
            for c in res[e].values():
                t.add(c[d["id"]])
            cells.append(f"{pct(t.lenient_ok, t.total)} ({t.rejected} resp.)" if t.rejected else pct(t.lenient_ok, t.total))
        L.append(f"| {d['id']} | " + " | ".join(cells) + " |")
    L += ["", "## Pe câmp (toate documentele și condițiile, corect normalizat)", "",
          "| Câmp | " + " | ".join(engines) + " |", "|---|" + "---|" * len(engines)]
    fields = sorted({f for e in engines for f in FIELD_STATS.get(e, {})})
    for f in fields:
        L.append(f"| `{f}` | " + " | ".join(pct(*FIELD_STATS[e].get(f, [0, 0])) for e in engines) + " |")
    L.append("")
    L.append("_Detaliile per câmp, cu valori, sunt doar în jurnalul local `backend/benchmarks/real/details.log` (exclus din git)._")
    L += [
        "",
        f"Motoare: Tesseract {all_engines['tesseract'].version() or 'n/a'} (`--psm 6`, `ron+eng`); "
        f"OneOCR: {all_engines['oneocr'].version() or 'n/a'}.",
    ]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
