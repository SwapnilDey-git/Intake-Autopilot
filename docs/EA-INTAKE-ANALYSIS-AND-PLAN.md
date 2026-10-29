# EA Intake — Analysis & Plan

Grounded in a structural survey of the real client folders (18 people, 649 files)
and the structure/formulas of 4 real `EA {year}.xlsx` sheets. **No client figures
appear in this document** — only the template skeleton and generic formula patterns.

## 1. Problem statement

Svolkmann Consulting files Austrian taxes for Romanian 24h-carers
(Personenbetreuer). Clients send piles of documents (forms, bills, certificates,
correspondence) over email/WhatsApp. Today a person at the practice reads the whole
pile by hand and produces the deliverable: the **Einnahmen-Ausgaben-Rechnung**
(`EA {year}.xlsx`) — a one-page income/expense statement whose totals feed the
official forms. **We are automating pile-of-documents → filled EA, per person per
year, with a human review gate before anything is trusted.**

## 2. What the real data looks like

- **Per person, multi-year, messy.** ~36 files/person (median 32, max 94). Tax years
  **2021–2026 mixed flat** in one folder; the year lives in the **filename**, not the
  folder. Half the folders use category subfolders (`Bescheide/`, `belege/`, `daten/`),
  half are flat or organized by FA-submission date.
- **Phone-camera intake.** ~40% of files are photos; 188 are "WhatsApp Image" captures
  of receipts, notes, and correspondence.
- **The tax forms are present** — E1a (33), E1 (31), L1k (10), E9 (5), Bescheide (26).
- **The deliverable already exists for past years** — 28 real `EA {year}.xlsx`, 16 of
  18 people. This is both our real template source and a **gold set to validate against**.
- **A spouse/household dimension exists** (E9 "Ehemann" certs, family sub-cases).

## 3. The EA is a SUMMARY, not itemized  (the crux, resolved)

Verified across 4 clients, the structure is consistent:

```
Header:   Name | StNr | Austrian address | Versnr (e-card)
          Romanian hometown + distance (km) | Tel | Email
Income:   Leistungserlöse            = sum of monthly Honorare
Expenses: Sozialversicherung   9225
          Kleinmaterial        9100
          Provisionen          9190
          Abschreibung         9130
          Sonstiger Aufwand    9230
          Reisekosten          9160   = km × 2 × 0.42 × trips   (deterministic)
Calc:     Aufwand gesamt              = SUM(expenses)
          Gewinn                      = Leistungserlöse − Aufwand
          15% Grundfreibetrag  9221   = Gewinn × 0.15
          Einkünfte a. Gewerbebetrieb = Gewinn − Grundfreibetrag
Footer:   Familienstand | Ehemann (name+DOB) | Kinder (name+DOB)
```

So "do all the calculations" = fill **one income figure + six expense figures +
household info**, and the sheet's own formulas produce Gewinn/Grundfreibetrag/
Einkünfte. This is tractable — it is NOT a receipt-itemization problem.

**Where each figure comes from (inference — to confirm with the practice):**
| EA line | Likely source document |
|---|---|
| Leistungserlöse (income) | monthly agency payments / Honorarnoten / income records |
| Sozialversicherung 9225 | SVS annual statement |
| Provisionen 9190 | agency commission statement |
| Reisekosten 9160 | km (per-person, known) × trips/year (small integer, needs input) |
| Kleinmaterial / Abschreibung / Sonstiger Aufwand | receipts, or standard/estimated — **OPEN** |
| Familienstand / Ehemann / Kinder | E9 / family docs / prior filing |

## 4. Two structural constraints on the build

1. **Generate from ONE canonical template.** The real sheets are hand-tailored per
   client (different sheet names, shifted rows, sometimes several people's years as
   tabs in one workbook). Writing into a client's own sheet by fixed cell coordinates
   is unsafe. We build a canonical EA template matching the real structure and
   generate a fresh `EA_{year}.xlsx` per (person, year).
2. **Our reconstructed template is incomplete** — missing `Kleinmaterial 9100` and
   `Abschreibung 9130`. Adopt the real structure (all six Kennzahlen).

## 5. Plan (phased)

**Phase 0 — Canonical EA template + calc.** Rebuild the template from the real
structure (six Kennzahlen, household footer, identity header). Fix `EXCEL_CELL_MAP`
to it. Deterministic Reisekosten already matches. *Low risk, high value, unblocked.*

**Phase 1 — Person → Year → Documents data model (ADR-0001).** Schema gains a
`clients` (person) level and a `tax_years` level; submissions become attach-points.
Folder import = one person per folder; live email/WhatsApp routes to a person.

**Phase 2 — Multi-doc extraction & per-year merge.** Classify each file (tax form /
SVS / agency-income / Bescheid / receipt-photo / junk), assign its year
(filename → content), and extract the ~8 EA figures from the RIGHT source docs, merged
into one per-(person, year) record. Flag conflicts for review.

