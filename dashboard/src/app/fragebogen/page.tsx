"use client";

// Questionnaire tracking: every personal link (ref) the office issued, and
// whether the client's PDF has come back. Refs live only on this box.

import { useEffect, useState } from "react";
import Link from "next/link";

const BACKEND = "http://localhost:8080";

type Invite = {
  ref: string;
  client_id: number | null;
  display_name: string | null;
  year: number;
  created_at: string;
  returned_at: string | null;
  status: "open" | "returned";
};

const fmt = (d: string | null) => (d ? new Date(d).toLocaleDateString("de-AT") : "—");

export default function FragebogenTracking() {
  const [rows, setRows] = useState<Invite[] | null>(null);
  const [filter, setFilter] = useState<"all" | "open" | "returned">("all");
  const [q, setQ] = useState("");

  useEffect(() => {
    fetch(`${BACKEND}/api/questionnaire/invites`)
      .then((r) => r.json())
      .then((d) => setRows(d.invites || []))
      .catch(() => setRows([]));
  }, []);

  const shown = (rows || []).filter(
    (r) =>
      (filter === "all" || r.status === filter) &&
      (!q || r.ref.includes(q.toUpperCase()) || (r.display_name || "").toLowerCase().includes(q.toLowerCase())),
  );
  const open = (rows || []).filter((r) => r.status === "open").length;

  return (
    <main className="container mx-auto max-w-4xl p-8">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <Link href="/" className="text-sm text-accent hover:text-accent-hover">← Clients</Link>
          <h1 className="mt-2 text-xl font-semibold text-ink">Fragebogen-Links</h1>
          <p className="text-sm text-ink-muted">
            {rows ? `${rows.length} verschickt · ${open} offen · ${rows.length - open} zurück` : "Lädt…"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Kennnummer oder Name"
            className="rounded-md border border-border bg-canvas px-3 py-1.5 text-sm text-ink"
          />
          {(["all", "open", "returned"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded-md border px-3 py-1.5 text-sm ${
                filter === f ? "border-accent text-ink" : "border-border text-ink-muted hover:bg-surface-hover"
              }`}
            >
              {f === "all" ? "Alle" : f === "open" ? "Offen" : "Zurück"}
            </button>
          ))}
        </div>
      </header>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left font-mono text-xs uppercase text-ink-faint">
            <th className="py-2">Kennnummer</th><th>Klientin</th><th>Jahr</th><th>Erstellt</th><th>Status</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((r) => (
            <tr key={r.ref} className="border-b border-border">
              <td className="py-2 font-mono text-ink">{r.ref}</td>
              <td>
                {r.client_id ? (
                  <Link href={`/clients/${r.client_id}`} className="text-accent hover:text-accent-hover">
                    {r.display_name || `Client #${r.client_id}`}
                  </Link>
                ) : "—"}
              </td>
              <td className="text-ink-muted">{r.year}</td>
              <td className="text-ink-muted">{fmt(r.created_at)}</td>
              <td>
                <span className={`rounded-sm px-1.5 py-0.5 font-mono text-xs uppercase ${
                  r.status === "returned" ? "bg-success/15 text-success" : "bg-warning/15 text-warning"}`}>
                  {r.status === "returned" ? `zurück ${fmt(r.returned_at)}` : "offen"}
                </span>
              </td>
            </tr>
          ))}
          {rows && shown.length === 0 && (
            <tr><td colSpan={5} className="py-6 text-center text-ink-muted">Keine Einträge.</td></tr>
          )}
        </tbody>
      </table>
    </main>
  );
}
