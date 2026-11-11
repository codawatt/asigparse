"""Parser + pipeline tests on synthetic OCR output (no OCR engine needed)."""

from datetime import date

from app.parsing.identity import identity_score, parse_identity
from app.parsing.mrz import find_mrz
from app.parsing.registration import parse_registration, registration_score
from app.pipeline import build_from_extraction, validate_payload
from tests.helpers import CI_ROWS, TALON_ROWS, make_doc

TODAY = date(2026, 11, 11)


def codes(validation):
    return {(i.field, i.code) for i in validation.issues}


# --- identity -----------------------------------------------------------------


def test_identity_two_column_layout():
    ide = parse_identity(make_doc(CI_ROWS))
    assert ide.document_type == "CI_1997"
    assert ide.last_name.value == "IONESCU"  # not polluted by the "Sex" column
    assert ide.first_name.value == "ALEX"
    assert ide.national_id.value == "1800101400016"
    assert "cnp_checksum" in ide.national_id.checks
    assert (ide.series.value, ide.number.value) == ("XY", "000001")
    assert ide.expiry_date.value == "01.01.2030"
    assert ide.address.value == "Mun. București Sec. 6 Str. Exemplului nr. 1 bl. A1 ap. 3"
    assert ide.mrz and ide.mrz.document_number_valid and ide.mrz.birth_date_valid and ide.mrz.composite_valid


def test_identity_falls_back_to_mrz_when_viz_missing():
    rows = [r for r in CI_ROWS if r not in (CI_ROWS[3], CI_ROWS[4], CI_ROWS[5], CI_ROWS[6])]
    ide = parse_identity(make_doc(rows))
    assert ide.last_name.value == "IONESCU" and ide.last_name.source == "identity.MRZ"
    assert ide.first_name.value == "ALEX"


def test_mrz_ocr_noise_repaired_only_when_check_digit_verifies():
    doc = make_doc(["IDROUIONESCU<<ALEX<<<<<<sssssssss<<<", "XYQ00001<6ROU8001014M300101914000162"])
    mrz = find_mrz(doc.lines)
    assert mrz.last_name == "IONESCU" and mrz.first_name == "ALEX"
    assert mrz.document_number == "XY000001" and mrz.document_number_valid
    # a wrong digit that no substitution can fix stays invalid
    doc = make_doc(["IDROUIONESCU<<ALEX<<<<<<<<<<<<<<<<<<", "XY000009<6ROU8001014M300101914000162"])
    assert not find_mrz(doc.lines).document_number_valid


def test_identity_missing_fields_are_none_not_invented():
    ide = parse_identity(make_doc(["CARTE DE IDENTITATE", "IDENTITY CARD", "Nume/Nom/Last name", "IONESCU"]))
    assert ide.last_name.value == "IONESCU"
    for field in (ide.first_name, ide.national_id, ide.series, ide.number, ide.expiry_date, ide.address):
        assert field.value is None


def test_cei_without_address_is_not_hallucinated():
    rows = [
        "CARTE ELECTRONICA DE IDENTITATE / ELECTRONIC IDENTITY CARD",
        "Nume/Last name", "VASILESCU", "Prenume/First name", "ANDREI",
        "CNP/Personal No.", "1920720460011", "Data expirarii/Date of expiry", "20.07.2030",
    ]
    ide = parse_identity(make_doc(rows))
    assert ide.document_type == "CEI"
    assert ide.address.value is None and not ide.address_label_present
    person, vehicle, meta, ctx = build_from_extraction(ide, None)
    val = validate_payload(person, vehicle, meta, ctx, threshold=0.85, today=TODAY)
    assert person.address is None
    assert ("person.address", "ADDRESS_NOT_ON_DOCUMENT") in codes(val)
    assert meta["person.address"].status == "not_on_document"


# --- registration -------------------------------------------------------------


