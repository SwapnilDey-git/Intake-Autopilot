# CONTEXT — Domain glossary (intake-autopilot)

Shared vocabulary for the tax-intake pipeline. Glossary only — no implementation
details, no code. When a term here and the code disagree, the code is the bug.

Status of a term:
- **settled** — confirmed with the user (Sebastian's practice).
- **proposed** — my working definition, not yet confirmed.

---

## Client (Person) — *settled*
A single natural person the practice files for (mostly Romanian 24h-care workers).
The **top-level unit** of the system. One real-world folder = one Client. A Client
persists across many tax years and accumulates many Documents over time.
Supersedes the old idea of "case = one email." See ADR-0001.

## TaxYear — *settled*
A single assessment year for one Client (e.g. 2022, 2023, 2024). A Client owns many
TaxYears. The TaxYear is the unit that produces **one filled EA spreadsheet**. The
year is normally read from the **filename** (`E1a 2023 …`, `EA 2024.xlsx`), not from
a folder name. How to assign a year when the filename lacks one is still open.

## Document — *settled*
One file the Client sent (PDF, photo, scan, spreadsheet). Belongs to a Client and —
once its year is known — to a TaxYear. Every Document is **kept and filed**; only a
subset is sent to the extractor (see Tax-relevant document).

## Submission — *proposed*
One arrival event: an email, a WhatsApp batch, or a bulk folder import. A Submission
carries one or more Documents and must be **routed to a Client** (existing or new).
Replaces "case" as the thing an inbound email creates. A Submission is not itself the
unit of output — it just attaches Documents to a Client.

## Tax-relevant document — *settled*
A Document worth sending to the vision extractor: the core forms (E1, E1a, L1k),
income certificates (E9), and assessment notices (Bescheid). Everything else
(receipt photos, bank statements, junk, duplicates) is **filed but not extracted**.
This is the agreed meaning of "scan all files" — read everything that *matters* per
year, don't burn hours on every photo. See ADR-0001 / Q2.

## Primary form — *settled (pre-existing term)*
The one tax form per Document classified as the main extractable form. Historically
the extraction unit. Under the person/year model, primaries are still what the
extractor reads, but their **fields merge into the owning TaxYear's record** rather
than standing alone.

## Supporting document — *settled (pre-existing term)*
A Document filed alongside a primary that is not itself extracted (or only
lightly). Kept with the Client/TaxYear for the reviewer's reference.

## EA sheet (Einnahmen-Ausgaben-Rechnung) — *settled*
The practice's real Excel deliverable: one `EA {year}.xlsx` per Client per TaxYear,
a cash-basis income/expense statement. The client folders already contain real EA
sheets (`EA 2021.xlsx … EA 2024.xlsx`) — these become the **canonical template**,
replacing the reconstructed one. One EA sheet is produced per TaxYear.

## Per-year record — *proposed*
The merged set of extracted fields for one Client + one TaxYear, assembled from all
that year's Tax-relevant documents. Feeds one EA sheet and (later) the drafting layer.

## Household / Spouse — *proposed*
A Client may have a spouse/partner whose income (E9 certificate) is needed for
AVAB / Alleinverdienerabsetzbetrag and the Kindermehrbetrag. A gross→net rule applies
to E9 figures. Modeled as a second person linked to the Client. Out of scope for the
extraction phase; reserved for the drafting phase.

## Drafting (next phase) — *settled as out-of-scope-now*
Generating formal replies to the Finanzamt (Aufhebung §299 BAO, Wiederaufnahme §303,
Beschwerde, Ergänzungsersuchen replies), per Client + TaxYear, synthesizing across
Documents and years, human-in-the-loop, with a full version + a condensed
FinanzOnline version (often + Romanian translation). Explicitly the **next phase**;
the current data model must be able to carry it without a rewrite. See ADR-0001 / Q4.
