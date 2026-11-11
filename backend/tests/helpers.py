"""Test helpers: build synthetic OCR output without running an OCR engine."""

from __future__ import annotations

from PIL import Image

from app.ocr.base import OcrDocument, OcrLine, OcrWord

CHAR_W = 20
HEIGHT = 30


def make_line(chunks: list[tuple[int, str]] | str, y: int, conf: float = 0.95, page: int = 0) -> OcrLine:
    """`chunks` is a list of (x, text) column chunks, or a plain string at x=100."""
    if isinstance(chunks, str):
        chunks = [(100, chunks)]
    words: list[OcrWord] = []
    for x, text in chunks:
        cx = x
        for token in text.split(" "):
            if not token:
                cx += CHAR_W
                continue
            words.append(OcrWord(token, conf, (cx, y, CHAR_W * len(token), HEIGHT)))
            cx += CHAR_W * (len(token) + 1)
    return OcrLine(words=words, page=page)


def make_doc(rows: list, conf: float = 0.95, low_conf_words: set[str] | None = None) -> OcrDocument:
    lines = []
    for i, row in enumerate(rows):
        line = make_line(row, y=100 + 60 * i, conf=conf)
        if low_conf_words:
            for w in line.words:
                if w.text in low_conf_words:
                    w.confidence = 0.4
        lines.append(line)
    return OcrDocument(lines=lines, engine="fake")


class FakeEngine:
    """OCR engine double. Returns pre-built OCR output selected by the image's
    aspect ratio (height/width, 2 decimals), which survives preprocessing."""

    name = "fake"

    def __init__(self, docs_by_aspect: dict[float, OcrDocument] | None = None, available: bool = True):
        self.docs_by_aspect = docs_by_aspect or {}
        self.available = available

    def is_available(self) -> bool:
        return self.available

    def version(self):
        return "fake"

    def missing_languages(self):
        return []

    def recognize(self, image: Image.Image, page: int = 0):
        doc = self.docs_by_aspect.get(round(image.height / image.width, 2))
        return (list(doc.lines), 0) if doc else ([], 0)


def png_bytes(width: int, height: int, color=(255, 255, 255)) -> bytes:
    import io

    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


# --- canonical synthetic OCR layouts -----------------------------------------

CI_ROWS = [
    "ROMANIA ROUMANIE ROMANIA",
    "CARTE DE IDENTITATE CARTE D'IDENTITE IDENTITY CARD",
    [(60, "SERIA XY NR 000001"), (1000, "CNP 1800101400016")],
    [(490, "Nume/Nom/Last name"), (1450, "Sex/Sexe/Sex")],
    [(490, "IONESCU"), (1450, "M")],
    [(490, "Prenume/Prénom/First name")],
    [(490, "ALEX")],
    [(490, "Domiciliu/Adresse/Address")],
    [(490, "Mun. București Sec. 6")],
    [(490, "Str. Exemplului nr. 1 bl. A1 ap. 3")],
    [(490, "Emisă de/Délivrée par/Issued by"), (1100, "Valabilitate/Validité/Validity")],
    [(490, "SPCLEP DEMO"), (1100, "01.01.20-01.01.2030")],
    "IDROUIONESCU<<ALEX<<<<<<<<<<<<<<<<<<",
    "XY000001<6ROU8001014M300101914000162",
]

TALON_ROWS = [
    "ROMANIA",
    "CERTIFICAT DE INMATRICULARE",
    [(60, "A"), (200, "B 99 XYZ"), (1250, "F.1"), (1360, "1576")],
    [(60, "B"), (200, "10.03.2020"), (1250, "J"), (1360, "M1")],
    [(60, "C.1.1"), (200, "IONESCU"), (1250, "P.1"), (1360, "999")],
    [(60, "C.1.2"), (200, "ALEX"), (1250, "P.2"), (1360, "67")],
    [(60, "C.1.3"), (200, "MUN. BUCURESTI SEC. 6"), (1250, "P.3"), (1360, "BENZINA")],
    [(60, "D.1"), (200, "DACIA"), (1250, "R"), (1360, "ALB")],
    [(60, "D.3"), (200, "LOGAN"), (1250, "S.1"), (1360, "5")],
    [(60, "E"), (200, "UU1TEST9X00000001")],
]