def test_registration_two_column_layout():
    reg = parse_registration(make_doc(TALON_ROWS))
    assert reg.registration_number.value == "B99XYZ"  # "B 99 XYZ" not mistaken for code B
    assert reg.first_registration.value == "10.03.2020"
    assert reg.holder_name.value == "IONESCU ALEX"
    assert (reg.make.value, reg.model.value) == ("DACIA", "LOGAN")
    assert reg.vin.value == "UU1TEST9X00000001"
    assert (reg.engine_cc.value, reg.power_kw.value, reg.fuel.value) == (999, 67, "PETROL")
    assert (reg.max_mass_kg.value, reg.category.value, reg.color.value, reg.seats.value) == (1576, "M1", "ALB", 5)
    assert not reg.owner_present and reg.owner_name.value is None


def test_registration_stacked_and_glued_codes_with_owner():
    rows = [
        "ROMANIA — CERTIFICAT DE INMATRICULARE",
        "A", "CJ 99 TST", "B", "15.06.2019", "C.1.1", "POPESCU", "C.12", "MARIA-ELENA",
        "C.1.3", "MUN. CLUJ-NAPOCA STR. FICTIVA NR. 10",
        "C.2.1", "SC EXEMPLU LEASING IFN SA", "C.2:3", "MUN. BUCURESTI SEC. 1",
        "D.1", "VOLKSWAGEN", "D.3", "GOLF", "E", "WVWZZZTEST0000002",
        "P.11598 P.285 P.3 MOTORINA",
    ]
    reg = parse_registration(make_doc(rows))
    assert reg.registration_number.value == "CJ99TST"
    assert reg.holder_name.value == "POPESCU MARIA-ELENA"
    assert reg.holder_address.value == "MUN. CLUJ-NAPOCA STR. FICTIVA NR. 10"
    assert reg.owner_present and reg.owner_name.value == "SC EXEMPLU LEASING IFN SA"
    assert reg.owner_address.value == "MUN. BUCURESTI SEC. 1"
    assert (reg.make.value, reg.model.value) == ("VOLKSWAGEN", "GOLF")
    assert (reg.engine_cc.value, reg.power_kw.value, reg.fuel.value) == (1598, 85, "DIESEL")


def test_registration_illegible_code_is_reported_not_guessed():
    rows = ["CERTIFICAT DE INMATRICULARE", "A", "B 99 XYZ", "G2A", "SC EXEMPLU LEASING IFN SA", "D.1", "DACIA"]
    reg = parse_registration(make_doc(rows))
    assert reg.owner_name.value is None
    assert any("G2A" in n for n in reg.notes)


def test_document_type_scoring():
    assert identity_score(make_doc(CI_ROWS)) > registration_score(make_doc(CI_ROWS))
    assert registration_score(make_doc(TALON_ROWS)) > identity_score(make_doc(TALON_ROWS))


# --- pipeline rules -----------------------------------------------------------


def test_holder_is_never_copied_to_owner_and_difference_flagged():
    ide = parse_identity(make_doc(CI_ROWS))
    rows = list(TALON_ROWS)
    rows[4] = [(60, "C.1.1"), (200, "SC EXEMPLU FLOTA SRL"), (1250, "P.1"), (1360, "999")]
    rows[5] = [(60, "D.2"), (200, "SD"), (1250, "P.2"), (1360, "67")]
    reg = parse_registration(make_doc(rows))
    person, vehicle, meta, ctx = build_from_extraction(ide, reg)
    val = validate_payload(person, vehicle, meta, ctx, threshold=0.85, today=TODAY)
    assert vehicle.certificate_holder.name == "SC EXEMPLU FLOTA SRL"
    assert vehicle.legal_owner is None
    assert ("vehicle.legal_owner.name", "OWNER_NOT_STATED") in codes(val)
    assert ("vehicle.certificate_holder.name", "HOLDER_DIFFERS_FROM_PERSON") in codes(val)
    assert meta["vehicle.legal_owner.name"].review_required


def test_low_confidence_flags_review():
    reg = parse_registration(make_doc(TALON_ROWS, low_conf_words={"UU1TEST9X00000001"}))
    person, vehicle, meta, ctx = build_from_extraction(None, reg)
    val = validate_payload(person, vehicle, meta, ctx, threshold=0.85, today=TODAY)
    assert meta["vehicle.vin"].review_required
    assert meta["vehicle.vin"].status == "needs_review"
    assert ("vehicle.vin", "LOW_CONFIDENCE") in codes(val)
    assert not meta["vehicle.make"].review_required


