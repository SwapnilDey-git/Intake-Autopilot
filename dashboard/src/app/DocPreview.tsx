"use client";

// Source-document preview for the reviewer. Routes by file type because the client's
// intake folders are heterogeneous -- PDFs, phone photos (jpg/jpeg/png), Excel working
// files (xlsx), and the odd exported contact card (vcf). Each needs a different renderer;
// the old version fed everything that wasn't a PDF into an <img>, which showed a broken
// image for xlsx/vcf. Anything we can't render inline falls back to a download link.
//
// COLORS: this preview panel is a white "document" surface, so everything here uses
// explicit dark-on-white neutrals -- NOT the app's theme tokens (text-ink/border-border
// etc.), which are light colors tuned for the dark dashboard chrome and render invisibly
// on white.
//
// PDFs are rendered with PDF.js (via react-pdf) rather than a raw <iframe> specifically so
// the browser's native PDF viewer does NOT execute the embedded JavaScript that official
// Austrian tax forms carry (an OpenAction script that pops a "use Adobe Acrobat" alert on
// open). react-pdf's <Document> runs with scripting disabled by default, so that alert
// never fires, and the stored/filed original document is left completely untouched.

import { useEffect, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";

// Bundle the worker locally (airgapped box -- no CDN). Pulled from the SAME pdfjs-dist that
// react-pdf depends on, so the API/worker versions always match.
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

const IMAGE_EXTS = new Set(["png", "jpg", "jpeg", "webp", "gif", "bmp"]);
const SHEET_EXTS = new Set(["xlsx", "xls"]);

function extOf(filename: string): string {
  const m = /\.([a-z0-9]+)$/i.exec(filename || "");
  return m ? m[1].toLowerCase() : "";
}

export default function DocPreview({ url, filename }: { url: string; filename: string }) {
  const ext = extOf(filename);
  if (ext === "pdf") return <PdfView url={url} />;
  if (IMAGE_EXTS.has(ext)) return <ImageView url={url} filename={filename} />;
  if (SHEET_EXTS.has(ext)) return <SheetView url={url} filename={filename} />;
  if (ext === "vcf") return <VCardView url={url} filename={filename} />;
  // Questionnaire copies (Fragebogen_{year}.html) are backend-rendered and
  // escaped; sandbox="" still forbids scripts, forms and navigation.
  if (ext === "html") return <iframe src={url} sandbox="" title={filename} className="h-full w-full bg-white" />;
  return <DownloadFallback url={url} filename={filename} label={ext ? `.${ext} file` : "file"} />;
}

// --- PDF -------------------------------------------------------------------
function PdfView({ url }: { url: string }) {
  const [numPages, setNumPages] = useState(0);
  return (
    <div className="flex h-full w-full flex-col items-center overflow-auto bg-neutral-200 py-3">
      <Document
        file={url}
        onLoadSuccess={({ numPages }) => setNumPages(numPages)}
        loading={<div className="p-6 text-sm text-neutral-600">Loading PDF…</div>}
        error={<div className="p-6 text-sm text-red-600">Couldn&apos;t render this PDF.</div>}
        noData={<div className="p-6 text-sm text-neutral-600">No document.</div>}
      >
        {Array.from({ length: numPages }, (_, i) => (
          <Page
            key={i}
            pageNumber={i + 1}
            width={620}
            renderTextLayer={false}
            renderAnnotationLayer={false}
            className="mb-3 shadow-md"
          />
        ))}
      </Document>
    </div>
  );
}

// --- Images (phone photos, scans) ------------------------------------------
// On a gray backdrop with a white card frame so a mostly-white scan (a signature, an
// invoice) is still visibly bounded instead of blending into the panel.
function ImageView({ url, filename }: { url: string; filename: string }) {
  const [broken, setBroken] = useState(false);
  if (broken) return <DownloadFallback url={url} filename={filename} label="image" />;
  return (
    <div className="flex h-full w-full items-start justify-center overflow-auto bg-neutral-200 p-4">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={url}
        alt={filename}
        className="h-auto max-w-full bg-white shadow-md ring-1 ring-neutral-300"
        onError={() => setBroken(true)}
      />
    </div>
  );
}

// --- Excel working files ---------------------------------------------------
// Rendered from the backend's /sheet endpoint (openpyxl -> JSON rows) rather than a
// client-side xlsx parser, so no new npm dependency has to ship to the airgapped box.
type SheetData = { name: string; rows: string[][]; truncated: boolean };

function SheetView({ url, filename }: { url: string; filename: string }) {
  const [sheets, setSheets] = useState<SheetData[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sheetUrl = url.replace(/\/document(\?.*)?$/, "/sheet");

  useEffect(() => {
    // No need to reset state here: the parent passes key={doc.id}, so this component
    // remounts per document and state already starts at its loading value.
    let alive = true;
    fetch(sheetUrl)
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => alive && setSheets(d.sheets ?? []))
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, [sheetUrl]);

  if (error) return <DownloadFallback url={url} filename={filename} label="spreadsheet" note={error} />;
  if (!sheets) return <div className="bg-white p-6 text-sm text-neutral-500">Loading spreadsheet…</div>;
  if (sheets.length === 0) return <div className="bg-white p-6 text-sm text-neutral-500">Empty spreadsheet.</div>;

  return (
    <div className="h-full w-full overflow-auto bg-white p-3">
      {sheets.map((s, si) => (
        <div key={si} className="mb-6">
          <div className="mb-2 font-mono text-[11px] uppercase text-neutral-500">{s.name}</div>
          {s.rows.length === 0 ? (
            <div className="text-sm text-neutral-500">(no data)</div>
          ) : (
            <table className="border-collapse text-xs text-neutral-800">
              <tbody>
                {s.rows.map((row, ri) => (
                  <tr key={ri}>
                    <td className="select-none border border-neutral-300 bg-neutral-100 px-1.5 py-0.5 text-right font-mono text-[10px] text-neutral-400">
                      {ri + 1}
                    </td>
                    {row.map((cell, ci) => (
                      <td
                        key={ci}
                        className="max-w-[240px] truncate border border-neutral-300 px-2 py-0.5"
                        title={cell}
                      >
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {s.truncated && (
            <div className="mt-1 text-[11px] text-neutral-500">Truncated — download to see the full sheet.</div>
          )}
        </div>
      ))}
    </div>
  );
}

// --- vCard (.vcf) ----------------------------------------------------------
// A vCard is plain text; parse the common fields into a readable contact card.
function VCardView({ url, filename }: { url: string; filename: string }) {
  const [pairs, setPairs] = useState<[string, string][] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Remounts per document (parent key={doc.id}), so no reset needed here.
    let alive = true;
    fetch(url)
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.text();
      })
      .then((t) => alive && setPairs(parseVcard(t)))
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, [url]);

  if (error) return <DownloadFallback url={url} filename={filename} label="contact card" note={error} />;
  if (!pairs) return <div className="bg-white p-6 text-sm text-neutral-500">Loading contact…</div>;
  if (pairs.length === 0)
    return <DownloadFallback url={url} filename={filename} label="contact card" note="No readable fields" />;

  return (
    <div className="h-full w-full overflow-auto bg-white p-6">
      <div className="mb-3 font-mono text-[11px] uppercase text-neutral-500">Contact (vCard)</div>
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-sm">
        {pairs.map(([k, v], i) => (
          <div key={i} className="contents">
            <dt className="text-neutral-500">{k}</dt>
            <dd className="break-words text-neutral-800">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

const VCARD_LABELS: Record<string, string> = {
  FN: "Name",
  N: "Name",
  ORG: "Organisation",
  TITLE: "Title",
  TEL: "Phone",
  EMAIL: "Email",
  ADR: "Address",
  BDAY: "Birthday",
  URL: "Website",
  NOTE: "Note",
};

function parseVcard(text: string): [string, string][] {
  const out: [string, string][] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || /^(BEGIN|END|VERSION|PRODID|REV|UID):/i.test(line)) continue;
    const colon = line.indexOf(":");
    if (colon < 0) continue;
    const key = line.slice(0, colon).split(";")[0].toUpperCase().replace(/^ITEM\d+\./, "");
    const value = line.slice(colon + 1).replace(/;+/g, " ").trim();
    if (!value) continue;
    const label = VCARD_LABELS[key];
    if (label) out.push([label, value]);
  }
  return out;
}

// --- Generic fallback ------------------------------------------------------
function DownloadFallback({
  url,
  filename,
  label,
  note,
}: {
  url: string;
  filename: string;
  label: string;
  note?: string;
}) {
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-3 bg-neutral-100 p-6 text-center">
      <div className="text-sm text-neutral-600">Can&apos;t preview this {label} inline.</div>
      <a
        href={url}
        download={filename}
        className="rounded-md border border-neutral-400 px-3 py-1.5 text-sm font-medium text-neutral-800 transition-colors hover:bg-neutral-200"
      >
        Download to open
      </a>
      {note && <div className="max-w-sm text-[11px] text-neutral-500">{note}</div>}
    </div>
  );
}
