# ADR-0001 — Person-centric, per-year intake model

Status: accepted (2026-08-20)

## Context

The pipeline was built on "one email = one **case**." Real client data (the
`TAX DOCUMENT EXAMPLES` folders) is organized differently: one folder per **person**,
each spanning **multiple tax years**, containing **many documents** (E1, E1a, L1k,
E9, Bescheide, receipt photos, and the practice's own `EA {year}.xlsx` sheets), with
the **year encoded in filenames**, not folders. The practice's actual deliverable is
one Einnahmen-Ausgaben-Rechnung (EA sheet) **per person per year**, and — in a later
phase — formal legal replies drafted per person per year across documents.

The email-centric model can't express this: it has no place for a person who returns
year after year, no per-year rollup, and no merge of fields spread across several
forms in the same year.

## Decision

1. **Client (person) is the top-level unit.** A Client owns many **TaxYears**; a
   TaxYear owns many **Documents**. (Q1)
2. **"Scan all files" = read every *tax-relevant* document** (E1/E1a/L1k, E9,
   Bescheid), merged into a per-year record; file everything else without extracting
   it. Not every photo goes to the model. (Q2)
3. **Output is one EA sheet per Client per TaxYear**, using the practice's **real**
   `EA {year}.xlsx` as the canonical template, replacing the reconstructed one. (Q3)
4. **Scope split:** this phase delivers extract → dashboard → per-year EA. **Drafting**
   (Aufhebung/Beschwerde/Ergänzungsersuchen) is the **next phase**, but the data model
   is designed now to carry it (Client, TaxYear, Household/Spouse, per-year record). (Q4)

An inbound email/WhatsApp becomes a **Submission** that is *routed* to a Client rather
than becoming its own case.

## Consequences

- Schema gains a `clients` (person) level and a `tax_years` level; `cases`/submissions
  become attach-points, not the output unit.
- Extraction results merge per (client, year) instead of standing alone per form.
- The reconstructed EA template is retired in favor of a real client EA sheet.
- Live email intake needs a **person-matching** step (open sub-decision).
- Year assignment from filenames needs a fallback for undated files (open sub-decision).
- This is hard to reverse (touches DB schema, extraction merge, and Excel fill), which
  is why it is recorded here.
