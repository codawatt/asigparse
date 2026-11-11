"""Generate SYNTHETIC demo documents (no real persons, IDs or vehicles).

The images only approximate the *text layout* of a Romanian CI model 1997 /
CEI and a vehicle registration certificate so the OCR + parsing pipeline can
be demonstrated end to end. They carry a SPECIMEN / DATE FICTIVE marking and
deliberately contain no official artwork, holograms or emblems.

Usage (from backend/):  python scripts/generate_samples.py
Output: backend/samples/*.png|jpg|pdf + manifest.json (with ground truth)
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.parsing.mrz import check_digit  # noqa: E402
from app.validation.validators import cnp_check_digit  # noqa: E402

OUT = ROOT / "samples"
FONT_DIRS = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu"), Path("/Library/Fonts"),
             Path("/System/Library/Fonts/Supplemental")]
FONT_CANDIDATES = {
    "regular": ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"],
    "bold": ["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"],
    "mono": ["consola.ttf", "cour.ttf", "Courier New.ttf", "DejaVuSansMono.ttf"],
}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    for d in FONT_DIRS:
        for name in FONT_CANDIDATES[kind]:
            p = d / name
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size=size)


def valid_cnp(first12: str) -> str:
    return first12 + str(cnp_check_digit(first12))


def mrz_td2(last: str, first: str, series: str, number: str, dob: str, sex: str, exp: str, cnp: str) -> tuple[str, str]:
    l1 = ("IDROU" + last.replace(" ", "<").replace("-", "<") + "<<" + first.replace(" ", "<").replace("-", "<"))
    l1 = l1.ljust(36, "<")[:36]
    doc = (series + number).ljust(9, "<")
    optional = (cnp[0] + cnp[-6:]).ljust(7, "<")
    body = doc + str(check_digit(doc)) + "ROU" + dob + str(check_digit(dob)) + sex + exp + str(check_digit(exp)) + optional
    composite = body[0:10] + body[13:20] + body[21:35]
    return l1, body + str(check_digit(composite))


def specimen(draw: ImageDraw.ImageDraw, w: int) -> None:
    f = font("bold", 30)
    text = "SPECIMEN · DATE FICTIVE · SYNTHETIC TEST DATA"
    tw = draw.textlength(text, font=f)
    draw.rectangle((w - tw - 50, 12, w - 20, 58), fill=(255, 235, 235))
    draw.text((w - tw - 35, 18), text, font=f, fill=(190, 30, 30))


# ---------------------------------------------------------------------------
# Identity cards
# ---------------------------------------------------------------------------

PEOPLE = {
    "ionescu": dict(last="IONESCU", first="ALEX", cnp=valid_cnp("180010140001"), series="XY", number="000001",
                    sex="M", dob="800101", exp_dmy=("01.01.20", "01.01.2030"), exp_mrz="300101",
                    birthplace="Mun. București Sec. 6",
                    address=["Mun. București Sec. 6", "Str. Exemplului nr. 1 bl. A1 ap. 3"]),
    "popescu": dict(last="POPESCU", first="MARIA-ELENA", cnp=valid_cnp("285031512001"), series="ZZ",
                    number="654321", sex="F", dob="850315", exp_dmy=("15.03.21", "15.03.2031"), exp_mrz="310315",
                    birthplace="Mun. Cluj-Napoca Jud. Cluj",
                    address=["Mun. Cluj-Napoca Jud. Cluj", "Str. Fictivă nr. 10 ap. 5"]),
}


def draw_ci1997(p: dict) -> Image.Image:
    W, H = 1800, 1135
    img = Image.new("RGB", (W, H), (236, 242, 248))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((6, 6, W - 6, H - 6), radius=40, outline=(150, 170, 190), width=4)
    specimen(d, W)
    d.text((60, 70), "ROMÂNIA   ROUMANIE   ROMANIA", font=font("bold", 40), fill=(20, 40, 90))
    d.text((60, 125), "CARTE DE IDENTITATE   CARTE D'IDENTITE   IDENTITY CARD", font=font("bold", 34), fill=(20, 40, 90))
    d.text((60, 190), f"SERIA {p['series']}   NR {p['number']}", font=font("bold", 40), fill=(10, 10, 10))
    d.text((1000, 190), f"CNP {p['cnp']}", font=font("bold", 40), fill=(10, 10, 10))
    d.rectangle((60, 270, 440, 760), fill=(205, 212, 222), outline=(160, 170, 180), width=3)
    d.text((170, 490), "FOTO", font=font("bold", 50), fill=(150, 158, 170))

    lbl, val = font("regular", 28), font("bold", 40)
    rows = [
        ("Nume/Nom/Last name", [p["last"]]),
        ("Prenume/Prénom/First name", [p["first"]]),
        ("Cetățenie/Nationalité/Nationality", ["Română / ROU"]),
        ("Loc naștere/Lieu de naissance/Place of birth", [p["birthplace"]]),
        ("Domiciliu/Adresse/Address", p["address"]),
    ]
    y = 265
    for label, values in rows:
        d.text((490, y), label, font=lbl, fill=(70, 80, 100))
        y += 36
        for v in values:
            d.text((490, y), v, font=val, fill=(10, 10, 10))
            y += 50
        y += 12
    d.text((1450, 265), "Sex/Sexe/Sex", font=lbl, fill=(70, 80, 100))
    d.text((1450, 301), p["sex"], font=val, fill=(10, 10, 10))
    d.text((490, y), "Emisă de/Délivrée par/Issued by", font=lbl, fill=(70, 80, 100))
    d.text((1100, y), "Valabilitate/Validité/Validity", font=lbl, fill=(70, 80, 100))
    y += 36
    d.text((490, y), "SPCLEP DEMO", font=val, fill=(10, 10, 10))
    d.text((1100, y), f"{p['exp_dmy'][0]}-{p['exp_dmy'][1]}", font=val, fill=(10, 10, 10))

    l1, l2 = mrz_td2(p["last"], p["first"], p["series"], p["number"], p["dob"], p["sex"], p["exp_mrz"], p["cnp"])
    mono = font("mono", 50)
    d.rectangle((30, 935, W - 30, H - 25), fill=(250, 250, 250))
    d.text((60, 950), l1, font=mono, fill=(0, 0, 0))
    d.text((60, 1020), l2, font=mono, fill=(0, 0, 0))
    return img


def draw_cei(p: dict) -> Image.Image:
    """Simplified electronic identity card front: no address is printed."""
    W, H = 1800, 1135
    img = Image.new("RGB", (W, H), (240, 238, 248))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((6, 6, W - 6, H - 6), radius=40, outline=(160, 150, 190), width=4)
    specimen(d, W)
    d.text((60, 70), "ROMÂNIA / ROMANIA", font=font("bold", 42), fill=(40, 30, 90))
    d.text((60, 125), "CARTE ELECTRONICĂ DE IDENTITATE / ELECTRONIC IDENTITY CARD", font=font("bold", 34),
           fill=(40, 30, 90))
    d.rectangle((60, 220, 470, 760), fill=(210, 205, 222))
    d.text((180, 470), "FOTO", font=font("bold", 50), fill=(150, 145, 170))
    lbl, val = font("regular", 28), font("bold", 40)
    rows = [
        ("Nume/Last name", p["last"]),
        ("Prenume/First name", p["first"]),
        ("Sex/Sex", p["sex_word"]),
        ("Cetățenie/Nationality", "ROU"),
        ("CNP/Personal No.", p["cnp"]),
        ("Seria și numărul/Document No.", f"SERIA {p['series']} NR {p['number']}"),
        ("Data expirării/Date of expiry", p["expiry"]),
    ]
    y = 220
    for label, value in rows:
        d.text((520, y), label, font=lbl, fill=(80, 70, 100))
        d.text((520, y + 36), value, font=val, fill=(10, 10, 10))
        y += 100
    return img


# ---------------------------------------------------------------------------
# Registration certificates
# ---------------------------------------------------------------------------

VEHICLES = {
    "logan": {
        "A": "B 99 XYZ", "B": "10.03.2020", "C.1.1": "IONESCU", "C.1.2": "ALEX",
        "C.1.3": "MUN. BUCUREȘTI SEC. 6 STR. EXEMPLULUI NR. 1", "D.1": "DACIA", "D.2": "SD / SDAAH / 4",
        "D.3": "LOGAN", "E": "UU1TEST9X00000001", "F.1": "1576", "J": "M1", "P.1": "999", "P.2": "67",
        "P.3": "BENZINA", "R": "ALB", "S.1": "5",
    },
    "golf_leasing": {
        "A": "CJ 99 TST", "B": "15.06.2019", "C.1.1": "POPESCU", "C.1.2": "MARIA-ELENA",
        "C.1.3": "MUN. CLUJ-NAPOCA STR. FICTIVĂ NR. 10", "C.2.1": "SC EXEMPLU LEASING IFN SA",
        "C.2.3": "MUN. BUCUREȘTI SEC. 1 BD. DEMONSTRAȚIEI NR. 7", "D.1": "VOLKSWAGEN", "D.2": "AU / CHX / 2",
        "D.3": "GOLF", "E": "WVWZZZTEST0000002", "F.1": "1820", "J": "M1", "P.1": "1598", "P.2": "85",
        "P.3": "MOTORINA", "R": "GRI", "S.1": "5",
    },
    "zoe_company": {
        "A": "B 123 DMO", "B": "21.09.2022", "C.1.1": "SC EXEMPLU FLOTA SRL",
        "C.1.3": "MUN. BUCUREȘTI SEC. 3 STR. TESTULUI NR. 4", "D.1": "RENAULT", "D.2": "AG / 5AQ / 1",
        "D.3": "ZOE", "E": "VF1TEST0000000003", "F.1": "1988", "J": "M1", "P.2": "100", "P.3": "ELECTRIC",
        "R": "ALBASTRU", "S.1": "5",
    },
}


def draw_registration_single(v: dict) -> Image.Image:
    """Layout 1: code and value on the same line, two columns."""
    W, H = 1700, 1250
    img = Image.new("RGB", (W, H), (244, 247, 240))
    d = ImageDraw.Draw(img)
    specimen(d, W)
    d.text((60, 70), "ROMÂNIA", font=font("bold", 44), fill=(20, 70, 40))
    d.text((60, 125), "CERTIFICAT DE ÎNMATRICULARE", font=font("bold", 44), fill=(20, 70, 40))
    d.text((60, 180), "Partea I / Part I", font=font("regular", 30), fill=(60, 90, 70))
    code_f, val_f = font("bold", 32), font("bold", 38)
    left = ["A", "B", "C.1.1", "C.1.2", "C.1.3", "C.2.1", "C.2.2", "C.2.3", "D.1", "D.2", "D.3", "E"]
    right = ["F.1", "J", "P.1", "P.2", "P.3", "R", "S.1"]
    y = 260
    for code in left:
        if code not in v:
            continue
        d.text((60, y), code, font=code_f, fill=(90, 110, 90))
        d.text((200, y - 3), v[code], font=val_f, fill=(10, 10, 10))
        y += 72
    y = 260
    for code in right:
        if code not in v:
            continue
        d.text((1250, y), code, font=code_f, fill=(90, 110, 90))
        d.text((1360, y - 3), v[code], font=val_f, fill=(10, 10, 10))
        y += 72
    return img


def draw_registration_stacked(v: dict) -> Image.Image:
    """Layout 2: small code above the value; several technical codes per line."""
    W, H = 1700, 1400
    img = Image.new("RGB", (W, H), (248, 246, 238))
    d = ImageDraw.Draw(img)
    specimen(d, W)
    d.text((60, 70), "ROMÂNIA — CERTIFICAT DE ÎNMATRICULARE", font=font("bold", 42), fill=(70, 50, 20))
    code_f, val_f = font("bold", 30), font("bold", 38)
    y = 170
    for code in ["A", "B", "C.1.1", "C.1.2", "C.1.3", "C.2.1", "C.2.3", "D.1", "D.3", "E"]:
        if code not in v:
            continue
        d.text((60, y), code, font=code_f, fill=(70, 55, 30))
        d.text((60, y + 38), v[code], font=val_f, fill=(10, 10, 10))
        y += 104
    tech = "   ".join(f"{c} {v[c]}" for c in ["P.1", "P.2", "P.3"] if c in v)
    d.text((60, y + 10), tech, font=val_f, fill=(10, 10, 10))
    tech2 = "   ".join(f"{c} {v[c]}" for c in ["F.1", "S.1", "R"] if c in v)
    d.text((60, y + 70), tech2, font=val_f, fill=(10, 10, 10))
    return img


# ---------------------------------------------------------------------------
# degradations
# ---------------------------------------------------------------------------


def as_photo(img: Image.Image, seed: int = 7) -> Image.Image:
    """Simulate a phone photo: background, slight rotation, blur, noise, downscale."""
    rnd = random.Random(seed)
    bg = Image.new("RGB", (img.width + 260, img.height + 260), (120, 100, 80))
    bg.paste(img, (130, 130))
    bg = bg.rotate(2.2, resample=Image.Resampling.BICUBIC, fillcolor=(120, 100, 80))
    bg = bg.filter(ImageFilter.GaussianBlur(1.1))
    px = bg.load()
    for _ in range(int(bg.width * bg.height * 0.01)):
        x, y = rnd.randrange(bg.width), rnd.randrange(bg.height)
        n = rnd.randint(-40, 40)
        r, g, b = px[x, y]
        px[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n)))
    return bg.resize((int(bg.width * 0.7), int(bg.height * 0.7)), Image.Resampling.LANCZOS)


# ---------------------------------------------------------------------------


def main() -> None:
    OUT.mkdir(exist_ok=True)
    ion, pop = PEOPLE["ionescu"], PEOPLE["popescu"]
    cei = dict(last="VASILESCU", first="ANDREI", sex_word="M", series="ZV", number="112233",
               cnp=valid_cnp("192072046001")[:12] + str((cnp_check_digit("192072046001") + 3) % 10),
               expiry="20.07.2025")

    draw_ci1997(ion).save(OUT / "ci_ionescu.png")
    draw_registration_single(VEHICLES["logan"]).save(OUT / "talon_logan.png")
    as_photo(draw_ci1997(pop)).save(OUT / "ci_popescu_photo.jpg", quality=72)
    draw_registration_stacked(VEHICLES["golf_leasing"]).save(OUT / "talon_golf_leasing.pdf", resolution=200)
    draw_cei(cei).save(OUT / "cei_vasilescu.png")
    draw_registration_single(VEHICLES["zoe_company"]).save(OUT / "talon_zoe_company.png")
    # an unusable image for error-handling demos
    Image.new("RGB", (800, 500), (128, 128, 128)).filter(ImageFilter.GaussianBlur(5)).save(OUT / "blank_unreadable.png")

    def plate(s: str) -> str:
        return s.replace(" ", "")

    manifest = {
        "synthetic": True,
        "notice": "Toate datele sunt fictive, generate de scripts/generate_samples.py.",
        "sets": [
            {
                "id": "standard",
                "title": "Caz standard: CI 1997 + talon (imagini clare)",
                "description": "Titular = persoana din CI; C.2 absent (proprietarul nu este presupus).",
                "identity": "ci_ionescu.png",
                "registration": "talon_logan.png",
                "expected": {
                    "person.last_name": ion["last"], "person.first_name": ion["first"],
                    "person.national_id": ion["cnp"], "person.identity_document.series": ion["series"],
                    "person.identity_document.number": ion["number"],
                    "person.identity_document.expiry_date": "2030-01-01",
                    "vehicle.registration_number": plate(VEHICLES["logan"]["A"]),
                    "vehicle.vin": VEHICLES["logan"]["E"], "vehicle.make": "DACIA", "vehicle.model": "LOGAN",
                    "vehicle.engine_cc": 999, "vehicle.power_kw": 67, "vehicle.fuel": "PETROL",
                    "vehicle.first_registration": "2020-03-10",
                    "vehicle.certificate_holder.name": "IONESCU ALEX", "vehicle.legal_owner": None,
                },
            },
            {
                "id": "photo_leasing",
                "title": "Fotografie înclinată + talon PDF cu proprietar leasing",
                "description": "CI fotografiată (blur, rotire, zgomot); talon PDF cu alt layout; C.2 ≠ C.1.",
                "identity": "ci_popescu_photo.jpg",
                "registration": "talon_golf_leasing.pdf",
                "expected": {
                    "person.last_name": pop["last"], "person.first_name": pop["first"],
                    "person.national_id": pop["cnp"], "person.identity_document.series": pop["series"],
                    "person.identity_document.number": pop["number"],
                    "vehicle.registration_number": plate(VEHICLES["golf_leasing"]["A"]),
                    "vehicle.vin": VEHICLES["golf_leasing"]["E"], "vehicle.make": "VOLKSWAGEN",
                    "vehicle.model": "GOLF", "vehicle.engine_cc": 1598, "vehicle.power_kw": 85,
                    "vehicle.fuel": "DIESEL", "vehicle.first_registration": "2019-06-15",
                    "vehicle.certificate_holder.name": "POPESCU MARIA-ELENA",
                    "vehicle.legal_owner.name": "SC EXEMPLU LEASING IFN SA",
                },
            },
            {
                "id": "cei_issues",
                "title": "CEI fără domiciliu + firmă titulară + vehicul electric",
                "description": "CNP cu cifră de control greșită și act expirat (intenționat); domiciliul nu "
                               "apare pe CEI; titular persoană juridică.",
                "identity": "cei_vasilescu.png",
                "registration": "talon_zoe_company.png",
                "expected": {
                    "person.last_name": cei["last"], "person.first_name": cei["first"],
                    "person.national_id": cei["cnp"], "person.address": None,
                    "vehicle.registration_number": plate(VEHICLES["zoe_company"]["A"]),
                    "vehicle.vin": VEHICLES["zoe_company"]["E"], "vehicle.make": "RENAULT", "vehicle.model": "ZOE",
                    "vehicle.engine_cc": None, "vehicle.fuel": "ELECTRIC",
                    "vehicle.certificate_holder.name": "SC EXEMPLU FLOTA SRL",
                },
            },
        ],
        "extra_files": {"unreadable": "blank_unreadable.png"},
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote samples to {OUT}")


if __name__ == "__main__":
    main()
