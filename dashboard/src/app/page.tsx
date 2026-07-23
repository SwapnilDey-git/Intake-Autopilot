"use client";

import { useState, useEffect, useRef } from "react";

// Types
type TravelSuggestion = {
  distance_km: number | null;
  missing_addresses: string[];
};

type Form = {
  id: number;
  filename: string;
  status: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  json_result: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  confidence?: any;
  error?: string;
  travel_suggestion?: TravelSuggestion;
};

const NOT_FOUND_VALUES = new Set(["Not Found", "Unknown"]);

// The model's self-reported confidence was empirically found to always be
// ~1.0 regardless of correctness (see wayfinder ticket 15) -- it isn't a
// usable signal, so instead of a live confidence banner we flag this fixed
// set of fields found to be unreliable, based on repeated testing against
// the same document. Revisit this list once ticket 12/13's real eval set
// gives broader evidence than one document.
const KNOWN_UNRELIABLE_FIELDS = ["e_card_number", "name", "honorare", "svs_sva"];

// Deterministic per-field shape checks -- the trustworthy half of field risk.
// Unlike the model's self-reported confidence (found ~uniform regardless of
// correctness, see KNOWN_UNRELIABLE_FIELDS above / wayfinder ticket 15), these
// flag values whose *shape* is wrong: a non-numeric amount, a wrong-length
// e-card, an address that is really just a form label ("Romania"). Deliberately
// calibrated to catch shape violations ONLY, never implausible-but-valid values
// -- the test forms carry odd years (1937) and huge incomes, which must NOT flag.
const AMOUNT_FIELDS = ["honorare", "wko_contribution", "provision_travel", "svs_sva"];
// The country/label words printed next to the address fields on the form. The
// model has substituted one of these for the actual handwritten address before
// (home_address -> "Romania"), so a value equal to a bare label is a misread.
const ADDRESS_LABEL_TOKENS = new Set(["romania", "austria", "address"]);

