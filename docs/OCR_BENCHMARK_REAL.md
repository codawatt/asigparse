# Benchmark OCR pe documente reale: OneOCR vs Tesseract

_Generat de `backend/scripts/benchmark_real.py` la 2026-11-12. Parser după corecțiile pentru layout-urile reale (CEI + MRZ TD1, talon nou cu legendă, reorientare automată OneOCR)._

Raport **anonimizat**: nu conține valori, nume de fișiere sau date personale. Documentele și valorile de referință sunt doar local, în `docs/acte/` (exclus din git).

## Set de date

| ID | Document | Sursă | Câmpuri verificate |
|---|---|---|---|
| CEI-1 | CEI (carte electronică) | scan PDF față+verso (card mic pe A4) | 8 |
| CEI-2 | CEI (carte electronică) | scan PDF față+verso (card mic pe A4) | 8 |
| CEI-3 | CEI (carte electronică) | captură de ecran, doar față, 552 px | 8 |
| CI97-1 | CI model 1997 | scan PDF (card mic pe A4) | 8 |
| CI97-2 | CI model 1997 | scan decupat PNG, 628 px | 8 |
| TAL-1 | Certificat înmatriculare | scan PDF 2 pagini (+ legendă) | 16 |
| TAL-2 | Certificat înmatriculare | captură de ecran, 900 px | 16 |
| TAL-3 | Certificat înmatriculare | fotografie telefon (perspectivă, umbră) | 16 |

8 fișiere, 88 câmpuri de referință per condiție, 9 condiții → 792 verificări per motor. Fiecare rulare trece prin tot fluxul (decodare → OCR → parsare → validare).

- **corect (strict)** = identic cu valoarea de pe act (inclusiv diacritice);
- **corect (normalizat)** = identic ignorând diacriticele, majusculele, spațiile și punctuația;
- **semnalat** = greșit/lipsă, dar marcat pentru verificare (operatorul e avertizat);
- **tăcut** = greșit și **nesemnalat**; cazul periculos.

## Rezumat (toate condițiile)

| Motor | Corect (normalizat) | Corect (strict) | Câmpuri critice corecte | Semnalate | **Tăcute** | Documente respinse | ms / document |
|---|---|---|---|---|---|---|---|
| oneocr | 77.0% | 70.1% | 81.9% | 174 | **8** | 6/72 | 644 |
| tesseract | 22.0% | 20.3% | 22.6% | 614 | **4** | 37/72 | 7362 |

## Pe condiție de captură (corect normalizat · tăcute · respinse)

| Condiție | oneocr | tesseract |
|---|---|---|
| `original` | 94.3% · 1 · 0 | 44.3% · 1 · 2 |
| `phone_photo` | 54.5% · 1 · 1 | 10.2% · 1 · 6 |
| `perspective` | 90.9% · 1 · 0 | 33.0% · 0 · 2 |
| `glare` | 95.5% · 1 · 0 | 29.5% · 1 · 2 |
| `dark_low_contrast` | 95.5% · 1 · 0 | 31.8% · 1 · 3 |
| `blur_2px` | 50.0% · 0 · 3 | 1.1% · 0 · 7 |
| `jpeg_q18` | 50.0% · 0 · 2 | 6.8% · 0 · 6 |
| `low_res_50pct` | 70.5% · 2 · 0 | 15.9% · 0 · 4 |
| `rotated_90` | 92.0% · 1 · 0 | 25.0% · 0 · 5 |

Condiții:

- `original`: fișierul exact cum a fost primit
- `phone_photo`: fundal, rotire 3,5°, blur 1,3 px, zgomot, scalare 65%, JPEG q70
- `perspective`: distorsiune trapez (~6%)
- `glare`: reflexie luminoasă eliptică
- `dark_low_contrast`: contrast ×0,45, luminozitate ×0,5
- `blur_2px`: blur gaussian 2,2 px
- `jpeg_q18`: scalare 60%, JPEG calitate 18
- `low_res_50pct`: rezoluție înjumătățită
- `rotated_90`: document rotit 90° (fotografiat lateral)

