"""Benchmark OCR engines end to end on the synthetic sample sets.

For every sample set (backend/samples/manifest.json) and every degradation
variant, both documents are run through the FULL pipeline (decode -> OCR ->
parse -> validate) and each expected field is compared with ground truth.

Outcome per field:
  correct        value == expected
  wrong_flagged  value wrong (or missing) but the field is marked for review /
                 has an error or warning -> the operator is warned
  wrong_silent   value wrong and NOT flagged -> the dangerous case
A document the pipeline rejects (422 ...) counts all its fields as wrong_flagged.

Usage (from backend/):
  python scripts/benchmark_ocr.py                 # all available engines
  python scripts/benchmark_ocr.py --engines oneocr tesseract --out ../docs/OCR_BENCHMARK.md
"""

from __future__ import annotations

import argparse
import io
import json
import platform
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.ocr.preprocess import decode_upload  # noqa: E402
from app.ocr.registry import build_engines  # noqa: E402
from app.service import ProcessingError, extract  # noqa: E402
from app.store import ProcessingStore  # noqa: E402

CRITICAL = {
    "person.last_name", "person.first_name", "vehicle.registration_number", "vehicle.vin",
    "vehicle.make", "vehicle.model", "vehicle.engine_cc",
}

# ---------------------------------------------------------------------------
# degradations (deterministic)
# ---------------------------------------------------------------------------


def _noise(img: Image.Image, amount: float, seed: int) -> Image.Image:
    rnd = random.Random(seed)
    img = img.convert("RGB")
    px = img.load()
    for _ in range(int(img.width * img.height * amount)):
        x, y = rnd.randrange(img.width), rnd.randrange(img.height)
        n = rnd.randint(-45, 45)
        r, g, b = px[x, y]
        px[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n)))
    return img


def phone_photo(img):
    bg = Image.new("RGB", (img.width + 300, img.height + 300), (110, 95, 80))
    bg.paste(img.convert("RGB"), (150, 150))
    bg = bg.rotate(3.5, resample=Image.Resampling.BICUBIC, fillcolor=(110, 95, 80))
    bg = _noise(bg.filter(ImageFilter.GaussianBlur(1.3)), 0.012, 11)
    return bg.resize((int(bg.width * 0.65), int(bg.height * 0.65)), Image.Resampling.LANCZOS), 70


def low_res(img):
    return img.resize((int(img.width * 0.35), int(img.height * 0.35)), Image.Resampling.BILINEAR), None


def blur(img):
    return img.filter(ImageFilter.GaussianBlur(2.2)), None


def dark_low_contrast(img):
    img = ImageEnhance.Contrast(img.convert("RGB")).enhance(0.45)
    return ImageEnhance.Brightness(img).enhance(0.5), None


def jpeg_heavy(img):
    return img.resize((int(img.width * 0.6), int(img.height * 0.6)), Image.Resampling.BILINEAR), 18


def perspective(img):
    w, h = img.size
    # map output quad -> input; top edge narrower (photo taken from below)
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    dst = [(w * 0.06, h * 0.05), (w * 0.95, 0), (w, h), (0, h * 0.97)]
    coeffs = _perspective_coeffs(dst, src)
    out = img.convert("RGB").transform((w, h), Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC,
                                       fillcolor=(120, 110, 100))
    return out, 85


def glare(img):
    img = img.convert("RGB")
    overlay = Image.new("L", img.size, 0)
    from PIL import ImageDraw

    d = ImageDraw.Draw(overlay)
    w, h = img.size
    d.ellipse((w * 0.55, h * 0.25, w * 0.85, h * 0.6), fill=210)
    overlay = overlay.filter(ImageFilter.GaussianBlur(w * 0.04))
    white = Image.new("RGB", img.size, (255, 255, 255))
    return Image.composite(white, img, overlay), None


def low_res_20(img):
    return img.resize((int(img.width * 0.2), int(img.height * 0.2)), Image.Resampling.BILINEAR), None


def blur_heavy(img):
    return img.filter(ImageFilter.GaussianBlur(3.5)), None


def worst_case(img):
    img, _ = perspective(img)
    img, _ = phone_photo(img)
    img = img.filter(ImageFilter.GaussianBlur(1.5))
    img = ImageEnhance.Contrast(img).enhance(0.6)
    return img.resize((int(img.width * 0.6), int(img.height * 0.6)), Image.Resampling.BILINEAR), 35


def _perspective_coeffs(pa, pb):
    import numpy as np

    rows = []
    for (x, y), (u, v) in zip(pa, pb):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    a = np.array(rows, dtype=float)
    b = np.array([c for p in pb for c in p], dtype=float)
    return np.linalg.solve(a, b).tolist()


