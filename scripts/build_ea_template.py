"""Generate the canonical EA (Einnahmen-Ausgaben-Rechnung) template.

Rebuilt from the STRUCTURE of the practice's real EA sheets (labels + formulas
only were inspected; no client figures). The real sheets are hand-tailored per
client (different sheet names, shifted rows, sometimes several people's years as
tabs in one workbook), so we do NOT write into a client's own sheet by fixed
coordinates -- we generate a fresh EA_{year}.xlsx per (person, year) from THIS
canonical template. Keep this generator and backend/main.py's EXCEL_CELL_MAP in
lockstep: the coordinates below are the contract.

Layout (sheet "EA"), values live in column C:

  C1  tax_year
  C3  name              C4 StNr.        C5 Versnr (e-card)
  C6  address (AT)      C7 hometown     C8 distance km
  C9  tel              C10 email
  C12 Leistungserlöse (income)
  C13 Sozialversicherung 9225
  C14 Kleinmaterial      9100
  C15 Provisionen        9190
  C16 Abschreibung       9130
  C17 Sonstiger Aufwand  9230
  C18 Reisekosten        9160   (computed: km x 2 x 0.42 x trips, cap 6000)
  C19 Aufwand gesamt          = SUM(C13:C18)
  C20 Gewinn                  = C12 - C19
  C21 15% Grundfreibetrag 9221= MAX(0, C20 * 0.15)   (never on a loss)
  C22 Einkünfte a. Gewerbeb.  = C20 - C21
  C24 Familienstand   C25 Ehemann/Ehefrau   C26 Kinder
"""
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment

OUT = Path(__file__).resolve().parent.parent / "backend" / "templates" / "EA_template.xlsx"

bold = Font(bold=True)


def main() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "EA"

    def label(coord, text, b=False):
        ws[coord] = text
        if b:
            ws[coord].font = bold

    # --- Title / year ---------------------------------------------------
    label("A1", "Einnahmen-Ausgaben-Rechnung", b=True)
    label("B1", "Jahr")
    # C1 = tax_year (filled on approval)

    # --- Identity header ------------------------------------------------
    label("A3", "Name")
    label("A4", "StNr.")
    label("A5", "Versnr. (E-Card)")
    label("A6", "Adresse (AT)")
    label("A7", "Heimatort")
    label("A8", "Entfernung (km)")
    label("A9", "Tel")
    label("A10", "Email")

    # --- Income + six expense Kennzahlen --------------------------------
    label("A12", "Leistungserlöse", b=True)
    label("A13", "Sozialversicherung"); label("B13", "9225")
    label("A14", "Kleinmaterial");      label("B14", "9100")
    label("A15", "Provisionen");        label("B15", "9190")
    label("A16", "Abschreibung");       label("B16", "9130")
    label("A17", "Sonstiger Aufwand");  label("B17", "9230")
    label("A18", "Reisekosten");        label("B18", "9160")

    # --- Calc block (formulas -- never written by the backend) ----------
    label("A19", "Aufwand gesamt", b=True)
    ws["C19"] = "=SUM(C13:C18)"
    label("A20", "Gewinn", b=True)
    ws["C20"] = "=C12-C19"
    label("A21", "15% Grundfreibetrag"); label("B21", "9221")
    ws["C21"] = "=MAX(0,C20*0.15)"
    label("A22", "Einkünfte aus Gewerbebetrieb", b=True)
    ws["C22"] = "=C20-C21"

    # --- Household footer (AVAB / Kindermehrbetrag) ---------------------
    label("A24", "Familienstand")
    label("A25", "Ehemann/Ehefrau")
    label("A26", "Kinder")

    # cosmetics: widen the label + value columns
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 8
    ws.column_dimensions["C"].width = 28
    for coord in ("C7", "C8"):
        ws[coord].alignment = Alignment(horizontal="left")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
