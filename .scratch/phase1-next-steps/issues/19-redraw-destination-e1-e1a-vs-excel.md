Type: grilling
Status: open
Blocked by: 10

## Question

**Destination-level scoping decision, opened 2026-07-23.** Real client documents this
session revealed the actual deliverable is filled Austrian **E1/E1a** government PDFs
(Kennzahl-coded, filed via FinanzOnline) — contradicting the map's prior assumption
(and CLAUDE.md / dev spec §8) that the output is a per-client `EA_2025.xlsx`.

Decide how this redraws the map's Destination:

- **(A) E1/E1a supersedes Excel** — the gov PDFs become THE output. Tickets 10/11 pivot
  fully to E1/E1a; the `EXCEL_CELL_MAP` + Excel-writer in `backend/main.py` and the
  `EA_2025_template.xlsx` become legacy/unused (move the Excel workstream to Out of scope).
- **(B) Both** — keep the Excel as an intermediate **calculation** sheet (its
  `Gewinn`/`Grundfreibetrag`/`Einkünfte` formulas do real work), and add E1/E1a PDF fill
  as the final client-facing deliverable on top.

**Why this is blocked (not just undecided):** the choice hinges on whether any real
*calculation* happens between the intake fields and the filed return — which is domain
knowledge only the client has, and which the user explicitly does not know (grilled
2026-07-23). Ticket 10 now asks the client for their real filing process precisely to
unblock this. If it turns out E1a itself carries the computed figures (KZ 9040 etc. are
the profit numbers), the Excel is likely redundant → lean (A); if they run a separate
calc sheet first, lean (B).

Resolve by grilling once ticket 10's answer is in hand. Do not pick (A)/(B) before then.

## Answer

(pending — blocked on client's real filing process, ticket 10)