VARIANTS = {
    "original": None,
    "phone_photo": phone_photo,
    "perspective": perspective,
    "low_res_35pct": low_res,
    "blur_2px": blur,
    "dark_low_contrast": dark_low_contrast,
    "jpeg_q18": jpeg_heavy,
    "glare": glare,
    "low_res_20pct": low_res_20,
    "blur_3_5px": blur_heavy,
    "worst_case": worst_case,
}
VARIANT_NOTES = {
    "original": "files exactly as in backend/samples (incl. one photo-like JPEG and one PDF)",
    "phone_photo": "background, 3.5° rotation, blur 1.3 px, noise, 65% scale, JPEG q70",
    "perspective": "keystone distortion (~6% top inset), JPEG q85",
    "low_res_35pct": "downscaled to 35% (≈600 px wide)",
    "blur_2px": "Gaussian blur radius 2.2 px",
    "dark_low_contrast": "contrast ×0.45, brightness ×0.5",
    "jpeg_q18": "60% scale, JPEG quality 18",
    "glare": "bright elliptical reflection over the right-centre area",
    "low_res_20pct": "downscaled to 20% (≈350 px wide; text ≈ 6–8 px high)",
    "blur_3_5px": "Gaussian blur radius 3.5 px",
    "worst_case": "perspective + phone photo + extra blur 1.5 px + contrast ×0.6 + 60% scale + JPEG q35",
}


def render(path: Path, variant: str) -> bytes:
    data = path.read_bytes()
    fn = VARIANTS[variant]
    if fn is None:
        return data
    page = decode_upload(data, max_pdf_pages=1, dpi=300).pages[0]
    out, quality = fn(page)
    buf = io.BytesIO()
    if quality:
        out.convert("RGB").save(buf, format="JPEG", quality=quality)
    else:
        out.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------


def get(obj: dict, path: str):
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        cur = cur.get(part)
    return cur


@dataclass
class Tally:
    correct: int = 0
    wrong_flagged: int = 0
    wrong_silent: int = 0
    crit_correct: int = 0
    crit_total: int = 0
    rejected_docs: int = 0
    ms: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def total(self):
        return self.correct + self.wrong_flagged + self.wrong_silent

    def add(self, other: "Tally"):
        for k in ("correct", "wrong_flagged", "wrong_silent", "crit_correct", "crit_total", "rejected_docs"):
            setattr(self, k, getattr(self, k) + getattr(other, k))
        self.ms += other.ms
        self.errors += other.errors


class Preprocessed:
    """Wrap an engine to force the Tesseract-style preprocessing (A/B test)."""

    preprocessing = "full"

    def __init__(self, inner):
        self.inner = inner
        self.name = inner.name + "+preprocess"

    def is_available(self):
        return self.inner.is_available()

    def recognize(self, image, page=0):
        return self.inner.recognize(image, page)


def run_case(engine, sample: dict, variant: str) -> Tally:
    t = Tally()
    sd = settings.samples_dir
    files = {"identity": render(sd / sample["identity"], variant),
             "registration": render(sd / sample["registration"], variant)}
    expected = sample["expected"]
    started = time.perf_counter()
    try:
        body = extract(files, engine=engine, settings=settings, store=ProcessingStore(60)).model_dump()
    except ProcessingError as exc:
        t.rejected_docs += 1
        t.errors.append(f"{sample['id']}/{variant}: {exc.code} ({exc.document})")
        for path in expected:
            t.wrong_flagged += 1
            t.crit_total += path in CRITICAL
        return t
    t.ms.append((time.perf_counter() - started) * 1000 / 2)  # per document
    flagged = {i["field"] for i in body["validation"]["issues"] if i["severity"] in ("error", "warning")}
    for path, exp in expected.items():
        got = get(body, path)
        meta = body["field_meta"].get(path) or body["field_meta"].get(path + ".name") or {}
        is_crit = path in CRITICAL
        t.crit_total += is_crit
        if got == exp:
            t.correct += 1
            t.crit_correct += is_crit
        elif meta.get("review_required") or path in flagged or got is None:
            t.wrong_flagged += 1
            t.errors.append(f"{sample['id']}/{variant}: {path} got {got!r} (flagged)")
        else:
            t.wrong_silent += 1
            t.errors.append(f"{sample['id']}/{variant}: {path} got {got!r} expected {exp!r} (SILENT)")
    return t