function getFormatFlags(data: Record<string, unknown>): { field: string; reason: string }[] {
  const flags: { field: string; reason: string }[] = [];
  // Read a field as a trimmed string, treating not-found/blank as absent so a
  // missing field is only ever reported by the Missing Fields banner, not here.
  const val = (k: string): string => {
    const raw = data[k];
    const s = typeof raw === "string" ? raw.trim() : typeof raw === "number" ? String(raw) : "";
    return NOT_FOUND_VALUES.has(s) ? "" : s;
  };

  const taxYear = val("tax_year");
  if (taxYear && !/^\d{4}$/.test(taxYear)) flags.push({ field: "tax_year", reason: "not a 4-digit year" });

  // Austrian e-card (SVNR) is exactly 10 digits -- strict, by decision.
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

export default function Dashboard() {
  const [forms, setForms] = useState<Form[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const [reviewerName, setReviewerName] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Edit State
  const [isEditing, setIsEditing] = useState(false);
  const [editData, setEditData] = useState(emptyEditData);

  // ai-service now normalizes every field to a flat string/bool before it ever
  // reaches here (see coerce_field_value in ai-service/main.py) -- but rows
  // extracted before that fix are already sitting in Postgres with whatever
  // shape the model returned (e.g. {"value": "...", "_confidence": 1}, or a
  // structured {"street": ..., "city": ...} address). React can't render a raw
  // object as a child, so every field value gets funneled through this before
  // it lands in editData, not just address fields.
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

  // Same nesting problem as the string fields above, but is_signed needs to
  // collapse to an actual boolean rather than formatFieldValue's string output.
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
    // Pre-filled from the address_geocode lookup (backend's compute_travel_suggestion)
    // when both addresses are known -- still a plain editable field, same as every
    // other AI-suggested value, so the reviewer can correct or override it.
    travel_distance_km: travelSuggestion?.distance_km != null ? String(travelSuggestion.distance_km) : "",
  });

  const fetchForms = async () => {
    try {
      const res = await fetch("http://localhost:8080/api/forms/pending");
      const data = await res.json();
      setForms(data);
      if (data.length > 0) {
        let parsed = data[0].json_result;
        if (typeof parsed === 'string') parsed = JSON.parse(parsed);
        setEditData(buildEditData(parsed || {}, data[0].travel_suggestion));
      }
    } catch (e) {
      console.error("Failed to fetch forms", e);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchForms();
    // fetchForms is stable (defined once per render, no external deps) — only run on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const currentForm = forms[currentIndex];

  const handleReview = async (approved: boolean) => {
    if (!currentForm) return;

    if (!reviewerName.trim()) {
      alert('Enter your name in "Reviewed by" before approving or rejecting — it goes on the audit log.');
      return;
    }

    try {
      const res = await fetch(`http://localhost:8080/api/forms/${currentForm.id}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          approved,
          updated_data: editData,
          reviewer_name: reviewerName,
        }),
      });
      const result = await res.json();

      if (!result.success) {
        alert(result.message || result.error || "Review submission failed.");
        return;
      }

      const nextForms = forms.filter((_, i) => i !== currentIndex);
      setForms(nextForms);
      setIsEditing(false);

      if (nextForms.length > 0) {
        let parsed = nextForms[0].json_result;
        if (typeof parsed === 'string') parsed = JSON.parse(parsed);
        setEditData(buildEditData(parsed || {}, nextForms[0].travel_suggestion));
      }
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
      // Hit our AI extraction service directly for instant testing!
      const res = await fetch("http://localhost:8000/extract", {
        method: "POST",
        body: formData,
      });
      const result = await res.json();

      if (result.error) {
        // Persist the failure so it shows in the queue rather than vanishing
        // silently — this is the "model/service down" fallback path.
        const createRes = await fetch("http://localhost:8080/api/forms", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            filename: file.name,
            status: "failed",
            // Prefer the specific diagnostic string for the audit log — the
            // reviewer-facing banner below uses the human-readable message instead.
            error: result.error || result.message,
          }),
        });
        const created = await createRes.json();
        setForms([{
          id: created.id ?? Math.floor(Math.random() * 100000),
          filename: file.name,
          status: "failed",
          json_result: {},
          error: result.message || result.error,
        }, ...forms]);
        setCurrentIndex(0);
        alert(`Extraction failed: ${result.message || result.error}\n\nAdded to the queue as "failed" for manual follow-up.`);
        return;
      }

      // Persist to Postgres so this form gets a real id — without this it
      // only ever existed in browser state and approving it would fail.
      const createRes = await fetch("http://localhost:8080/api/forms", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filename: file.name,
          status: "extracted",
          fields: result.fields,
          confidence: result.confidence,
        }),
      });
      const created = await createRes.json();

      const newForm: Form = {
        id: created.id ?? Math.floor(Math.random() * 100000),
        filename: file.name,
        status: "extracted",
        json_result: result.fields,
        confidence: result.confidence,
      };

      setForms([newForm, ...forms]);
      setCurrentIndex(0);
      setEditData(buildEditData(result.fields || {}));

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

  const isFailed = currentForm?.status === "failed";

  const missingFields = isFailed
    ? []
    : Object.entries(editData)
        .filter(([, v]) => typeof v === "string" && NOT_FOUND_VALUES.has(v))
        .map(([k]) => k);

  // Only flag known-unreliable fields that aren't already caught by the
  // missing-fields banner above -- that banner already tells the reviewer
  // to check those; this one is for fields that look populated but have a
  // history of being wrong anyway (e.g. a plausible-looking but incorrect
  // e_card_number).
  const unreliableFieldsToFlag = isFailed
    ? []
    : KNOWN_UNRELIABLE_FIELDS.filter((f) => !missingFields.includes(f));

  // Deterministic shape/plausibility flags -- see getFormatFlags. Complements the
  // banners above with fields that are present but malformed (likely misreads),
  // independent of the model's (unreliable) self-reported confidence.
  const formatFlags = isFailed ? [] : getFormatFlags(editData);

  return (
    <main className="container mx-auto p-8 min-h-screen flex flex-col">
      <header className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-ink tracking-tight">
            Intake Reviewer
          </h1>
          <p className="text-ink-muted mt-1 text-sm">Verify AI extractions before they&apos;re approved</p>
        </div>
        <div className="flex items-center gap-3">
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

          <div className="bg-surface border border-border px-4 py-2.5 rounded-md text-sm text-ink-muted">
            Queue: <span className="text-ink font-medium">{forms.length}</span>
          </div>
        </div>
      </header>

      {forms.length === 0 ? (
        <div className="flex flex-1 items-center justify-center flex-col gap-4">
          <div className="bg-surface border border-border p-10 rounded-lg text-center flex flex-col items-center max-w-sm">
            <svg className="w-10 h-10 text-success mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
            <h2 className="text-lg font-semibold text-ink mb-1">All caught up</h2>
            <p className="text-ink-muted text-sm mb-5">There are no pending documents in the queue.</p>
            <button onClick={() => fileInputRef.current?.click()} className="text-accent hover:text-accent-hover text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded-sm">Upload a document</button>
          </div>
        </div>
      ) : (
        <div className="grid lg:grid-cols-2 gap-6 flex-1">
          {/* Left Side: Document Preview Placeholder */}
          <div className="bg-surface border border-border rounded-lg overflow-hidden flex flex-col">
            <div className="bg-surface-hover px-5 py-4 border-b border-border flex justify-between items-center">
              <h3 className="font-medium flex items-center gap-2 text-sm text-ink">
                <svg className="w-4 h-4 text-ink-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
                {currentForm.filename}
              </h3>
              <span className="text-xs font-medium px-2.5 py-1 bg-canvas text-ink-muted rounded-sm border border-border uppercase tracking-wide">
                Source PDF
              </span>
            </div>
            <div className="flex-1 bg-canvas p-8 flex items-center justify-center min-h-[500px]">
              <div className="w-full h-full max-w-md bg-surface border border-border rounded-md p-10 flex items-center justify-center text-ink-faint text-sm text-center">
                [In a production app, the real PDF viewer would render here based on the filename.]
              </div>
            </div>
          </div>

          {/* Right Side: Extraction Data & Actions */}
          <div className="flex flex-col gap-4">
            <div className="bg-surface border border-border rounded-lg p-6 flex-1">
              <div className="flex justify-between items-center mb-5">
                <h3 className="text-base font-semibold text-ink flex items-center gap-2">
                  <svg className="w-4 h-4 text-ink-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
                  AI Extraction
                </h3>
                <button
                  onClick={() => setIsEditing(!isEditing)}
                  className="text-sm font-medium px-3 py-2 bg-canvas hover:bg-surface-hover text-ink-muted hover:text-ink rounded-md transition-colors border border-border flex items-center gap-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
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

              {isFailed && (
                <div className="mb-5 bg-danger/10 border border-danger/40 rounded-md p-4 flex items-center gap-3">
                  <svg className="w-5 h-5 text-danger shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                  <div>
                    <h4 className="text-danger font-semibold uppercase tracking-wide text-xs">Extraction Failed</h4>
                    <p className="text-ink-muted text-sm mt-0.5">{currentForm.error || "The AI service did not respond, even after retries."} Re-upload this document once the service is back up, then Reject this entry to clear it from the queue.</p>
                  </div>
                </div>
              )}

              {!isFailed && editData.is_signed === false && (
                <div className="mb-5 bg-danger/10 border border-danger/40 rounded-md p-4 flex items-center gap-3">
                  <svg className="w-5 h-5 text-danger shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                  <div>
                    <h4 className="text-danger font-semibold uppercase tracking-wide text-xs">Flagged for Review</h4>
                    <p className="text-ink-muted text-sm mt-0.5">The AI did not detect a valid signature at the bottom of the form.</p>
                  </div>
                </div>
              )}

              {!isFailed && missingFields.length > 0 && (
                <div className="mb-5 bg-warning/10 border border-warning/40 rounded-md p-4 flex items-center gap-3">
                  <svg className="w-5 h-5 text-warning shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                  <div>
                    <h4 className="text-warning font-semibold uppercase tracking-wide text-xs">Missing Fields</h4>
                    <p className="text-ink-muted text-sm mt-0.5">{missingFields.join(", ")} could not be read from the form. Confirm with the carer before approving.</p>
                  </div>
                </div>
              )}

              {!isFailed && !editData.travel_distance_km && (currentForm?.travel_suggestion?.missing_addresses?.length ?? 0) > 0 && (
                <div className="mb-5 bg-warning/10 border border-warning/40 rounded-md p-4 flex items-center gap-3">
                  <svg className="w-5 h-5 text-warning shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                  <div>
                    <h4 className="text-warning font-semibold uppercase tracking-wide text-xs">No Travel Distance Suggestion</h4>
                    <p className="text-ink-muted text-sm mt-0.5">{currentForm?.travel_suggestion?.missing_addresses?.join(" and ")} not found in the address lookup table — enter travel_distance_km manually below.</p>
                  </div>
                </div>
              )}

              {!isFailed && unreliableFieldsToFlag.length > 0 && (
                <div className="mb-5 bg-warning/10 border border-warning/40 rounded-md p-4 flex items-center gap-3">
                  <svg className="w-5 h-5 text-warning shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                  <div>
                    <h4 className="text-warning font-semibold uppercase tracking-wide text-xs">Historically Unreliable Fields</h4>
                    <p className="text-ink-muted text-sm mt-0.5">{unreliableFieldsToFlag.join(", ")} — the AI model has been wrong on these fields even when it looked confident. Always verify against the original photo before approving.</p>
                  </div>
                </div>
              )}

              {!isFailed && formatFlags.length > 0 && (
                <div className="mb-5 bg-warning/10 border border-warning/40 rounded-md p-4 flex items-center gap-3">
                  <svg className="w-5 h-5 text-warning shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                  <div>
                    <h4 className="text-warning font-semibold uppercase tracking-wide text-xs">Format Check</h4>
                    <p className="text-ink-muted text-sm mt-0.5">{formatFlags.map((f) => `${f.field} (${f.reason})`).join(", ")} — these values do not match their expected format and are likely misreads. Verify against the original photo before approving.</p>
                  </div>
                </div>
              )}

              {!isFailed && <div className="space-y-3">
                {Object.entries(editData).map(([key, value]) => (
                  <div key={key} className="bg-canvas p-4 rounded-md border border-border transition-colors hover:border-accent/50">
                    <label className="block text-xs font-medium text-ink-muted uppercase tracking-wide mb-2">{key}</label>
                    {isEditing ? (
                      <input
                        type="text"
                        value={typeof value === "boolean" ? String(value) : value}
                        onChange={(e) => setEditData({...editData, [key]: e.target.value})}
                        className="w-full bg-surface border border-border rounded-md px-3 py-2 text-ink font-mono text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent transition-colors"
                      />
                    ) : (
                      <div className="text-base font-mono text-ink">
                        {value || <span className="text-ink-faint not-italic font-sans">Not found</span>}
                      </div>
                    )}
                  </div>
                ))}
              </div>}
            </div>

            {/* Reviewer identity — required for the audit log */}
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

            {/* Action Buttons */}
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => handleReview(false)}
                className="flex items-center justify-center gap-2 px-6 py-3.5 bg-surface hover:bg-surface-hover text-danger font-medium text-sm rounded-lg border border-border hover:border-danger/50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                Reject
              </button>

              <button
                onClick={() => handleReview(true)}
                disabled={isFailed}
                title={isFailed ? "Can't approve a failed extraction — re-upload the document instead." : undefined}
                className="flex items-center justify-center gap-2 px-6 py-3.5 bg-success hover:bg-success-hover text-canvas font-medium text-sm rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-success"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path></svg>
                Approve &amp; Save
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
