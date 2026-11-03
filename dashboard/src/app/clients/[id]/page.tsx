"use client";

// Client-scoped, per-year EA reviewer (ADR-0001 / Phase 3b).
// Three panes, like the case reviewer, but keyed to a PERSON:
//   left   — the client's name + all their documents, grouped by tax year
//   middle — preview of the selected document (the thing being parsed)
//   right  — the EA record for the selected document's YEAR: the ~8 figures the
//            sheet needs, editable, with live Gewinn/Grundfreibetrag/Einkünfte and
//            a "Generate EA" action that writes EA_{year}.xlsx.

import { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";

// PDF.js touches browser-only globals at import, so keep the preview client-only.
import FragebogenInvite from "./FragebogenInvite";
import UploadToCase from "../../UploadToCase";
const DocPreview = dynamic(() => import("../../DocPreview"), { ssr: false });

const BACKEND = "http://localhost:8080";

type YearRow = { id: number; year: number; status: string; ea_path: string | null };
type DocRow = {
  id: number;
  filename: string;
  display_name: string;
  doc_type: string | null;
  role: string;
  doc_year: number | null;
  tax_year_id: number | null;
  status: string;
};
type Detail = {
  client: { id: number; display_name: string | null };
  years: YearRow[];
  documents: DocRow[];
};
type EAField = {
  value: unknown;
  source_doc_type?: string;
  source_form_id?: number;
  conflict?: boolean;
  inherited?: boolean;   // stable identity field carried over from another year's doc
  alternatives?: { value: unknown; doc_type: string }[];
  superseded?: { value: unknown; doc_type: string }[];  // older copy of the same form, overridden by the newer one
  // client's handwritten working for a money field: "calc" = total taken after the last "=",
  // "multi" = several amounts, no single result -> reviewer must decide
  calc?: { raw: string; kind: "calc" | "multi" | "not_in_text"; calc_ok?: boolean | null; computed?: boolean };
  km_note?: string;
};
type YearRecord = {
  id: number;
  year: number;
  status: string;
  dringend?: boolean;
  ea_path: string | null;
  ea_fields: { fields?: Record<string, EAField> } | null;
};

const DOC_TYPE_LABELS: Record<string, string> = {
  e1a: "E1a", e1: "E1", l1k: "L1k", steuererklaerung: "Steuererklärung",
  bescheid: "Bescheid", honorar: "Honorar", svs: "SVS", fambh: "Familienbeihilfe",
  gisa: "GISA", steuerkonto: "Steuerkonto", ergaenzung: "Ergänzungsersuchen",
  aufhebung: "Aufhebung", wiederaufnahme: "Wiederaufnahme", beschwerde: "Beschwerde",
  nachreichung: "Nachreichung", antrag: "Antrag", eingabe: "Eingabe",
  begruendung: "Begründung", zinsen: "Zinsen", signature: "Unterschrift",
  photo: "Foto", working_file: "Arbeitsdatei", other: "Sonstiges",
  intake_sheet: "Fragebogen", e9: "E9", vcf: "Kontakt",
  intake_form_paper: "Formular (handschriftlich)", photo_form: "Foto (Formular)", id_photo: "Ausweis/E-Card (Foto)",
  pdf_form: "Scan (Formular)", practice_invoice: "Kanzlei-Rechnung", intake_note: "Notiz (getippt)",
};
const docLabel = (t: string | null) => (t ? DOC_TYPE_LABELS[t] || t : "—");

// Right-panel field groups (German-facing — the practice works in German).
const FIELD_GROUPS: { title: string; fields: [string, string][] }[] = [
  { title: "Identität", fields: [
    ["name", "Name"], ["stnr", "StNr."], ["e_card_number", "Versnr. (E-Card)"],
    ["address_austria", "Adresse (AT)"], ["hometown", "Heimatort"], ["tel", "Tel"], ["email", "Email"],
  ]},
  { title: "Einnahmen / Ausgaben", fields: [
    ["honorare", "Leistungserlöse"], ["svs_sva", "Sozialversicherung 9225"],
    ["kleinmaterial", "Kleinmaterial 9100"], ["provisionen", "Provisionen 9190"],
    ["abschreibung", "Abschreibung 9130"], ["sonstiger_aufwand", "Sonstiger Aufwand 9230"],
  ]},
  { title: "Reise", fields: [
    ["travel_distance_km", "Entfernung (km)"], ["trip_count", "Fahrten/Jahr"],
    ["reisekosten", "Reisekosten 9160 (lt. E1a, ohne km/Fahrten)"],
  ]},
  { title: "Haushalt", fields: [
    ["marital_status", "Familienstand"], ["spouse", "Ehemann/Ehefrau"], ["children", "Kinder"],
  ]},
];
const ALL_FIELD_KEYS = FIELD_GROUPS.flatMap((g) => g.fields.map(([k]) => k));

// Mirrors backend _to_number: several numbers in one value (a handwritten
// "1.200€ + 300€") are ambiguous -> 0, never glued into one figure; 3-digit
// groups ("18,250", "2.000") are thousands.
function parseNum(v: unknown): number {
  if (v == null || v === "") return 0;
  if ((String(v).match(/\d[\d.,]*/g) || []).length > 1) return 0;
  let s = String(v).replace(/[^\d,.-]/g, "");
  if (!s) return 0;
  if (s.includes(",") && s.includes(".")) {
    s = s.lastIndexOf(",") > s.lastIndexOf(".") ? s.replace(/\./g, "").replace(",", ".") : s.replace(/,/g, "");
  } else if (s.includes(",") || s.includes(".")) {
    const sep = s.includes(",") ? "," : ".";
    const thousands = new RegExp(`^-?\\d{1,3}(?:\\${sep}\\d{3})+$`);
    // otherwise the LAST sep is the decimal, earlier ones thousands ("2,451,47")
    const i = s.lastIndexOf(sep);
    s = thousands.test(s) ? s.split(sep).join("") : s.slice(0, i).split(sep).join("") + "." + s.slice(i + 1);
  }
  return parseFloat(s) || 0;
}
const eur = (n: number) =>
  n.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function ClientReviewerPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [data, setData] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedDocId, setSelectedDocId] = useState<number | null>(null);
  const [yearRecord, setYearRecord] = useState<YearRecord | null>(null);
  const [editData, setEditData] = useState<Record<string, string>>({});
  const [reviewer, setReviewer] = useState("");
  const [busy, setBusy] = useState(false);
  const [genMsg, setGenMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // Load the client (name, years, documents).
  useEffect(() => {
    let live = true;
    fetch(`${BACKEND}/api/clients/${id}`)
      .then((r) => r.json())
      .then((d) => {
        if (!live) return;
        if (d.error) setError(d.error);
        else {
          setData(d);
          const first = d.documents?.[0]?.id ?? null;
          setSelectedDocId(first);
        }
      })
      .catch((e) => live && setError(String(e)));
    return () => { live = false; };
  }, [id]);

  // Keep the left rail's highlighted entry in view when selection changes via a
  // source-jump click (the target doc may be scrolled out of sight, e.g. a
  // different tax year).
  useEffect(() => {
    if (selectedDocId == null) return;
    document
      .querySelector(`[data-doc-id="${selectedDocId}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [selectedDocId]);

  const selectedDoc = data?.documents.find((doc) => doc.id === selectedDocId) || null;
  const activeTaxYearId = selectedDoc?.tax_year_id ?? null;
  const activeYear = selectedDoc?.doc_year ?? null;

  // Load the EA record for the selected document's year. When there's no active
  // year the render guards on activeTaxYearId, so we simply don't fetch (no need
  // to clear state synchronously in the effect body).
  useEffect(() => {
    if (!activeTaxYearId) return;
    let live = true;
    fetch(`${BACKEND}/api/tax-years/${activeTaxYearId}`)
      .then((r) => r.json())
      .then((rec: YearRecord) => {
        if (!live) return;
        setYearRecord(rec);
        setGenMsg(null);
        const f = rec.ea_fields?.fields || {};
        const next: Record<string, string> = {};
        for (const k of ALL_FIELD_KEYS) {
          const v = f[k]?.value;
          next[k] = v == null ? "" : String(v);
        }
        setEditData(next);
      })
      .catch(() => live && setYearRecord(null));
    return () => { live = false; };
  }, [activeTaxYearId]);

  // Documents grouped by year for the rail.
  const grouped = useMemo(() => {
    const m = new Map<string, DocRow[]>();
    (data?.documents || []).forEach((doc) => {
      const key = doc.doc_year != null ? String(doc.doc_year) : "unassigned";
      if (!m.has(key)) m.set(key, []);
      m.get(key)!.push(doc);
    });
    const keys = Array.from(m.keys()).filter((k) => k !== "unassigned").sort((a, b) => Number(b) - Number(a));
    if (m.has("unassigned")) keys.push("unassigned");
    return keys.map((k) => ({ key: k, docs: m.get(k)! }));
  }, [data]);

  // Live EA math (mirrors the sheet formulas) as a reviewer aid.
  const totals = useMemo(() => {
    const km = parseNum(editData.travel_distance_km);
    const trips = parseNum(editData.trip_count);
    // Same rule as /generate: km x trips when both are set, else the E1a figure.
    const reisekosten = km && trips ? Math.min(km * 2 * 0.42 * trips, 6000) : parseNum(editData.reisekosten);
    const income = parseNum(editData.honorare);
    const expenses =
      parseNum(editData.svs_sva) + parseNum(editData.kleinmaterial) + parseNum(editData.provisionen) +
      parseNum(editData.abschreibung) + parseNum(editData.sonstiger_aufwand) + reisekosten;
    const gewinn = income - expenses;
    const gfb = Math.max(0, gewinn * 0.15);
    return { reisekosten, aufwand: expenses, gewinn, gfb, einkuenfte: gewinn - gfb };
  }, [editData]);

  const totalDocs = data?.documents.length ?? 0;
  const totalForms = data?.documents.filter((d) => d.role === "primary").length ?? 0;
  const fieldMeta = yearRecord?.ea_fields?.fields || {};

  async function generate() {
    if (!activeTaxYearId) return;
    if (!reviewer.trim()) { setGenMsg({ ok: false, text: "Enter a reviewer name first." }); return; }
    setBusy(true); setGenMsg(null);
    try {
      const res = await fetch(`${BACKEND}/api/tax-years/${activeTaxYearId}/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewer_name: reviewer.trim(), fields: editData }),
      }).then((r) => r.json());
      if (res.success) {
        setGenMsg({ ok: true, text: `EA ${activeYear} generated → ${res.ea_path}` });
        // refresh the year record so status flips to 'generated'
        const rec = await fetch(`${BACKEND}/api/tax-years/${activeTaxYearId}`).then((r) => r.json());
        setYearRecord(rec);
      } else {
        setGenMsg({ ok: false, text: res.error || "Generation failed." });
      }
    } catch (e) {
      setGenMsg({ ok: false, text: String(e) });
    } finally {
      setBusy(false);
    }
  }

  // Explicit sign-off: flips the year to 'approved' (the FinanzOnline hand-off,
  // Phase 5). Only offered once the sheet is generated — you approve a concrete
  // EA, not a draft. Re-fetches so the status badge updates.
  async function approve() {
    if (!activeTaxYearId) return;
    if (!reviewer.trim()) { setGenMsg({ ok: false, text: "Enter a reviewer name first." }); return; }
    setBusy(true); setGenMsg(null);
    try {
      const res = await fetch(`${BACKEND}/api/tax-years/${activeTaxYearId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewer_name: reviewer.trim() }),
      }).then((r) => r.json());
      if (res.success) {
        setGenMsg({ ok: true, text: `EA ${activeYear} freigegeben — bereit für FinanzOnline.` });
        const rec = await fetch(`${BACKEND}/api/tax-years/${activeTaxYearId}`).then((r) => r.json());
        setYearRecord(rec);
      } else {
        setGenMsg({ ok: false, text: res.error || "Freigabe fehlgeschlagen." });
      }
    } catch (e) {
      setGenMsg({ ok: false, text: String(e) });
    } finally {
      setBusy(false);
    }
  }

  // Office override of the emergency flag (raise or clear). Reflects into the
  // client list's ordering/badge on its next load.
  async function toggleDringend() {
    if (!activeTaxYearId) return;
    const next = !yearRecord?.dringend;
    setBusy(true); setGenMsg(null);
    try {
      const res = await fetch(`${BACKEND}/api/tax-years/${activeTaxYearId}/dringend`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dringend: next, reviewer_name: reviewer.trim() || null }),
      }).then((r) => r.json());
      if (res.success) {
        setYearRecord((p) => (p ? { ...p, dringend: res.dringend } : p));
      } else {
        setGenMsg({ ok: false, text: res.error || "Konnte Dringend nicht ändern." });
      }
    } catch (e) {
      setGenMsg({ ok: false, text: String(e) });
    } finally {
      setBusy(false);
    }
  }

  // Refresh the client's documents after a manual upload, WITHOUT resetting the
  // reviewer's current selection (unlike the initial load). Newly filed docs are
  // created synchronously by the case ingest, so they appear right away; their
  // extraction fills in on a later open.
  function reloadClient() {
    fetch(`${BACKEND}/api/clients/${id}`)
      .then((r) => r.json())
      .then((d) => { if (!d.error) setData(d); })
      .catch(() => {});
  }

  return (
    <main className="container mx-auto flex min-h-screen flex-col p-6">
      <header className="mb-5 flex items-center justify-between">
        <Link href="/" className="text-sm text-accent transition-colors hover:text-accent-hover">
          ← Clients
        </Link>
        {data && (
          <div className="flex items-center gap-2">
          {/* Upload a returned form/questionnaire for THIS client — binds by
              client_id, routed through the shared case path (Phase 3). */}
          <UploadToCase clientId={data.client.id} label="Formular hochladen" onDone={reloadClient} />
          <FragebogenInvite clientId={data.client.id} year={activeYear} />
          {/* The client questionnaire, bound to this client (and the open year):
              its answers land here as a "Fragebogen" document and fill the EA record. */}
          <a
            href={`${BACKEND}/fragebogen?client=${data.client.id}${activeYear ? `&year=${activeYear}` : ""}`}
            target="_blank"
            rel="noopener"
            className="rounded-md border border-border px-3 py-1.5 text-sm text-ink transition-colors hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            Fragebogen {activeYear ?? ""} öffnen ↗
          </a>
          </div>
        )}
      </header>

      {error && (
        <div className="rounded-md border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
          Couldn&apos;t load client: {error}
        </div>
      )}

      {data && (
        <div className="grid min-h-0 flex-1 grid-cols-[260px_1fr_420px] gap-5">
          {/* LEFT: client name + documents grouped by year */}
          <aside className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-surface">
            <div className="border-b border-border px-4 py-3">
              <h1 className="truncate text-lg font-semibold text-ink">
                {data.client.display_name || `Client #${data.client.id}`}
              </h1>
              <p className="mt-0.5 font-mono text-xs text-ink-muted">
                {totalDocs} files · {totalForms} forms
              </p>
            </div>
            <nav className="min-h-0 flex-1 overflow-auto py-1">
              {grouped.map(({ key, docs }) => (
                <div key={key} className="px-2 py-1">
                  <div className="px-2 py-1 font-mono text-xs uppercase tracking-wide text-ink-faint">
                    {key === "unassigned" ? "Unassigned year" : key}
                  </div>
                  {docs.map((doc) => {
                    const sel = doc.id === selectedDocId;
                    return (
                      <button
                        key={doc.id}
                        data-doc-id={doc.id}
                        onClick={() => setSelectedDocId(doc.id)}
                        className={`flex w-full items-start gap-2 rounded-md px-2 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent ${
                          sel ? "border border-accent/50 bg-canvas" : "border border-transparent hover:bg-surface-hover"
                        }`}
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm text-ink">{doc.display_name}</span>
                          <span className="block font-mono text-[11px] uppercase tracking-wide text-ink-faint">
                            {docLabel(doc.doc_type)}
                            {doc.role === "primary" && <span className="text-accent"> · form</span>}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              ))}
            </nav>
          </aside>

          {/* MIDDLE: preview of the selected document */}
          <section className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-surface">
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <span className="truncate text-sm text-ink">{selectedDoc?.display_name || "No document"}</span>
              {selectedDoc && (
                <span className="shrink-0 rounded-sm border border-border px-2 py-0.5 font-mono text-[11px] uppercase text-ink-muted">
                  {docLabel(selectedDoc.doc_type)}
                </span>
              )}
            </div>
            <div className="min-h-0 flex-1">
              {selectedDoc ? (
                <DocPreview
                  key={selectedDoc.id}
                  url={`${BACKEND}/api/forms/${selectedDoc.id}/document`}
                  filename={selectedDoc.display_name}
                />
              ) : (
                <div className="p-6 text-sm text-ink-muted">Select a document.</div>
              )}
            </div>
          </section>

          {/* RIGHT: EA record for the selected document's year */}
          <section className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-surface">
            <div className="border-b border-border px-4 py-3">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-ink">
                  Einnahmen-Ausgaben-Rechnung {activeYear ?? ""}
                </h2>
                {activeTaxYearId && yearRecord && (
                  <div className="flex items-center gap-1.5">
                    <button
                      type="button"
                      onClick={toggleDringend}
                      disabled={busy}
                      title={yearRecord.dringend
                        ? "Als Notfall markiert — klicken, um die Markierung zu entfernen."
                        : "Als Notfall markieren (erscheint oben in der Klientenliste)."}
                      className={`rounded-sm border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide transition-colors disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                        yearRecord.dringend
                          ? "border-danger bg-danger text-canvas hover:bg-danger/90"
                          : "border-border text-ink-faint hover:border-danger hover:text-danger"
                      }`}
                    >
                      {yearRecord.dringend ? "● Dringend" : "Dringend?"}
                    </button>
                    <span className={`rounded-sm border px-2 py-0.5 font-mono text-[11px] uppercase ${
                      yearRecord.status === "approved"
                        ? "border-success/50 bg-success/10 text-success"
                        : "border-border text-ink-faint"
                    }`}>
                      {yearRecord.status === "approved" ? "freigegeben" : yearRecord.status}
                    </span>
                  </div>
                )}
              </div>
              <p className="mt-0.5 text-xs text-ink-muted">
                {activeYear ? "Confirm the figures, then generate the sheet." : "Document has no tax year yet."}
              </p>
            </div>

            {!activeTaxYearId ? (
              <div className="p-6 text-sm text-ink-muted">
                This document isn&apos;t bound to a tax year (usually an undated photo). Its year is set from
                the document content on extraction, or by hand.
              </div>
            ) : (
              <div className="min-h-0 flex-1 overflow-auto px-4 py-3">
                {FIELD_GROUPS.map((group) => (
                  <div key={group.title} className="mb-4">
                    <h3 className="mb-1.5 font-mono text-[11px] uppercase tracking-wide text-ink-faint">
                      {group.title}
                    </h3>
                    <div className="space-y-1.5">
                      {group.fields.map(([key, label]) => {
                        const meta = fieldMeta[key];
                        return (
                          <label key={key} className="block">
                            <span className="mb-0.5 block text-xs text-ink-muted">{label}</span>
                            <div className="flex flex-wrap items-center gap-2">
                            <input
                              value={editData[key] ?? ""}
                              onChange={(e) => setEditData((p) => ({ ...p, [key]: e.target.value }))}
                              className="min-w-0 flex-1 basis-40 rounded-md border border-border bg-canvas px-2 py-1 font-mono text-base tracking-wide text-ink [font-variant-numeric:tabular-nums] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                            />
                            {meta?.source_doc_type && (
                              <button
                                type="button"
                                disabled={!meta.source_form_id || meta.source_form_id === selectedDocId}
                                onClick={() => meta.source_form_id && setSelectedDocId(meta.source_form_id)}
                                title={
                                  meta.source_form_id && meta.source_form_id !== selectedDocId
                                    ? `${meta.inherited
                                        ? `Carried over from this person's ${docLabel(meta.source_doc_type)} in another year (identity fields are stable across years).`
                                        : `Read from the ${docLabel(meta.source_doc_type)} document (per-field authority).`
                                      } Click to open it in the preview.`
                                    : "This is the document currently open in the preview."
                                }
                                className="shrink-0 rounded-sm border border-border px-1.5 py-0.5 font-mono text-[10px] uppercase text-ink-faint transition-colors hover:border-accent hover:text-accent disabled:cursor-default disabled:hover:border-border disabled:hover:text-ink-faint"
                              >
                                {docLabel(meta.source_doc_type)}
                                {meta.inherited ? " ·prior yr" : ""}
                                {meta.source_form_id && meta.source_form_id !== selectedDocId ? " ↗" : ""}
                              </button>
                            )}
                            {meta?.conflict && (
                              <span
                                title={`Other sources disagree: ${(meta.alternatives || [])
                                  .map((a) => `${a.value} (${docLabel(a.doc_type)})`)
                                  .join(", ")}`}
                                className="shrink-0 rounded-sm border border-warning/50 px-1.5 py-0.5 text-[10px] uppercase text-warning"
                              >
                                conflict
                              </span>
                            )}
                            {(meta?.superseded || []).length > 0 && (
                              <span
                                title={`Newer document wins. Older version had: ${(meta?.superseded || [])
                                  .map((a) => `${a.value} (${docLabel(a.doc_type)})`)
                                  .join(", ")}`}
                                className="shrink-0 rounded-sm border border-border px-1.5 py-0.5 text-[10px] uppercase text-ink-faint"
                              >
                                newer
                              </span>
                            )}
                            {meta?.calc && (
                              <span
                                title={meta.calc.kind === "not_in_text"
                                  ? "Steht so nicht in der Notiz: vom Modell berechnet, bitte prüfen"
                                  : `Handschriftlich: ${meta.calc.raw}${
                                  meta.calc.kind === "multi"
                                    ? " — mehrere Beträge, kein Ergebnis: bitte Wert eintragen"
                                    : meta.calc.computed
                                      ? " — Ergebnis unvollständig gelesen: nachgerechneter Wert übernommen, bitte prüfen"
                                      : meta.calc.calc_ok === false
                                      ? " — Rechnung geht nicht auf"
                                      : " — Ergebnis nach dem letzten „=“ übernommen"
                                }`}
                                className={`shrink-0 rounded-sm border px-1.5 py-0.5 text-[10px] uppercase ${
                                  meta.calc.kind === "multi" || meta.calc.kind === "not_in_text" || meta.calc.calc_ok === false
                                    ? "border-warning/50 text-warning"
                                    : "border-border text-ink-faint"
                                }`}
                              >
                                {meta.calc.kind === "multi" || meta.calc.kind === "not_in_text" || meta.calc.calc_ok === false ? "prüfen" : "Rechnung"}
                              </span>
                            )}
                            {meta?.km_note && (
                              <span
                                title={`Auf dem Blatt steht auch „Kilometer ${meta.km_note}“ — Kilometergeld statt Transportkosten? Bitte prüfen`}
                                className="shrink-0 rounded-sm border border-warning/50 px-1.5 py-0.5 text-[10px] uppercase text-warning"
                              >
                                km {meta.km_note} · prüfen
                              </span>
                            )}
                            </div>
                            {meta?.conflict && (meta.alternatives || []).length > 0 && (
                              <div className="mt-1 flex flex-wrap gap-1.5 pl-0.5">
                                {(meta.alternatives || []).map((a, i) => (
                                  <button
                                    key={i}
                                    type="button"
                                    onClick={() => setEditData((p) => ({ ...p, [key]: String(a.value ?? "") }))}
                                    title={`Use this value instead (from ${docLabel(a.doc_type)})`}
                                    className="rounded-sm border border-warning/40 bg-warning/5 px-1.5 py-0.5 font-mono text-xs text-warning transition-colors hover:bg-warning/15"
                                  >
                                    {String(a.value ?? "")} <span className="text-[10px] uppercase text-warning/70">· {docLabel(a.doc_type)}</span>
                                  </button>
                                ))}
                              </div>
                            )}
                          </label>
                        );
                      })}
                    </div>
                  </div>
                ))}

                {/* Live computed block (mirrors the sheet formulas) */}
                <div className="mt-2 rounded-md border border-border bg-canvas p-3">
                  <div className="grid grid-cols-2 gap-y-1 font-mono text-xs">
                    <span className="text-ink-muted">Reisekosten 9160</span>
                    <span className="text-right text-ink">{eur(totals.reisekosten)}</span>
                    <span className="text-ink-muted">Aufwand gesamt</span>
                    <span className="text-right text-ink">{eur(totals.aufwand)}</span>
                    <span className="text-ink-muted">Gewinn</span>
                    <span className="text-right text-ink">{eur(totals.gewinn)}</span>
                    <span className="text-ink-muted">15% Grundfreibetrag</span>
                    <span className="text-right text-ink">{eur(totals.gfb)}</span>
                    <span className="font-semibold text-ink">Einkünfte a. Gewerbebetrieb</span>
                    <span className="text-right font-semibold text-ink">{eur(totals.einkuenfte)}</span>
                  </div>
                </div>
              </div>
            )}

            {/* Footer: reviewer + generate */}
            {activeTaxYearId && (
              <div className="border-t border-border px-4 py-3">
                {genMsg && (
                  <div
                    className={`mb-2 rounded-md border px-3 py-2 text-xs ${
                      genMsg.ok
                        ? "border-success/40 bg-success/10 text-success"
                        : "border-danger/40 bg-danger/10 text-danger"
                    }`}
                  >
                    {genMsg.text}
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <input
                    value={reviewer}
                    onChange={(e) => setReviewer(e.target.value)}
                    placeholder="Reviewed by"
                    className="min-w-0 flex-1 rounded-md border border-border bg-canvas px-2 py-2 text-sm text-ink placeholder:text-ink-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                  />
                  <button
                    onClick={generate}
                    disabled={busy}
                    className="shrink-0 rounded-md bg-success px-4 py-2 text-sm font-medium text-canvas transition-colors hover:bg-success-hover disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
                  >
                    {busy ? "…" : `Generate EA ${activeYear}`}
                  </button>
                  {/* Freigeben only after the sheet exists — you approve a concrete
                      EA, not a draft. Approving is the hand-off into FinanzOnline. */}
                  {yearRecord && (yearRecord.status === "generated" || yearRecord.status === "approved") && (
                    <button
                      onClick={approve}
                      disabled={busy || yearRecord.status === "approved"}
                      title={yearRecord.status === "approved"
                        ? "Bereits freigegeben."
                        : "Freigeben — EA ist geprüft und bereit zur Einreichung."}
                      className="shrink-0 rounded-md border border-success px-4 py-2 text-sm font-medium text-success transition-colors hover:bg-success/10 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-success"
                    >
                      {yearRecord.status === "approved" ? "✓ Freigegeben" : "Freigeben"}
                    </button>
                  )}
                </div>
              </div>
            )}
          </section>
        </div>
      )}
    </main>
  );
}