## Pe document, fișierul original (corect normalizat · ms)

| ID | Sursă | oneocr | tesseract |
|---|---|---|---|
| CEI-1 | scan PDF față+verso (card mic pe A4) | 100.0% · 827 ms | 62.5% · 4785 ms |
| CEI-2 | scan PDF față+verso (card mic pe A4) | 100.0% · 1299 ms | respins |
| CEI-3 | captură de ecran, doar față, 552 px | 100.0% · 406 ms | 75.0% · 2481 ms |
| CI97-1 | scan PDF (card mic pe A4) | 100.0% · 895 ms | 25.0% · 2542 ms |
| CI97-2 | scan decupat PNG, 628 px | 100.0% · 496 ms | 62.5% · 3391 ms |
| TAL-1 | scan PDF 2 pagini (+ legendă) | 87.5% · 3753 ms | 56.2% · 17496 ms |
| TAL-2 | captură de ecran, 900 px | 93.8% · 472 ms | 75.0% · 4521 ms |
| TAL-3 | fotografie telefon (perspectivă, umbră) | 87.5% · 518 ms | respins |

## Pe document, media tuturor condițiilor (corect normalizat)

| ID | oneocr | tesseract |
|---|---|---|
| CEI-1 | 94.4% | 19.4% (5 resp.) |
| CEI-2 | 94.4% | 8.3% (8 resp.) |
| CEI-3 | 58.3% (2 resp.) | 26.4% (5 resp.) |
| CI97-1 | 79.2% | 2.8% (8 resp.) |
| CI97-2 | 66.7% (1 resp.) | 27.8% (4 resp.) |
| TAL-1 | 89.6% | 39.6% |
| TAL-2 | 57.6% (3 resp.) | 31.2% (3 resp.) |
| TAL-3 | 79.9% | 7.6% (4 resp.) |

## Pe câmp (toate documentele și condițiile, corect normalizat)

| Câmp | oneocr | tesseract |
|---|---|---|
| `person.address` | 77.8% | 20.0% |
| `person.first_name` | 77.8% | 8.9% |
| `person.identity_document.expiry_date` | 77.8% | 20.0% |
| `person.identity_document.number` | 71.1% | 11.1% |
| `person.identity_document.series` | 71.1% | 11.1% |
| `person.identity_document.type` | 88.9% | 28.9% |
| `person.last_name` | 75.6% | 13.3% |
| `person.national_id` | 88.9% | 22.2% |
| `vehicle.category` | 74.1% | 25.9% |
| `vehicle.certificate_holder.name` | 0.0% | 0.0% |
| `vehicle.color` | 85.2% | 22.2% |
| `vehicle.engine_cc` | 85.2% | 48.1% |
| `vehicle.first_registration` | 81.5% | 40.7% |
| `vehicle.fuel` | 88.9% | 33.3% |
| `vehicle.legal_owner.address` | 55.6% | 7.4% |
| `vehicle.legal_owner.name` | 77.8% | 3.7% |
| `vehicle.make` | 85.2% | 37.0% |
| `vehicle.max_permissible_mass_kg` | 88.9% | 48.1% |
| `vehicle.model` | 85.2% | 14.8% |
| `vehicle.power_kw` | 88.9% | 51.9% |
| `vehicle.registration_number` | 85.2% | 14.8% |
| `vehicle.seats` | 81.5% | 7.4% |
| `vehicle.vehicle_type` | 74.1% | 25.9% |
| `vehicle.vin` | 74.1% | 37.0% |

_Detaliile per câmp, cu valori, sunt doar în jurnalul local `backend/benchmarks/real/details.log` (exclus din git)._

Motoare: Tesseract 5.5.3 (`--psm 6`, `ron+eng`); OneOCR: Copied from Snipping Tool 11.2608.41.0 (X64) on 2026-11-11T22:20:05.