def pct(a, b):
    return f"{100 * a / b:.1f}%" if b else "–"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engines", nargs="*", default=None)
    ap.add_argument("--variants", nargs="*", default=list(VARIANTS))
    ap.add_argument("--ab-preprocess", action="store_true", help="also run OneOCR with Tesseract preprocessing")
    ap.add_argument("--out", type=Path, default=None, help="write a markdown report")
    args = ap.parse_args()

    manifest = json.loads((settings.samples_dir / "manifest.json").read_text(encoding="utf-8"))
    all_engines = build_engines(settings)
    names = args.engines or [n for n, e in all_engines.items() if e.is_available()]
    engines = [(n, all_engines[n]) for n in names if all_engines[n].is_available()]
    if args.ab_preprocess and all_engines["oneocr"].is_available():
        engines.append(("oneocr+preprocess", Preprocessed(all_engines["oneocr"])))

    results: dict[str, dict[str, Tally]] = {}
    for name, eng in engines:
        results[name] = {}
        for variant in args.variants:
            total = Tally()
            for sample in manifest["sets"]:
                total.add(run_case(eng, sample, variant))
            results[name][variant] = total
            print(f"{name:20s} {variant:18s} correct {pct(total.correct, total.total):>6s} "
                  f"silent {total.wrong_silent:2d} ms/doc {statistics.mean(total.ms) if total.ms else 0:7.0f}",
                  flush=True)

    if args.out:
        args.out.write_text(report(results, all_engines, manifest, args.variants), encoding="utf-8")
        print(f"report written to {args.out}")


def report(results, all_engines, manifest, variants) -> str:
    n_fields = sum(len(s["expected"]) for s in manifest["sets"])
    lines = [
        "# OCR engine benchmark: OneOCR vs Tesseract",
        "",
        f"_Generated by `backend/scripts/benchmark_ocr.py` on {date.today().isoformat()}._",
        "",
        "## Setup",
        "",
        f"- Machine: {platform.platform()}, {platform.processor() or 'unknown CPU'}, Python {platform.python_version()}",
        f"- Tesseract: {all_engines['tesseract'].version() or 'n/a'} (`--psm 6`, `ron+eng`, with grayscale/upscale/autocontrast preprocessing)",
        f"- OneOCR: {all_engines['oneocr'].version() or 'n/a'} (colour image as decoded; only images < 900 px wide are upscaled). "
        "`oneocr+preprocess` = same engine fed the Tesseract preprocessing (A/B test).",
        f"- Data: {len(manifest['sets'])} synthetic sample sets (CI 1997, CEI, three talon layouts incl. a PDF), "
        f"{n_fields} ground-truth fields per variant, {len(variants)} variants → "
        f"{n_fields * len(variants)} field checks and {2 * len(manifest['sets']) * len(variants)} documents per engine.",
        "- Each case runs the **full pipeline** (decode → OCR → parsing → validation), i.e. it measures what the "
        "operator would see, not raw character accuracy.",
        "",
        "**Caveat:** all images are synthetic renders of fictitious data (no real documents may be used). Real "
        "documents add guilloche backgrounds, holograms and wear; absolute numbers will be lower. The comparison "
        "between engines on identical inputs is the meaningful part.",
        "",
        "## Summary (all variants)",
        "",
        "| Engine | Fields correct | Critical fields correct | Wrong but flagged | **Wrong & silent** | Docs rejected | Mean ms / document |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, by_var in results.items():
        t = Tally()
        for v in by_var.values():
            t.add(v)
        lines.append(
            f"| {name} | {pct(t.correct, t.total)} ({t.correct}/{t.total}) | {pct(t.crit_correct, t.crit_total)} | "
            f"{t.wrong_flagged} | **{t.wrong_silent}** | {t.rejected_docs} | "
            f"{statistics.mean(t.ms):.0f} |" if t.ms else f"| {name} | – | – | – | – | {t.rejected_docs} | – |"
        )
    lines += ["", "## Field accuracy per variant", "",
              "| Variant | " + " | ".join(results) + " |", "|---|" + "---|" * len(results)]
    for v in variants:
        cells = []
        for name in results:
            t = results[name][v]
            cell = f"{pct(t.correct, t.total)}"
            if t.wrong_silent:
                cell += f" ({t.wrong_silent} silent)"
            if t.rejected_docs:
                cell += f" ({t.rejected_docs} doc rejected)"
            cells.append(cell)
        lines.append(f"| `{v}` | " + " | ".join(cells) + " |")
    lines += ["", "Variants:", ""] + [f"- `{v}`: {VARIANT_NOTES[v]}" for v in variants]
    lines += ["", "## Mean processing time per document (ms)", "",
              "| Variant | " + " | ".join(results) + " |", "|---|" + "---|" * len(results)]
    for v in variants:
        lines.append(f"| `{v}` | " + " | ".join(
            f"{statistics.mean(results[n][v].ms):.0f}" if results[n][v].ms else "–" for n in results) + " |")
    lines += ["", "## Every miss", ""]
    for name, by_var in results.items():
        errs = [e for v in by_var.values() for e in v.errors]
        lines.append(f"<details><summary>{name}: {len(errs)} entries</summary>\n")
        lines += [f"- {e}" for e in errs] or ["- none"]
        lines.append("\n</details>\n")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