def test_missing_identity_document_reported():
    reg = parse_registration(make_doc(TALON_ROWS))
    person, vehicle, meta, ctx = build_from_extraction(None, reg)
    val = validate_payload(person, vehicle, meta, ctx, threshold=0.85, today=TODAY)
    assert person.last_name is None
    assert ("person.last_name", "MISSING_VALUE") in codes(val)
    assert not val.passed


def test_clean_documents_pass_except_owner_info():
    ide = parse_identity(make_doc(CI_ROWS))
    reg = parse_registration(make_doc(TALON_ROWS))
    person, vehicle, meta, ctx = build_from_extraction(ide, reg)
    val = validate_payload(person, vehicle, meta, ctx, threshold=0.85, today=TODAY)
    assert vehicle.first_registration == "2020-03-10"
    assert person.identity_document.expiry_date == "2030-01-01"
    assert val.passed, [i.code for i in val.issues if i.severity != "info"]
    assert {i.code for i in val.issues} == {"OWNER_NOT_STATED"}


def test_partially_read_holder_name_is_flagged():
    ide = parse_identity(make_doc(CI_ROWS))
    rows = [r for r in TALON_ROWS if not (isinstance(r, list) and r[0][1] == "C.1.2")]
    reg = parse_registration(make_doc(rows))
    assert reg.holder_partial and reg.holder_name.value == "IONESCU"
    person, vehicle, meta, ctx = build_from_extraction(ide, reg)
    val = validate_payload(person, vehicle, meta, ctx, threshold=0.85, today=TODAY)
    assert ("vehicle.certificate_holder.name", "HOLDER_NAME_INCOMPLETE") in codes(val)
    assert meta["vehicle.certificate_holder.name"].review_required


def test_company_holder_without_given_name_is_not_partial():
    rows = list(TALON_ROWS)
    rows[4] = [(60, "C.1.1"), (200, "SC EXEMPLU FLOTA SRL"), (1250, "P.1"), (1360, "999")]
    rows = [r for r in rows if not (isinstance(r, list) and r[0][1] == "C.1.2")]
    assert not parse_registration(make_doc(rows)).holder_partial


def test_oneocr_segments_are_grouped_into_rows_even_when_tilted():
    import math

    from app.ocr.oneocr import group_into_rows

    def seg(text, x, y, angle=0.0, w=200, h=30):
        # quad corners of an axis box rotated around the origin by `angle`
        t = math.radians(angle)
        pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        rot = [(px * math.cos(t) - py * math.sin(t), px * math.sin(t) + py * math.cos(t)) for px, py in pts]
        return [(text, 0.99, tuple(c for p in rot for c in p))]

    # label row with two columns, then value row; image tilted 3 degrees
    raw = [seg("Nume/Nom/Last", 490, 280, 3), seg("Sex/Sexe/Sex", 1450, 280, 3),
           seg("IONESCU", 490, 320, 3), seg("M", 1450, 320, 3)]
    rows = group_into_rows(raw, 3.0)
    assert [ln.text for ln in rows] == ["Nume/Nom/Last Sex/Sexe/Sex", "IONESCU M"]


# --- real-world layouts (structure copied from real documents, ALL VALUES FICTITIOUS) ---

def _td1(docnum="ZZ1234567", cnp="1800101400016", dob="800101", sex="M", exp="350101"):
    from app.parsing.mrz import check_digit

    l1 = "IDROU" + docnum + str(check_digit(docnum)) + cnp + "<<"
    l2 = dob + str(check_digit(dob)) + sex + exp + str(check_digit(exp)) + "ROU" + "<" * 11
    l2 += str(check_digit(l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29]))
    return l1, l2


