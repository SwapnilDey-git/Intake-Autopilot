Type: task
Status: open

## Question

**Rescoped 2026-07-23** — the target output is not a custom Excel sheet. Real client
documents surfaced this session (from a collaborator, real Stabinger client relationship)
show the actual deliverable is **filled official Austrian tax forms — `E1` and `E1a`
(PDF, field-coded by "Kennzahl"/KZ: e.g. KZ 9040, 9160, 9225), filed via FinanzOnline**.
The current `backend/templates/EA_2025_template.xlsx` is a reconstruction from the dev
spec's §8 prose (two guessed cells: `svs_sva` → `D11` vs `B11`; the spec's `A25` target
has no mapped source field) — it may never have matched how the client actually files.

~~Request the client's actual `EA_2025.xlsx` file.~~ (Superseded by the above.)

**What to actually request from the client (client-side ask, not agent-drivable):**

1. **Their real filing process, step by step**: intake form → filed return. Specifically —
   do they type numbers straight into FinanzOnline's web forms, fill and upload the E1/E1a
   PDFs, or run a calculation first (Excel-style `Gewinn`/`Grundfreibetrag`/`Einkünfte`)
   and only then transcribe results into E1/E1a? (This is the exact question that blocks
   the destination decision — see ticket 19. The user does not currently know this.)
2. **The blank real forms**: current-year `E1` and `E1a` PDFs (or confirmation of which
   KZ fields they actually populate).
3. **Any real calculation sheet** they actually use, if one exists (the thing the dev-spec
   Excel was standing in for) — so we know whether the calc is load-bearing or vestigial.

Blocks the destination-redraw decision (ticket 19) and the mapping reconcile (ticket 11).

## Progress notes

**2026-07-15**: Old (Excel-only) framing sent to the client over WhatsApp, bundled with
tickets 07a and 12's asks. Awaiting response.

**2026-07-23**: Rescoped after the E1/E1a discovery (see above). The original "send us
EA_2025.xlsx" ask is too narrow — needs re-sending with the filing-process + E1/E1a
questions. Do NOT assume the Excel is the deliverable in any downstream work until this
comes back.

## Answer

(pending — waiting on client response)
