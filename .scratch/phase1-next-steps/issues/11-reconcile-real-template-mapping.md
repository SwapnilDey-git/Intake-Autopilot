Type: grilling
Status: open
Blocked by: 10, 19

## Question

**Rescoped 2026-07-23** — now that the real target is the government `E1`/`E1a` forms
(Kennzahl-coded), not the reconstructed Excel, this ticket is no longer "reconcile the
`.xlsx` cell map." It becomes: **build the real field mapping from intake fields → the
correct KZ (Kennzahl) codes on E1/E1a**, and decide the fill mechanism.

Once tickets 10 (real forms + filing process) and 19 (destination redraw: does E1/E1a
supersede or supplement the Excel) resolve:

1. Build the `intake-field → KZ` map against the **actual** E1/E1a forms (KZ 9040, 9160,
   9225, … as they appear on the real PDFs), replacing/superseding the guessed
   `EXCEL_CELL_MAP` in `backend/main.py`.
2. Resolve the two legacy Excel guesses (`svs_sva`, unmapped `A25`) only if ticket 19
   keeps the Excel as a real calc sheet; otherwise they retire with the Excel.
3. Decide the PDF-fill approach (e.g. `pypdf`/`pdftk` AcroForm field fill by KZ field
   name vs. flattened overlay) — this is a new implementation dependency the Excel path
   never had, and should be spun off into its own implementation ticket once the mapping
   is settled.

## Answer

(pending)