**Phase 3 — Dashboard per-person/per-year review + EA generation.** Person → years →
docs; reviewer confirms the ~8 figures; generate `EA_{year}.xlsx` from the canonical
template. Human gate stays mandatory.

**Phase 4 (later) — Drafting.** Aufhebung §299 / Wiederaufnahme §303 / Beschwerde /
Ergänzungsersuchen replies, per person per year. Separate phase; the data model above
is designed to carry it.

## 6. Validation

28 real past EA sheets are a gold set. For a past year, run the pipeline and compare
the computed figures against the real sheet. Per the standing privacy rule, the
numeric comparison is run locally by the practice/user — not read out by the assistant.

## 7. Decisions — resolved from the data (2026-08-20)

Inferred from the real EA sheets' formula patterns (structure only, no figures)
and the filename/doc-type corpus:

- **Income (Leistungserlöse)** = **sum of monthly agency payments** (the income
  formula is a sum of 4–7 monthly terms). Source docs: `honorar` / agency schedule.
- **Reisekosten** = **km × 2 × 0.42 × trips**, trips a small **client-stated integer,
  reviewer-entered** (exactly the current backend logic); km from the person's known
  Romanian-hometown distance. Not receipt-derived.
- **Soft expense lines (Kleinmaterial / Abschreibung / Sonstiger Aufwand)** = a short
  hand-assembled sum of **2–5 items** (a standard monthly-recurring item + a few
  receipts), **not** bulk itemization → **reviewer enters a figure per line**;
  receipt-suggestion is a later nicety, not required.
- **Person-matching** for live channels = **by sender identity (email/phone), else
  left unbound for manual assignment**; folder import binds by name. (Implemented.)
- **Year assignment** = **trusted filename year for named docs; suppressed for photos**
  (a photo's filename year is its capture date, not the tax year) → photos defer to
  content/manual. (Implemented; validated on the real corpus.)
- **Merge-conflict resolution** (same field, two docs) — deferred to Phase 2 core:
  precedence by doc type (E1a > E1 for business figures; SVS statement for 9225; etc.)
  with disagreements flagged for the reviewer.

### Where each EA figure is sourced (doc-type → EA line)
| EA line (Kennzahl) | Source doc type |
|---|---|
| Leistungserlöse | honorar / agency payment schedule |
| Sozialversicherung 9225 | svs |
| Provisionen 9190 | honorar / agency (commission) |
| Reisekosten 9160 | computed (km × 2 × 0.42 × trips) |
| Kleinmaterial 9100 / Abschreibung 9130 / Sonstiger Aufwand 9230 | receipts (reviewer-entered) |
| Familienstand / Ehemann / Kinder | e9 / fambh / prior EA |

## 8. Build status (2026-08-20)

- **Phase 0** ✓ canonical EA template + backend cell map (tested).
- **Phase 1** ✓ clients / tax_years / client_identities schema (applied to dev DB).
- **Phase 2 scaffold** ✓ filename year detection (photo-aware), per-person routing +
  per-year binding at ingest, `GET /api/clients` + `/api/clients/{id}`, and
  `scripts/import_person_folder.py`. Validated end-to-end on synthetic data.
- **Phase 3a** ✓ read-only person/year dashboard (`/clients`, `/clients/[id]`),
  cross-linked from the reviewer. Verified via build/lint/SSR (in-browser screenshot
  blocked by a local Chrome-extension fault, not the app).
- **Phase 2 core** ✓ `merge_year_fields()` (doc-type precedence + conflict flagging,
  de-DE number reconciliation, field aliases) → `_rebuild_year_record()` into
  `tax_years.ea_fields`; content-based year rebind on extraction (photos get their year
  from the form's `tax_year`); `GET /api/tax-years/{id}` + `POST /api/tax-years/{id}/generate`
  (writes EA_{year}.xlsx from the canonical template, reisekosten computed). Merge
  unit-tested; both endpoints tested end-to-end (generated sheet cells + formulas verified).
- **Phase 3b** ✓ client-scoped per-year EA reviewer at `/clients/[id]`: client name +
  counts top-left; documents grouped by tax year in the left rail; DocPreview of the
  selected document in the middle; right panel = that document's YEAR EA record —
  editable identity/income/expense/household fields with **conflict badges**, live
  Gewinn/Grundfreibetrag/Einkünfte, Reviewed-by, and a **Generate EA {year}** button
  (POST `/api/tax-years/{id}/generate`, money coerced to numbers so the sheet formulas
  compute). Build + lint clean; data endpoints verified. (In-browser screenshot still
  blocked by the local Chrome-extension fault, not the app.)

- **Next** — real folder import to validate the full extraction→merge→EA chain on genuine
  data; then fold all of this into the client update package.
