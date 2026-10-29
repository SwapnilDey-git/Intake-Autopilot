"use client";

import { useState, useEffect, useRef } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";

// PDF.js touches browser-only globals (DOMMatrix) at import, so keep the preview
// client-only — never server-prerendered.
const DocPreview = dynamic(() => import("../DocPreview"), { ssr: false });

// Types
type TravelSuggestion = {
  distance_km: number | null;
  missing_addresses: string[];
};

// Completeness verdict from the backend (wayfinder ticket 21). mandatory_fields is
// the single source of truth for which fields are required; the badge recomputes
// pass/fail live against editData so it clears as the reviewer fills a blank.
type Completeness = {
  is_complete: boolean;
  missing_fields: string[];
  mandatory_fields: string[];
};

// One attachment within a case. Primaries carry an extraction (json_result +
// completeness + travel_suggestion); supporting docs carry only identity/preview
// info. Every doc -- primary or supporting -- is previewable by form_id via
// GET /api/forms/{form_id}/document.
type Doc = {
  form_id: number;
  filename: string;
  doc_type: string | null;
  role: string; // 'primary' | 'supporting'
  status: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  json_result?: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  confidence?: any;
  error?: string;
  completeness?: Completeness;
  travel_suggestion?: TravelSuggestion;
};

// One submission (email / WhatsApp / upload) = one case. The queue lists cases,
// not individual files, so a 40-attachment email is ONE entry with its documents
// grouped, not 40 rows. Legacy single uploads are shown as synthetic one-doc cases
// (case_id < 0) so nothing disappears from the reviewer's view.
type Case = {
  case_id: number;
  source: string;
  sender?: string | null;
  subject?: string | null;
  client_name_guess?: string | null;
  status: string;
  documents: Doc[];
};

const NOT_FOUND_VALUES = new Set(["Not Found", "Unknown"]);

// Short human labels for the document-list rail. Falls back to the raw doc_type
// for anything unmapped, so a new keyword still renders sensibly.
const DOC_TYPE_LABELS: Record<string, string> = {
  e1: "E1", e1a: "E1a", l1k: "L1k", steuererklaerung: "Steuererklärung",
  bescheid: "Bescheid", honorar: "Honorar", fambh: "FamBH", svs: "SVS",
  gisa: "GISA", steuerkonto: "Steuerkonto", wiederaufnahme: "Wiederaufnahme",
  aufhebung: "Aufhebung", beschwerde: "Beschwerde", ergaenzung: "Ergänzung",
  nachreichung: "Nachreichung", antrag: "Antrag", begruendung: "Begründung",
  eingabe: "Eingabe", zinsen: "Zinsen", signature: "Signature",
  photo: "Photo", photo_form: "Photo (form)", pdf_form: "Scan (form)",
  working_file: "Working file", other: "Document",
};
const docLabel = (t: string | null | undefined) => (t && DOC_TYPE_LABELS[t]) || t || "Document";

// The model's self-reported confidence was empirically found to always be
// ~1.0 regardless of correctness (see wayfinder ticket 15) -- it isn't a
// usable signal, so instead of a live confidence banner we flag this fixed
// set of fields found to be unreliable, based on repeated testing against
// the same document. Revisit this list once ticket 12/13's real eval set
// gives broader evidence than one document.
const KNOWN_UNRELIABLE_FIELDS = ["e_card_number", "name", "honorare", "svs_sva"];

// Deterministic per-field shape checks -- the trustworthy half of field risk.
const AMOUNT_FIELDS = ["honorare", "wko_contribution", "provision_travel", "svs_sva"];
const ADDRESS_LABEL_TOKENS = new Set(["romania", "austria", "address"]);

