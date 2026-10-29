"use client";

// Person-centric queue (ADR-0001): one row per client, with year/document counts.
// Read-only navigation into the per-year view; the per-year review + EA generation
// screen is layered on after Phase 2 core. The old case reviewer (/) is untouched.

import { useEffect, useState } from "react";
import Link from "next/link";

const BACKEND = "http://localhost:8080";

type ClientRow = {
  id: number;
  display_name: string | null;
  year_count: number;
  doc_count: number;
};

export default function ClientsPage() {
  const [clients, setClients] = useState<ClientRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetch(`${BACKEND}/api/clients`)
      .then((r) => r.json())
      .then((d) => {
        if (live) setClients(d.clients || []);
      })
      .catch((e) => {
        if (live) setError(String(e));
      });
    return () => {
      live = false;
    };
  }, []);

  return (
    <main className="container mx-auto max-w-3xl p-8">
      <header className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Clients</h1>
          <p className="mt-1 text-sm text-ink-muted">
            People the practice files for — each owns their tax years and documents.
          </p>
        </div>
        <Link
          href="/fragebogen"
          className="rounded-md border border-border px-3 py-1.5 text-sm text-ink transition-colors hover:bg-surface-hover"
        >
          Fragebogen-Links
        </Link>
      </header>

      {error && (
        <div className="rounded-md border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
          Couldn&apos;t load clients: {error}
        </div>
      )}

      {clients === null && !error && (
        <div className="text-sm text-ink-muted">Loading…</div>
      )}

      {clients && clients.length === 0 && (
        <div className="rounded-lg border border-border bg-surface px-6 py-10 text-center">
          <p className="text-sm text-ink-muted">
            No clients yet. A client appears here once a submission is routed to a person
            (live intake) or a folder is imported.
          </p>
        </div>
      )}

      {clients && clients.length > 0 && (
        <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface">
          {clients.map((c) => (
            <li key={c.id}>
              <Link
                href={`/clients/${c.id}`}
                className="flex items-center justify-between gap-4 px-5 py-4 transition-colors hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
              >
                <span className="truncate text-ink">{c.display_name || `Client #${c.id}`}</span>
                <span className="flex shrink-0 items-center gap-4 font-mono text-xs text-ink-muted">
                  <span>
                    {c.year_count} {c.year_count === 1 ? "year" : "years"}
                  </span>
                  <span>
                    {c.doc_count} {c.doc_count === 1 ? "doc" : "docs"}
                  </span>
                  <span className="text-ink-faint" aria-hidden="true">
                    ›
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
