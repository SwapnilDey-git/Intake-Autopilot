"use client";

// Personal questionnaire links for one client. The public form (Vercel) stores
// nothing; the client sends back a PDF carrying her answers and this ref, and
// intake matches it to this client and flips the ref to "zurück".

import { useCallback, useEffect, useState } from "react";

const BACKEND = "http://localhost:8080";

type Invite = {
  ref: string;
  year: number;
  created_at: string;
  returned_at: string | null;
  status: "open" | "returned";
  url: string | null;
};

const fmt = (d: string | null) => (d ? new Date(d).toLocaleDateString("de-AT") : "");

export default function FragebogenInvite({ clientId, year }: { clientId: number; year: number | null }) {
  const [invites, setInvites] = useState<Invite[]>([]);
  const [publicUrl, setPublicUrl] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const load = useCallback(() => {
    fetch(`${BACKEND}/api/questionnaire/invites?client_id=${clientId}`)
      .then((r) => r.json())
      .then((d) => {
        setInvites(d.invites || []);
        setPublicUrl(d.public_form_url || null);
      })
      .catch(() => {});
  }, [clientId]);

  useEffect(load, [load]);

  async function create() {
    const y = year ?? new Date().getFullYear() - 1;
    const res = await fetch(`${BACKEND}/api/questionnaire/invites`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client_id: clientId, year: y }),
    }).then((r) => r.json());
    if (res.success) {
      setOpen(true);
      if (res.url) {
        await navigator.clipboard?.writeText(res.url).catch(() => {});
        setMsg(`Link ${res.ref} kopiert — per WhatsApp oder E-Mail schicken.`);
      } else {
        setMsg(`Kennnummer ${res.ref} erstellt. PUBLIC_FORM_URL ist im Backend nicht gesetzt — kein Link.`);
      }
      load();
    } else {
      setMsg(res.error || "Fehler beim Erstellen.");
    }
  }

  const returned = invites.filter((i) => i.status === "returned").length;

  return (
    <div className="relative">
      <div className="flex items-center gap-2">
        <button
          onClick={create}
          className="rounded-md bg-accent px-3 py-1.5 text-sm text-white transition-colors hover:bg-accent-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          Link für Klientin {year ?? ""}
        </button>
        {invites.length > 0 && (
          <button
            onClick={() => setOpen((o) => !o)}
            className="rounded-md border border-border px-2.5 py-1.5 font-mono text-xs text-ink-muted hover:bg-surface-hover"
            title="Verschickte Fragebogen-Links"
          >
            {returned}/{invites.length} zurück
          </button>
        )}
      </div>
      {open && (
        <div className="absolute right-0 z-20 mt-2 w-[420px] rounded-lg border border-border bg-surface p-3 shadow-lg">
          {msg && <p className="mb-2 text-xs text-ink">{msg}</p>}
          {!publicUrl && (
            <p className="mb-2 text-xs text-ink-muted">
              Öffentliche Fragebogen-Adresse fehlt (Backend-Variable PUBLIC_FORM_URL).
            </p>
          )}
          <ul className="max-h-64 divide-y divide-border overflow-auto">
            {invites.map((i) => (
              <li key={i.ref} className="flex items-center gap-2 py-1.5 text-xs">
                <span className="font-mono text-ink">{i.ref}</span>
                <span className="text-ink-faint">{i.year}</span>
                <span className="text-ink-faint">{fmt(i.created_at)}</span>
                <span
                  className={`ml-auto rounded-sm px-1.5 py-0.5 font-mono uppercase ${
                    i.status === "returned" ? "bg-success/15 text-success" : "bg-warning/15 text-warning"
                  }`}
                >
                  {i.status === "returned" ? `zurück ${fmt(i.returned_at)}` : "offen"}
                </span>
                {i.url && (
                  <button
                    onClick={() => navigator.clipboard?.writeText(i.url!).then(() => setMsg(`Link ${i.ref} kopiert.`))}
                    className="rounded-sm border border-border px-1.5 py-0.5 text-ink-muted hover:bg-surface-hover"
                  >
                    Kopieren
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
