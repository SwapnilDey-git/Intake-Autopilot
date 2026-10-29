# Intake Autopilot — Architecture

A self-hosted / airgapped tax-intake automation. A tax intake form (PDF or photo)
arrives, a local vision LLM extracts the fields, a human reviews and corrects them in
a dashboard, and on approval the data is written into a per-client Excel file and filed
into a named folder that syncs to the office network drive. No external API calls are
made for inference — everything except the intake channels and the final drive sync runs
locally on the client's Windows PC in Docker.

## System diagram (ASCII)

```
                         INTAKE AUTOPILOT — System Architecture

  INTAKE CHANNELS                    ORCHESTRATION & LOCAL AI              REVIEW & OUTPUT
 ┌────────────────────┐
 │  Gmail inbox        │── poll 1m ─┐
 │  (Gmail Trigger)    │            │
 └────────────────────┘            │
 ┌────────────────────┐            │     ┌────────────────────────────┐
 │  WhatsApp            │─ webhook ─┼────▶│           n8n              │
 │  (Meta Cloud API)   │            │     │   :5678  (orchestrator)    │
 └────────────────────┘            │     │  Gmail / WhatsApp / Webhook│
 ┌────────────────────┐            │     │  → Split Attachments       │
 │  Webhook            │───────────┘     │  → Call AI Service         │
 │  POST /upload-real  │                 │  → Insert forms/extractions│
 └────────────────────┘                 │  → audit_log               │
 ┌────────────────────┐  direct upload   └──────────────┬─────────────┘
 │  Dashboard "Upload" │──────────┐         POST /extract│ (multipart file)
 └────────────────────┘          │                      ▼
                                  │        ┌────────────────────────────┐   ┌───────────────┐
                                  └───────▶│      ai-service  :8000     │──▶│   Ollama       │
                                           │  FastAPI + PyMuPDF         │   │   :11434       │
                                           │  render every page →       │◀──│  qwen2.5vl:7b  │
                                           │  vision LLM → JSON fields   │   │ (vision model) │
                                           │  saves upload → /storage    │   └───────────────┘
                                           └──────────────┬─────────────┘
                                                          │ INSERT rows
                                                          ▼
                                           ┌────────────────────────────┐
                                           │        Postgres  :5432     │
                                           │  forms · extractions ·     │
                                           │  reviews · audit_log ·     │
                                           │  address_geocode           │
                                           └──────────────┬─────────────┘
                                    GET /api/forms/pending │ (dashboard polls every 3s)
                                                          ▼
 ┌───────────────────────────────────────────────────────────────────────────────────┐
 │  Dashboard (Next.js)  :3000                         ◀── human reviewer              │
 │  • live queue, auto-refresh + auto-advance                                          │
 │  • real PDF/image preview  (GET /api/forms/{id}/document)                            │
 │  • grouped fields, edit, missing/format/duplicate banners, Approve / Reject         │
 └───────────────────────────────────┬───────────────────────────────────────────────┘
                                      │ POST /api/forms/{id}/review  (approved + edits + reviewer)
                                      ▼
                         ┌────────────────────────────┐
                         │        backend  :8080      │
                         │  FastAPI                   │
                         │  • duplicate/idempotency   │
                         │  • travel-cost calc        │
                         │  • Excel write (cell map)  │
                         │  • builds client folder    │
                         │  • serves source document  │
                         │  • writes audit_log        │
                         └──────────────┬─────────────┘
                                        │ on approval
                                        ▼
                         ┌───────────────────────────────────────────────┐
                         │  /storage/Clients/{Name}_{Year}/              │  shared Docker volume
                         │    ├── EA_{year}.xlsx        (from template)  │
                         │    └── original_intake.pdf/.jpg               │
                         └──────────────┬────────────────────────────────┘
                                        │ robocopy every 5 min (Windows Scheduled Task)
                                        ▼
                         ┌───────────────────────────────────────────────┐
                         │  Z:\STABINGER\...\2026 WA + EE- erledigt\     │  network share
                         │    └── {Name}_{Year}\  (Excel + original PDF) │  (\\10.0.0.85\Intern)
                         └───────────────────────────────────────────────┘

  Docker network (client's Windows PC):  postgres · n8n · ollama · ai-service · backend
  Runs standalone (not in compose):      dashboard (npm run dev)
  Reaches outside the box:               Gmail / WhatsApp intake, and the final Z: sync
```

## Data flow (numbered)

1. **Intake** — a form arrives by Gmail, WhatsApp, the webhook, or the dashboard upload button.
2. **Orchestrate** — n8n receives it, splits multi-attachment emails, and calls the AI service.
   (The dashboard upload path calls the AI service directly.)
3. **Extract** — `ai-service` rasterizes every PDF page with PyMuPDF, sends the images to the
   local Ollama vision model, returns `{fields, confidence}`, and saves the original file to `/storage`.
4. **Persist** — `forms` + `extractions` rows are written to Postgres; every step is logged to `audit_log`.
5. **Review** — the dashboard polls `GET /api/forms/pending` every 3s, renders the real document on the
   left and the extracted fields on the right; the reviewer corrects fields and clicks Approve.
6. **Write-up** — `backend` blocks duplicates, computes travel cost, writes the input cells into a
   per-client copy of the Excel template, creates `storage/Clients/{Name}_{Year}/`, and files the
   original document beside the Excel.
7. **Sync** — a Windows Scheduled Task robocopies `storage/Clients` to the `Z:\STABINGER` network
   share every 5 minutes (add/update only — never deletes the office's existing folders).

## Components

| Component   | Tech                              | Port  | Role |
|-------------|-----------------------------------|-------|------|
| n8n         | n8n 2.32.5                        | 5678  | Orchestrates the 3 intake channels into the AI + DB pipeline |
| ai-service  | Python FastAPI, PyMuPDF, Pillow   | 8000  | `POST /extract`: render pages → vision LLM → JSON fields; saves upload to `/storage` |
| Ollama      | Ollama + `qwen2.5vl:7b`           | 11434 | Local vision LLM inference (no external calls) |
| backend     | Python FastAPI                    | 8080  | Forms API, review/approval, idempotency, Excel write, client-folder filing, document serving |
| Postgres    | Postgres                          | 5432  | `forms`, `extractions`, `reviews`, `audit_log`, `address_geocode` |
| dashboard   | Next.js 16 / React 19 / Tailwind  | 3000  | Reviewer UI — live queue, PDF preview, edit + approve/reject |
| storage/    | shared Docker volume              | —     | Uploaded files + per-client `Clients/` outputs + Ollama model cache |
| Sync task   | Windows Scheduled Task + robocopy | —     | Mirrors `storage/Clients` → `Z:\STABINGER` every 5 min |

## Key design properties

- **Local-first / airgapped inference** — the vision model runs on-box; sensitive tax data never
  leaves the machine for extraction.
- **Human-in-the-loop** — nothing is written to the Excel/network drive without a reviewer approving.
- **Idempotent + audited** — duplicate `(e_card_number, tax_year)` approvals are blocked; every
  extraction / approval / rejection / write is logged.
- **Three parallel channels, one pipeline** — Gmail, WhatsApp, and webhook all converge on the same
  `forms`/`extractions` tables and the same review + filing flow.
```