CEI_ROWS = [
    "RO ROMÂNIA CARTE DE IDENTITATE",
    "ROMANIA IDENTITY CARD",
    [(490, "Nume /Surname")],
    [(490, "IONESCU")],
    [(490, "Prenume / Given names")],
    [(490, "ALEX-ION")],
    [(490, "Sex / Sex"), (700, "Cetatenie / Nationality"), (1100, "Data nasterii / Date of birth")],
    [(490, "M"), (700, "ROU"), (1100, "01 01 1980")],
    [(490, "CNP / PIN")],
    [(490, "1800101400016")],
    [(490, "Nr. document / Document no."), (1100, "Data expirării / Date of expiry")],
    [(490, "ZZ1234567"), (1100, "01 01 2035")],
]


def test_cei_front_and_back_layout():
    l1, l2 = _td1()
    ide = parse_identity(make_doc(CEI_ROWS + [l1, l2, "IONESCU<<ALEX<ION<<<<<<<<<<<<<<"]))
    assert ide.document_type == "CEI"
    assert (ide.last_name.value, ide.first_name.value) == ("IONESCU", "ALEX-ION")
    assert (ide.series.value, ide.number.value) == ("ZZ", "1234567")
    assert ide.expiry_date.value == "01.01.2035"
    assert ide.national_id.value == "1800101400016" and "mrz_match" in ide.national_id.checks
    assert ide.mrz.format == "TD1" and ide.mrz.document_number_valid and ide.mrz.composite_valid
    person, vehicle, meta, ctx = build_from_extraction(ide, None)
    val = validate_payload(person, vehicle, meta, ctx, threshold=0.85, today=TODAY)
    assert person.identity_document.expiry_date == "2035-01-01"
    assert ("person.address", "ADDRESS_NOT_ON_DOCUMENT") in codes(val)
    assert not any(i.field.startswith("person.identity_document") for i in val.issues if i.severity != "info")


def test_cei_front_only_without_mrz():
    ide = parse_identity(make_doc(CEI_ROWS))
    assert ide.document_type == "CEI"
    assert (ide.series.value, ide.number.value) == ("ZZ", "1234567")


def test_cei_cnp_falls_back_to_mrz_when_visual_zone_unreadable():
    l1, l2 = _td1()
    rows = [r for r in CEI_ROWS if r != [(490, "1800101400016")]]
    ide = parse_identity(make_doc(rows + [l1, l2]))
    assert ide.national_id.value == "1800101400016" and ide.national_id.source == "identity.MRZ"


def test_cedilla_diacritics_normalised_to_comma_below():
    rows = list(CI_ROWS)
    rows[4] = [(490, "ŞTEFĂNESCU"), (1450, "M")]
    ide = parse_identity(make_doc(rows))
    assert ide.last_name.value == "ȘTEFĂNESCU"


TALON_NEW_ROWS = [  # 2024+ certificate: owner block C.2 + "C2=C1" box, codes mid-line
    "A ZZ-99-TST B 01.02.2010 H ANEXA",
    "J AUTOTURISM M1 01.02.2024 1.1 01.02.2024 NR X00000000V",
    "0.1 DACIA F.1 1500 G 1100 Numarul de inmatriculare ZZ-99-TST",
    "D.2 ABC DEF P.1 1461 P.2 66 INSPECȚII TEHNICE PERIODICE",
    "D.3 LOGAN P.3 MOTORINA Q x",
    "E UU1TEST9X00000009 R GRI",
    "K e2*2007/46*0000*00 S.1 5 S.2",
    [(60, "C.2 C.2.1 POPESCU"), (700, "V.7 NEDC:120")],
    [(60, "C.2.2 ANA MARIA"), (700, "Observații XX000")],
    [(60, "C.2.3 Str. EXEMPLU Nr. 1 mun")],
    [(80, "TESTENI Jud. TEST"), (700, "FILTRU DE PARTICULE")],
    [(300, "C2=C1")],
    "C.3C.3.1",
    "C3=C1",
    # back side / page 2 legend must not leak into the fields
    "(A) Numărul de înmatriculare (B) Data primei înmatriculări a vehiculului",
    "(C.1) Posesorul certificatului de înmatriculare: (C.1.1) Numele de familie sau",
    "(D.1) Marca (D.2) Tipul (D.3) Descrierea comercială",
    "E) Numărul de identificare al vehiculului (R) Culoarea vehiculului (S.1) Număr Certificat",
]