function getFormatFlags(data: Record<string, unknown>): { field: string; reason: string }[] {
  const flags: { field: string; reason: string }[] = [];
  const val = (k: string): string => {
    const raw = data[k];
    const s = typeof raw === "string" ? raw.trim() : typeof raw === "number" ? String(raw) : "";
    return NOT_FOUND_VALUES.has(s) ? "" : s;
  };

  const taxYear = val("tax_year");
  if (taxYear && !/^\d{4}$/.test(taxYear)) flags.push({ field: "tax_year", reason: "not a 4-digit year" });

  const eCard = val("e_card_number").replace(/\s/g, "");
  if (eCard && !/^\d{10}$/.test(eCard)) flags.push({ field: "e_card_number", reason: "not a 10-digit e-card number" });

  for (const f of AMOUNT_FIELDS) {
    const v = val(f);
    if (v && !/\d/.test(v)) flags.push({ field: f, reason: "no numeric amount" });
  }

  const children = val("children");
  if (children && !/^\d{1,2}$/.test(children)) flags.push({ field: "children", reason: "not a whole number" });

  for (const f of ["address_austria", "home_address"]) {
    const v = val(f).toLowerCase().replace(/[.,]/g, "").trim();
    if (v && ADDRESS_LABEL_TOKENS.has(v)) flags.push({ field: f, reason: "looks like a form label, not an address" });
  }

  return flags;
}

const emptyEditData = {
  tax_year: "", e_card_number: "", name: "", address_austria: "", home_address: "",
  honorare: "", wko_contribution: "", provision_travel: "", svs_sva: "",
  marital_status: "", children: "", is_signed: false,
  travel_distance_km: "", trip_count: ""
};

const FIELD_GROUPS: { title: string; fields: { key: keyof typeof emptyEditData; label: string }[] }[] = [
  { title: "Identity", fields: [
    { key: "name", label: "Name" },
    { key: "e_card_number", label: "E-Card number" },
    { key: "tax_year", label: "Tax year" },
  ] },
  { title: "Address", fields: [
    { key: "address_austria", label: "Address (Austria)" },
    { key: "home_address", label: "Home address" },
  ] },
  { title: "Income & contributions", fields: [
    { key: "honorare", label: "Honorare" },
    { key: "wko_contribution", label: "WKO contribution" },
    { key: "provision_travel", label: "Travel provision" },
    { key: "svs_sva", label: "SVS / SVA" },
  ] },
  { title: "Household", fields: [
    { key: "marital_status", label: "Marital status" },
    { key: "children", label: "Children" },
    { key: "is_signed", label: "Signature" },
  ] },
  { title: "Travel", fields: [
    { key: "travel_distance_km", label: "Travel distance (km)" },
    { key: "trip_count", label: "Trip count" },
  ] },
];

const BACKEND = "http://localhost:8080";