def test_new_format_talon_with_legend_and_c2_eq_c1():
    reg = parse_registration(make_doc(TALON_NEW_ROWS))
    assert reg.registration_number.value == "ZZ99TST"
    assert reg.first_registration.value == "01.02.2010"
    assert reg.category.value == "M1"
    assert (reg.make.value, reg.vehicle_type.value, reg.model.value) == ("DACIA", "ABC DEF", "LOGAN")
    assert reg.vin.value == "UU1TEST9X00000009" and reg.color.value == "GRI"
    assert (reg.engine_cc.value, reg.power_kw.value, reg.fuel.value, reg.seats.value) == (1461, 66, "DIESEL", 5)
    assert reg.owner_name.value == "POPESCU ANA MARIA"
    assert reg.owner_address.value == "Str. EXEMPLU Nr. 1 mun TESTENI Jud. TEST"
    assert reg.holder_name.value is None  # never copied from the owner
    assert reg.c2_eq_c1_box
    person, vehicle, meta, ctx = build_from_extraction(None, reg)
    val = validate_payload(person, vehicle, meta, ctx, threshold=0.85, today=TODAY)
    issue = next(i for i in val.issues if i.code == "HOLDER_SEE_C2_EQ_C1")
    assert issue.suggestion == "POPESCU ANA MARIA"
    assert vehicle.certificate_holder is None


def test_colour_not_taken_from_legend_words():
    rows = [r for r in TALON_NEW_ROWS if r != "E UU1TEST9X00000009 R GRI"] + ["E UU1TEST9X00000009"]
    reg = parse_registration(make_doc(rows))
    assert reg.color.value is None  # "NUMĂR CERTIFICAT" in the legend is not a colour


def test_partially_read_owner_and_bad_category_are_flagged():
    rows = [r for r in TALON_NEW_ROWS if not (isinstance(r, list) and r[0][1].startswith("C.2 C.2.1"))]
    rows = [r if r != "J AUTOTURISM M1 01.02.2024 1.1 01.02.2024 NR X00000000V" else "J AUTOTURISM MI" for r in rows]
    reg = parse_registration(make_doc(rows))
    assert reg.owner_partial and reg.owner_name.value == "ANA MARIA"
    person, vehicle, meta, ctx = build_from_extraction(None, reg)
    val = validate_payload(person, vehicle, meta, ctx, threshold=0.85, today=TODAY)
    assert ("vehicle.legal_owner.name", "OWNER_NAME_INCOMPLETE") in codes(val)
    assert ("vehicle.category", "CATEGORY_UNUSUAL") in codes(val) or vehicle.category is None


def test_one_letter_name_is_flagged():
    from app.validation import validators as v

    assert v.validate_name("S", "Nume").code == "NAME_TOO_SHORT"
    assert v.validate_name("IONESCU", "Nume").valid


def test_identity_type_without_evidence_is_flagged():
    ide = parse_identity(make_doc(["CARTE DE IDENTITATE", "IDENTITY CARD", "Nume", "IONESCU", "1800101400016"]))
    assert not ide.type_evidence
    person, vehicle, meta, ctx = build_from_extraction(ide, None)
    val = validate_payload(person, vehicle, meta, ctx, threshold=0.85, today=TODAY)
    assert ("person.identity_document.type", "DOCUMENT_TYPE_UNCERTAIN") in codes(val)
    assert parse_identity(make_doc(CI_ROWS)).type_evidence


def test_damaged_cei_mrz_is_not_evidence_for_the_1997_card():
    l1, l2 = _td1()
    rows = ["CARTE DE IDENTITATE", "Nume", "IONESCU", l1[:12] + "#####" + l1[17:], l2]  # line 1 damaged
    ide = parse_identity(make_doc(rows))
    assert ide.document_type == "CEI" or not ide.type_evidence


def test_name_with_card_header_text_is_flagged():
    from app.validation import validators as v

    assert v.validate_name("ROMANIAS", "Nume").code == "NAME_LOOKS_LIKE_LABEL"
    assert v.validate_name("ROMANESCU", "Nume").valid