export default function Dashboard() {
  const [cases, setCases] = useState<Case[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(null);
  // The doc previewed on the left, and the primary whose fields are on the right.
  // They diverge when the reviewer clicks a supporting doc to inspect it while
  // still editing the primary's fields.
  const [selectedDocId, setSelectedDocId] = useState<number | null>(null);
  const [activePrimaryId, setActivePrimaryId] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const [reviewerName, setReviewerName] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  // Which primary's data is loaded into editData. Guards the 3s poll from
  // resetting the reviewer's in-progress edits.
  const initializedIdRef = useRef<number | null>(null);

  const [isEditing, setIsEditing] = useState(false);
  const [editData, setEditData] = useState(emptyEditData);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const formatFieldValue = (value: any): string => {
    if (typeof value === "string") return value;
    if (typeof value === "number") return String(value);
    if (value === null || value === undefined) return "";
    if (typeof value === "object") {
      if (typeof value.value === "string" || typeof value.value === "number") {
        return String(value.value);
      }
      const addressParts = [value.street, value.city, value.state, value.country].filter(
        (p) => typeof p === "string" && p.length > 0
      );
      if (addressParts.length > 0) return addressParts.join(", ");
      return JSON.stringify(value);
    }
    return String(value);
  };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const formatBooleanValue = (value: any): boolean => {
    if (typeof value === "boolean") return value;
    if (value && typeof value === "object" && "value" in value) {
      return Boolean(value.value);
    }
    return Boolean(value);
  };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const buildEditData = (parsed: any, travelSuggestion?: TravelSuggestion) => ({
    ...emptyEditData,
    tax_year: formatFieldValue(parsed?.tax_year),
    e_card_number: formatFieldValue(parsed?.e_card_number),
    name: formatFieldValue(parsed?.name),
    address_austria: formatFieldValue(parsed?.address_austria),
    home_address: formatFieldValue(parsed?.home_address),
    honorare: formatFieldValue(parsed?.honorare),
    wko_contribution: formatFieldValue(parsed?.wko_contribution),
    provision_travel: formatFieldValue(parsed?.provision_travel),
    svs_sva: formatFieldValue(parsed?.svs_sva),
    marital_status: formatFieldValue(parsed?.marital_status),
    children: formatFieldValue(parsed?.children),
    is_signed: formatBooleanValue(parsed?.is_signed),
    travel_distance_km: travelSuggestion?.distance_km != null ? String(travelSuggestion.distance_km) : "",
  });

  // Fetch the case queue AND legacy single uploads, merging the latter as
  // synthetic one-doc cases (negative case_id) so manual/webhook uploads stay
  // visible alongside real multi-file cases.
  const fetchCases = async () => {
    try {
      const [caseRes, legacyRes] = await Promise.all([
        fetch(`${BACKEND}/api/cases/pending`).then((r) => r.json()).catch(() => []),
        fetch(`${BACKEND}/api/forms/pending`).then((r) => r.json()).catch(() => []),
      ]);
      const realCases: Case[] = Array.isArray(caseRes) ? caseRes : [];
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const legacyForms: any[] = Array.isArray(legacyRes) ? legacyRes : [];
      const legacyCases: Case[] = legacyForms.map((f) => ({
        case_id: -Math.abs(f.id),
        source: "upload",
        sender: null,
        subject: null,
        client_name_guess: f.filename,
        status: "open",
        documents: [{
          form_id: f.id,
          filename: f.filename,
          doc_type: f.status === "failed" ? "failed" : "primary",
          role: "primary",
          status: f.status,
          json_result: f.json_result,
          confidence: f.confidence,
          error: f.error,
          completeness: f.completeness,
          travel_suggestion: f.travel_suggestion,
        }],
      }));
      const merged = [...realCases, ...legacyCases];
      setCases(merged);
      // Keep the reviewer on their current case if it's still present.
      setSelectedCaseId((prev) =>
        prev != null && merged.some((c) => c.case_id === prev) ? prev : merged[0]?.case_id ?? null
      );
    } catch (e) {
      console.error("Failed to fetch cases", e);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchCases();
    const timer = setInterval(fetchCases, 3000);
    return () => clearInterval(timer);
  }, []);

  const currentCase = cases.find((c) => c.case_id === selectedCaseId) ?? cases[0];
  const documents = currentCase?.documents ?? [];
  const primaries = documents.filter((d) => d.role === "primary");
  const activePrimary =
    primaries.find((d) => d.form_id === activePrimaryId) ?? primaries[0] ?? documents[0];
  const currentDoc = documents.find((d) => d.form_id === selectedDocId) ?? activePrimary;

  // When the case changes, default the active primary + preview to its first
  // primary. Keyed on case_id so a poll doesn't reset the reviewer's doc choice.
  const caseInitRef = useRef<number | null>(null);
  useEffect(() => {
    if (!currentCase) {
      caseInitRef.current = null;
      return;
    }
    if (caseInitRef.current === currentCase.case_id) return;
    caseInitRef.current = currentCase.case_id;
    const firstPrimary = currentCase.documents.find((d) => d.role === "primary") ?? currentCase.documents[0];
    setActivePrimaryId(firstPrimary?.form_id ?? null);
    setSelectedDocId(firstPrimary?.form_id ?? null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentCase?.case_id]);

  // Load the active primary's values into editData exactly once per primary.
  useEffect(() => {
    if (!activePrimary) {
      initializedIdRef.current = null;
      return;
    }
    if (initializedIdRef.current === activePrimary.form_id) return;
    initializedIdRef.current = activePrimary.form_id;
    let parsed = activePrimary.json_result;
    if (typeof parsed === "string") {
      try { parsed = JSON.parse(parsed); } catch { parsed = {}; }
    }
    setEditData(buildEditData(parsed || {}, activePrimary.travel_suggestion));
    setIsEditing(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activePrimary?.form_id]);

  const selectDoc = (doc: Doc) => {
    setSelectedDocId(doc.form_id);
    // Clicking a primary also switches the fields panel to it.
    if (doc.role === "primary") setActivePrimaryId(doc.form_id);
  };

  const handleReview = async (approved: boolean) => {
    if (!activePrimary) return;
    if (!reviewerName.trim()) {
      alert('Enter your name in "Reviewed by" before approving or rejecting — it goes on the audit log.');
      return;
    }
    try {
      const res = await fetch(`${BACKEND}/api/forms/${activePrimary.form_id}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved, updated_data: editData, reviewer_name: reviewerName }),
      });
      const result = await res.json();
      if (!result.success) {
        alert(result.message || result.error || "Review submission failed.");
        return;
      }

      // Remove the just-reviewed primary from the case locally. If the case has
      // another primary left, advance to it; otherwise drop the whole case and
      // move to the next one. (The backend files supporting docs + closes the
      // case once its last primary is resolved.)
      const remainingPrimaries = primaries.filter((d) => d.form_id !== activePrimary.form_id);
      if (remainingPrimaries.length > 0 && currentCase) {
        const nextCases = cases.map((c) =>
          c.case_id === currentCase.case_id
            ? { ...c, documents: c.documents.filter((d) => d.form_id !== activePrimary.form_id) }
            : c
        );
        setCases(nextCases);
        setActivePrimaryId(remainingPrimaries[0].form_id);
        setSelectedDocId(remainingPrimaries[0].form_id);
        initializedIdRef.current = null;
      } else {
        const nextCases = cases.filter((c) => c.case_id !== currentCase?.case_id);
        setCases(nextCases);
        setSelectedCaseId(nextCases[0]?.case_id ?? null);
        caseInitRef.current = null;
      }
      setIsEditing(false);
    } catch (e) {
      console.error("Failed to submit review", e);
      alert("Failed to submit review — check backend connectivity.");
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsUploading(true);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch("http://localhost:8000/extract", { method: "POST", body: formData });
      const result = await res.json();
      if (result.error) {
        await fetch(`${BACKEND}/api/forms`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename: file.name, status: "failed", error: result.error || result.message }),
        });
        alert(`Extraction failed: ${result.message || result.error}\n\nAdded to the queue as "failed" for manual follow-up.`);
        await fetchCases();
        return;
      }
      await fetch(`${BACKEND}/api/forms`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: file.name, status: "extracted", fields: result.fields, confidence: result.confidence }),
      });
      await fetchCases();
    } catch (err) {
      alert("Extraction failed. Check if AI container is running.");
      console.error(err);
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-border border-t-accent"></div>
      </div>
    );
  }

  const isFailed = activePrimary?.status === "failed";
  // A primary still awaiting background extraction has no fields yet.
  const isExtracting = !!activePrimary && !isFailed &&
    activePrimary.role === "primary" && !activePrimary.json_result &&
    !["approved", "rejected"].includes(activePrimary.status);

  const missingFields = (isFailed || isExtracting)
    ? []
    : Object.entries(editData)
        .filter(([, v]) => typeof v === "string" && NOT_FOUND_VALUES.has(v))
        .map(([k]) => k);

  const unreliableFieldsToFlag = (isFailed || isExtracting)
    ? []
    : KNOWN_UNRELIABLE_FIELDS.filter((f) => !missingFields.includes(f));

  const formatFlags = (isFailed || isExtracting) ? [] : getFormatFlags(editData);

  const mandatoryFields = activePrimary?.completeness?.mandatory_fields ?? [];
  const mandatoryMissing = (isFailed || isExtracting)
    ? mandatoryFields
    : mandatoryFields.filter((f) => {
        if (f === "is_signed") return editData.is_signed !== true;
        const raw = (editData as Record<string, unknown>)[f];
        const s = typeof raw === "string" ? raw.trim() : typeof raw === "number" ? String(raw) : "";
        return s === "" || NOT_FOUND_VALUES.has(s);
      });
  const isComplete = mandatoryFields.length > 0 && mandatoryMissing.length === 0;

  const caseTitle = currentCase?.client_name_guess?.trim() || currentCase?.sender || currentCase?.subject || "Untitled case";

  return (
    <main className="container mx-auto p-8 min-h-screen flex flex-col">
      <header className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-ink tracking-tight">Intake Reviewer</h1>
          <p className="text-ink-muted mt-1 text-sm">One case at a time — verify the form, glance at the rest, approve.</p>
        </div>
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="rounded-md px-3 py-2.5 text-sm text-accent transition-colors hover:text-accent-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-canvas"
          >
            ← Clients
          </Link>
          <input type="file" ref={fileInputRef} onChange={handleFileUpload} className="hidden" accept=".pdf,.png,.jpg,.jpeg" />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploading}
            className="flex items-center gap-2 bg-accent hover:bg-accent-hover text-canvas px-4 py-2.5 rounded-md text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-canvas"
          >
            {isUploading ? (
              <div className="w-4 h-4 border-2 border-canvas/40 border-t-canvas rounded-full animate-spin"></div>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path></svg>
            )}
            {isUploading ? "Extracting…" : "Upload PDF"}
          </button>

          <div className="flex items-center gap-2.5 bg-surface border border-border px-4 py-2.5 rounded-md text-sm text-ink-muted">
            <span className="relative flex h-2 w-2" aria-hidden="true">
              <span className="motion-safe:animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-60"></span>
              <span className="relative inline-flex h-2 w-2 rounded-full bg-accent"></span>
            </span>
            <span>Cases</span>
            <span className="text-ink font-medium tabular-nums">{cases.length}</span>
          </div>
        </div>
      </header>

      {cases.length === 0 || !currentCase ? (
        <div className="flex flex-1 items-center justify-center flex-col gap-4">
          <div className="bg-surface border border-border p-10 rounded-lg text-center flex flex-col items-center max-w-sm">
            <svg className="w-10 h-10 text-success mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
            <h2 className="text-lg font-semibold text-ink mb-1">All caught up</h2>
            <p className="text-ink-muted text-sm mb-5">There are no cases waiting for review.</p>
            <button onClick={() => fileInputRef.current?.click()} className="text-accent hover:text-accent-hover text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded-sm">Upload a document</button>
          </div>
        </div>
      ) : (
        <div className="flex gap-6 flex-1 min-h-0">
          {/* Document rail: every file in this case. Primary form(s) highlighted;
              supporting docs are one click away to preview without leaving the form. */}
          <aside className="w-64 shrink-0 bg-surface border border-border rounded-lg flex flex-col overflow-hidden">
            <div className="px-4 py-3.5 border-b border-border">
              <div className="text-sm font-semibold text-ink truncate" title={caseTitle}>{caseTitle}</div>
              <div className="text-xs text-ink-muted mt-0.5 flex items-center gap-1.5">
                <span className="uppercase tracking-wide">{currentCase.source}</span>
                <span aria-hidden="true">·</span>
                <span>{documents.length} file{documents.length === 1 ? "" : "s"}</span>
                {primaries.length > 1 && (<><span aria-hidden="true">·</span><span>{primaries.length} forms</span></>)}
              </div>
            </div>
            <div className="overflow-y-auto flex-1 p-2 space-y-1">
              {documents.map((doc) => {
                const isActive = doc.form_id === currentDoc?.form_id;
                const isPrimary = doc.role === "primary";
                return (
                  <button
                    key={doc.form_id}
                    onClick={() => selectDoc(doc)}
                    className={`w-full text-left px-3 py-2 rounded-md border transition-colors flex items-start gap-2.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                      isActive ? "bg-canvas border-accent/60" : "border-transparent hover:bg-surface-hover"
                    }`}
                  >
                    <svg className={`w-4 h-4 mt-0.5 shrink-0 ${isPrimary ? "text-accent" : "text-ink-faint"}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      {isPrimary
                        ? <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                        : <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />}
                    </svg>
                    <span className="min-w-0 flex-1">
                      <span className="block text-xs text-ink truncate">{doc.filename}</span>
                      <span className={`block text-[10px] uppercase tracking-wide mt-0.5 ${isPrimary ? "text-accent" : "text-ink-faint"}`}>
                        {isPrimary ? "Form · " : ""}{docLabel(doc.doc_type)}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </aside>

          <div className="grid lg:grid-cols-2 gap-6 flex-1 min-w-0">
            {/* Preview of the selected document (any file in the case). */}
            <div className="bg-surface border border-border rounded-lg overflow-hidden flex flex-col">
              <div className="bg-surface-hover px-5 py-4 border-b border-border flex justify-between items-center gap-3">
                <h3 className="font-medium flex items-center gap-2 text-sm text-ink min-w-0">
                  <svg className="w-4 h-4 text-ink-muted shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
                  <span className="truncate">{currentDoc?.filename}</span>
                </h3>
                <span className="text-xs font-medium px-2.5 py-1 bg-canvas text-ink-muted rounded-sm border border-border uppercase tracking-wide shrink-0">
                  {currentDoc?.role === "primary" ? "Form" : docLabel(currentDoc?.doc_type)}
                </span>
              </div>
              <div className="flex-1 bg-canvas p-4 min-h-[500px]">
                <div className="w-full h-full min-h-[480px] rounded-md border border-border overflow-hidden bg-white">
                  {currentDoc && (
                    <DocPreview
                      key={currentDoc.form_id}
                      url={`${BACKEND}/api/forms/${currentDoc.form_id}/document`}
                      filename={currentDoc.filename}
                    />
                  )}
                </div>
              </div>
            </div>

            {/* Extraction data & actions for the active primary form. */}
            <div className="flex flex-col gap-4 min-w-0">
              <div className="bg-surface border border-border rounded-lg p-6 flex-1">
                <div className="flex justify-between items-center mb-5">
                  <div className="min-w-0">
                    <h3 className="text-base font-semibold text-ink flex items-center gap-2">
                      <svg className="w-4 h-4 text-ink-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
                      AI Extraction
                      {primaries.length > 1 && (
                        <span className="text-xs font-normal text-ink-muted">· form {primaries.findIndex((d) => d.form_id === activePrimary?.form_id) + 1} of {primaries.length}</span>
                      )}
                    </h3>
                    {/* Name the document these fields belong to, so it's never confused
                        with a supporting doc that happens to be previewed on the left. */}
                    {activePrimary && (
                      <p className="text-xs text-ink-muted mt-1 truncate">Fields from <span className="text-ink font-medium">{activePrimary.filename}</span></p>
                    )}
                  </div>
                  <button
                    onClick={() => setIsEditing(!isEditing)}
                    disabled={isFailed || isExtracting}
                    className="text-sm font-medium px-3 py-2 bg-canvas hover:bg-surface-hover text-ink-muted hover:text-ink rounded-md transition-colors border border-border flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                  >
                    {isEditing ? (
                      <>
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                        Cancel
                      </>
                    ) : (
                      <>
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
                        Edit Data
                      </>
                    )}
                  </button>
                </div>

                {/* When the reviewer is previewing a SUPPORTING doc on the left, the
                    fields on the right still belong to the form -- say so explicitly,
                    otherwise it reads as a data/preview mismatch. */}
                {currentDoc && activePrimary && currentDoc.form_id !== activePrimary.form_id && (
                  <div className="mb-5 bg-canvas border border-border rounded-md p-4 flex items-start gap-3">
                    <svg className="w-5 h-5 text-ink-muted shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                    <p className="text-ink-muted text-sm">You&apos;re previewing <span className="text-ink font-medium">{currentDoc.filename}</span> — a supporting document ({docLabel(currentDoc.doc_type)}). It&apos;s filed with the case, not extracted, so the fields below stay on the form (<span className="text-ink font-medium">{activePrimary.filename}</span>). Click the form in the list to line them up.</p>
                  </div>
                )}

                {isExtracting && (
                  <div className="mb-5 bg-canvas border border-border rounded-md p-4 flex items-center gap-3">
                    <div className="h-5 w-5 shrink-0 animate-spin rounded-full border-2 border-border border-t-accent"></div>
                    <div>
                      <h4 className="text-ink font-semibold uppercase tracking-wide text-xs">Extracting…</h4>
                      <p className="text-ink-muted text-sm mt-0.5">The vision model is reading this form. Fields appear here automatically when it finishes — you can review the other documents in the meantime.</p>
                    </div>
                  </div>
                )}

                {isFailed && (
                  <div className="mb-5 bg-danger/10 border border-danger/40 rounded-md p-4 flex items-center gap-3">
                    <svg className="w-5 h-5 text-danger shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                    <div>
                      <h4 className="text-danger font-semibold uppercase tracking-wide text-xs">Extraction Failed</h4>
                      <p className="text-ink-muted text-sm mt-0.5">{activePrimary?.error || "The AI service did not respond, even after retries."} Reject this entry to clear it, or re-run once the service is back up.</p>
                    </div>
                  </div>
                )}

                {!isFailed && !isExtracting && editData.is_signed === false && (
                  <div className="mb-5 bg-danger/10 border border-danger/40 rounded-md p-4 flex items-center gap-3">
                    <svg className="w-5 h-5 text-danger shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                    <div>
                      <h4 className="text-danger font-semibold uppercase tracking-wide text-xs">Flagged for Review</h4>
                      <p className="text-ink-muted text-sm mt-0.5">The AI did not detect a valid signature at the bottom of the form.</p>
                    </div>
                  </div>
                )}

                {!isFailed && !isExtracting && mandatoryFields.length > 0 && (
                  isComplete ? (
                    <div className="mb-5 bg-success/10 border border-success/40 rounded-md p-4 flex items-center gap-3">
                      <svg className="w-5 h-5 text-success shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                      <div>
                        <h4 className="text-success font-semibold uppercase tracking-wide text-xs">Complete</h4>
                        <p className="text-ink-muted text-sm mt-0.5">All required fields are present. Still verify the flagged fields below before approving.</p>
                      </div>
                    </div>
                  ) : (
                    <div className="mb-5 bg-danger/10 border border-danger/40 rounded-md p-4 flex items-center gap-3">
                      <svg className="w-5 h-5 text-danger shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636"></path></svg>
                      <div>
                        <h4 className="text-danger font-semibold uppercase tracking-wide text-xs">Incomplete — Required Fields Missing</h4>
                        <p className="text-ink-muted text-sm mt-0.5">{mandatoryMissing.join(", ")} {mandatoryMissing.length === 1 ? "is" : "are"} required to file. Fill or confirm {mandatoryMissing.length === 1 ? "it" : "them"} — or approve knowingly (the gap is logged either way).</p>
                      </div>
                    </div>
                  )
                )}

                {!isFailed && !isExtracting && missingFields.length > 0 && (
                  <div className="mb-5 bg-warning/10 border border-warning/40 rounded-md p-4 flex items-center gap-3">
                    <svg className="w-5 h-5 text-warning shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                    <div>
                      <h4 className="text-warning font-semibold uppercase tracking-wide text-xs">Missing Fields</h4>
                      <p className="text-ink-muted text-sm mt-0.5">{missingFields.join(", ")} could not be read from the form. Confirm with the carer before approving.</p>
                    </div>
                  </div>
                )}

                {!isFailed && !isExtracting && !editData.travel_distance_km && (activePrimary?.travel_suggestion?.missing_addresses?.length ?? 0) > 0 && (
                  <div className="mb-5 bg-warning/10 border border-warning/40 rounded-md p-4 flex items-center gap-3">
                    <svg className="w-5 h-5 text-warning shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                    <div>
                      <h4 className="text-warning font-semibold uppercase tracking-wide text-xs">No Travel Distance Suggestion</h4>
                      <p className="text-ink-muted text-sm mt-0.5">{activePrimary?.travel_suggestion?.missing_addresses?.join(" and ")} not found in the address lookup table — enter travel_distance_km manually below.</p>
                    </div>
                  </div>
                )}

                {!isFailed && !isExtracting && unreliableFieldsToFlag.length > 0 && (
                  <div className="mb-5 bg-warning/10 border border-warning/40 rounded-md p-4 flex items-center gap-3">
                    <svg className="w-5 h-5 text-warning shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                    <div>
                      <h4 className="text-warning font-semibold uppercase tracking-wide text-xs">Historically Unreliable Fields</h4>
                      <p className="text-ink-muted text-sm mt-0.5">{unreliableFieldsToFlag.join(", ")} — the AI model has been wrong on these fields even when it looked confident. Always verify against the original before approving.</p>
                    </div>
                  </div>
                )}

                {!isFailed && !isExtracting && formatFlags.length > 0 && (
                  <div className="mb-5 bg-warning/10 border border-warning/40 rounded-md p-4 flex items-center gap-3">
                    <svg className="w-5 h-5 text-warning shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                    <div>
                      <h4 className="text-warning font-semibold uppercase tracking-wide text-xs">Format Check</h4>
                      <p className="text-ink-muted text-sm mt-0.5">{formatFlags.map((f) => `${f.field} (${f.reason})`).join(", ")} — these values do not match their expected format and are likely misreads. Verify against the original before approving.</p>
                    </div>
                  </div>
                )}

                {!isFailed && !isExtracting && <div className="space-y-6">
                  {FIELD_GROUPS.map((group) => (
                    <section key={group.title}>
                      <h4 className="text-[11px] font-medium uppercase tracking-[0.12em] text-ink-faint mb-1">{group.title}</h4>
                      <div className="border-t border-border">
                        {group.fields.map(({ key, label }) => {
                          const value = editData[key];
                          const signed = key === "is_signed" && (value === true || value === "true");
                          const asText = typeof value === "boolean" ? String(value) : value;
                          const isEmpty = key !== "is_signed" && (asText === "" || NOT_FOUND_VALUES.has(asText));
                          return (
                            <div key={key} className="flex items-baseline gap-4 py-2.5 border-b border-border last:border-b-0">
                              <label htmlFor={`field-${key}`} className="w-40 shrink-0 text-sm text-ink-muted">{label}</label>
                              {isEditing ? (
                                <input
                                  id={`field-${key}`}
                                  type="text"
                                  value={asText}
                                  onChange={(e) => setEditData({ ...editData, [key]: e.target.value })}
                                  className="flex-1 min-w-0 bg-canvas border border-border rounded-md px-3 py-1.5 text-ink font-mono text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent transition-colors"
                                />
                              ) : key === "is_signed" ? (
                                <div className="flex-1 min-w-0 font-mono text-[15px] text-ink">{signed ? "Signed" : "Not signed"}</div>
                              ) : isEmpty ? (
                                <div className="flex-1 min-w-0 text-[15px] text-ink-faint">Not found</div>
                              ) : (
                                <div className="flex-1 min-w-0 font-mono text-[15px] text-ink break-words">{asText}</div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </section>
                  ))}
                </div>}
              </div>

              <div className="bg-surface border border-border rounded-lg px-5 py-3.5 flex items-center gap-4">
                <label className="text-xs font-medium text-ink-muted uppercase tracking-wide whitespace-nowrap">Reviewed by</label>
                <input
                  type="text"
                  value={reviewerName}
                  onChange={(e) => setReviewerName(e.target.value)}
                  placeholder="Your name"
                  className="flex-1 bg-canvas border border-border rounded-md px-3 py-2 text-ink text-sm placeholder:text-ink-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent transition-colors"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <button
                  onClick={() => handleReview(false)}
                  disabled={isExtracting}
                  className="flex items-center justify-center gap-2 px-6 py-3.5 bg-surface hover:bg-surface-hover text-danger font-medium text-sm rounded-lg border border-border hover:border-danger/50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                  Reject
                </button>

                <button
                  onClick={() => handleReview(true)}
                  disabled={isFailed || isExtracting}
                  title={isFailed ? "Can't approve a failed extraction — re-run instead." : isExtracting ? "Still extracting…" : undefined}
                  className="flex items-center justify-center gap-2 px-6 py-3.5 bg-success hover:bg-success-hover text-canvas font-medium text-sm rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-success"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path></svg>
                  Approve &amp; Save
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
