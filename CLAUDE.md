# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Read order for deep context** (this file is the short version): `SESSION-HANDOVER-2026-09-01.md` (newest full handoff — read this first, it supersedes everything below where they conflict) → `ARCHITECTURE.md` (system diagram) → `RUNNING.md` (64KB operational bible: every run/debug/deploy scenario, full model-choice history, troubleshooting war stories) → `CONTEXT.md` (domain glossary) → `docs/adr/0001-person-centric-year-model.md` (why the data model looks the way it does) → `WHERE-WE-ARE.md` (plain-language status / what's blocked on the client). `SETUP.md` (Windows/WSL2) or `SETUP-mac.md` (macOS) cover fresh-machine prerequisites.

## Read this before touching git or client data

- **Git HEAD is far behind the working tree.** Most of the real implementation — `backend/classify.py`, `backend/extractors.py`, the person-centric dashboard pages (`dashboard/src/app/clients/`, `dashboard/src/app/reviewer/`), `docs/`, `ARCHITECTURE.md`, `CONTEXT.md`, large chunks of `backend/main.py`/`ai-service/main.py`/`database/schema.sql` — is **untracked or modified, not committed**. `git log` stops around the 2026-07-23 Mac-handoff baseline plus a handful of wayfinder-ticket commits; everything from the 2026-08-20 person-centric rewrite onward lives only on disk. Don't `git checkout`/`reset`/`clean` assuming HEAD reflects current behavior — verify against the actual files first. A good early task on a fresh checkout is committing this state onto `wip/next-steps` rather than leaving it fragile.
- **PII is non-negotiable.** Real client tax documents, WhatsApp images, and their filenames live under `storage/`, `reference/`, `testdoc/`, and most of `.scratch/` — all gitignored on purpose. Never read, echo, log, commit, or transmit the *contents or filenames* of client documents; report structure/counts only (e.g. "subfolder [10]: vcf=1, e1a=2"), never by client name. On anything resembling the client's production box, report presence/source booleans only, never raw extracted values. Never enter the client's own OAuth/WhatsApp credentials, and never send anything to the client without an explicit "go" — draft only.

## What this is

An airgapped, local-first pipeline for an Austrian tax practice (Stabinger Consulting) that mostly files for Romanian 24h-care workers. It ingests client documents (PDF/WhatsApp photos/Gmail), classifies and extracts tax figures with a local vision/text LLM (no cloud — PII never leaves the box), merges them into a human-reviewed record, and produces one filled `EA {year}.xlsx` (Einnahmen-Ausgaben-Rechnung) per client per tax year.

**Data model (ADR-0001, settled 2026-08-20): `Client (Person) → TaxYear → Documents`, merging into one per-(client, year) record → one EA sheet.** This replaced an earlier "one email = one case" model that had no way to represent a person who returns year after year with fields scattered across several documents. A `case` (email/WhatsApp/webhook/folder submission) still exists but is now just an attach-point that routes its documents to a client, not the output unit itself. See `CONTEXT.md` for the full glossary (Client, TaxYear, Document, Submission, Tax-relevant document, Primary/Supporting, EA sheet, Per-year record).

**Two review flows currently coexist in the dashboard** — this is the single most important thing to understand before touching `backend/main.py` or the dashboard:
1. **Legacy single-form case reviewer** (`/reviewer`, `POST /api/forms/{id}/review`) — one case/form at a time, approve writes straight into `EXCEL_CELL_MAP` cells of a per-form Excel copy. Still live and still exercised by all three intake channels.
2. **Person-centric per-year reviewer** (`/` client list → `/clients/[id]`, `POST /api/tax-years/{id}/generate`) — built for ADR-0001: browse a client's documents grouped by tax year, edit the merged per-year record, generate `EA_{year}.xlsx` from the canonical template (`backend/templates/EA_template.xlsx`, built by `scripts/build_ea_template.py`) via a *different* cell map (`EA_RECORD_CELL_MAP`, column C throughout — see `build_ea_template.py`'s docstring for the full row layout).

Both write real Excel output; neither has been retired. Check which flow a change needs before assuming `EXCEL_CELL_MAP` is the only mapping in play.

## Services

| Component  | Tech | Port | Role |
|---|---|---|---|
| n8n | n8n | 5678 | Orchestrates 3 intake channels (webhook/Gmail/WhatsApp) into the AI + DB pipeline. Not in git; exported workflow JSON in `n8n/`. |
| ai-service | Python FastAPI, PyMuPDF, Pillow (`ai-service/main.py`) | 8000 | `POST /extract` (vision: renders every PDF page, sends to Ollama) and `POST /extract_text` (LLM over an already-extracted text layer, no rendering). Bounds concurrency with a semaphore (`AI_MAX_CONCURRENCY`, default 2) around a threaded Ollama call. |
| Ollama | Ollama | 11434 | Local vision/text model host. Model tag is env-driven (`MODEL_NAME`) — see "Model choice" below. |
| backend | Python FastAPI, single file (`backend/main.py`, ~1700 lines) + `classify.py` + `extractors.py` | 8080 | Owns Postgres, the 4-lane extraction cascade, merge logic, both Excel-write paths, client-folder filing, document serving, audit log. |
| Postgres 16 | — | 5432 | `clients`, `client_identities`, `tax_years`, `cases`, `forms`, `extractions`, `reviews`, `audit_log`, `address_geocode`, `whatsapp_contacts`. |
| dashboard | Next.js 16 / React 19 / Tailwind v4 | 3000 | Runs on the host (`npm run dev`), not in compose. Three pages — see below. |
| storage/ | shared bind mount into n8n/ai-service/backend | — | Uploads, per-client `Clients/{name}_{year}/EA_{year}.xlsx` + filed originals, and the Ollama model cache (`storage/ollama_models`). |

### The 4-lane extraction cascade (`backend/extractors.py`, `backend/main.py`'s `_extract_primaries`)

Deterministic-first, cheapest lane wins, falls through only on failure:
1. **AcroForm read** — pull values straight from a fillable PDF's form fields.
2. **Kennzahl label-join text-parse** — for born-digital text PDFs (E1a), join Austrian tax Kennzahl codes (KZ 9100/9134/9190/9233/...) to their values by parsing the text layer. No model cost.
3. **LLM-over-text** (`ai-service` `/extract_text`) — feed the text layer to the local LLM.
4. **Vision** (`ai-service` `/extract`) — render pages, vision model. Last resort: scans/photos with no usable text layer.

Also in `extractors.py`: a `.vcf` contact-card parser (phone/email, no model cost) and doc-type-aware lanes for E9 (spouse) and FamBH (children). `classify.py` decides doc type, junk-filtering, year-from-filename, and primary-vs-supporting role (`decide_case_roles`) before any of this runs.

### Dashboard pages

- **`/`** (`page.tsx`) — person-centric client list: one row per client with year/document counts, links into `/clients/[id]`. Read-only navigation.
- **`/clients/[id]`** (`clients/[id]/page.tsx`) — the person-centric reviewer: left pane = client's documents grouped by tax year, middle = document preview (`DocPreview.tsx`, PDF.js — client-only, dynamically imported to avoid SSR touching browser globals), right = the merged per-year EA record, editable, with live Gewinn/Grundfreibetrag/Einkünfte and a "Generate EA" action.
- **`/reviewer`** (`reviewer/page.tsx`) — the original one-case-at-a-time reviewer: completeness badge, format-check banner, travel-distance suggestion, Approve/Reject gated on a "Reviewed by" name.

All three talk directly to `backend` (`http://localhost:8080`) via hardcoded URLs — no env config, no proxy.

## Data flow

```
Intake (Gmail poll / WhatsApp webhook / n8n webhook / dashboard upload / scripts/import_person_folder.py bulk backfill)
  -> POST /api/intake/case: classify() each attachment (doc type, junk filter, year, primary/supporting)
       -> match/create client (by email/phone/name identity), ensure tax_years row
       -> file supporting docs into storage/Clients/{name}_{year}/; primaries queued for background extraction
  -> _extract_primaries: 4-lane cascade per primary doc -> extractions row
  -> merge_year_fields: per-(client, year) merge across all that year's extractions -> tax_years.ea_fields (draft)
  -> reviewer opens /clients/[id], edits the merged record, POST /api/tax-years/{id}/generate
       -> writes EA_{year}.xlsx from backend/templates/EA_template.xlsx via EA_RECORD_CELL_MAP, tax_years.status = 'generated'

(in parallel, still live) legacy single-form path:
  PDF upload -> ai-service /extract -> forms + extractions rows -> /reviewer -> POST /api/forms/{id}/review
       -> blocks duplicate (e_card_number, tax_year); computes travel cost; writes EXCEL_CELL_MAP cells into
          storage/Clients/{name}_{year}/EA_{year}.xlsx (copied from EXCEL_TEMPLATE_PATH on first write)
```

Every step (extraction, extraction_failed, approval, rejection, duplicate_blocked, write, file, completeness, greeting_sent) is logged to `audit_log`.

## Commands

**Start the stack** (containerized Ollama — the shippable default, `MODEL_NAME=minicpm-v`):
```
docker compose up -d --build
```
**On this Mac**, native Ollama already owns host `:11434` (Metal GPU, `docker-compose.override.yml` pins `MODEL_NAME=qwen2.5vl:7b`) — do **not** run a bare `docker compose up -d`; bring the stack up without the containerized `ollama` service:
```
docker compose up -d --build --no-deps postgres n8n backend ai-service
```

**Apply the DB schema** (not automatic — no init-script mount):
```
docker exec -i intake-db psql -U admin -d intake < database/schema.sql
```
Safe to re-run anytime (`IF NOT EXISTS`/`ADD COLUMN IF NOT EXISTS` throughout).

**Dashboard**:
```
cd dashboard && npm install
npm run dev      # http://localhost:3000
npm run build
npm run lint      # only quality check configured; no test script exists
```

**Code edits to backend/ai-service take effect on restart, no rebuild** (bind-mounted): `docker compose restart backend ai-service`. Only `requirements.txt`/Dockerfile changes need `--build`.

**Bulk-import a client folder** (local backfill/testing of the person-centric model — live intake goes through n8n, not this):
```
docker exec intake-backend python /tmp/import_person_folder.py /storage/<folder> "<ClientName>"
```

**Accuracy eval harness** (`eval/`, stack must be up):
```
python3 eval/run_eval.py --model-label qwen2.5vl:7b
```
Scores `/extract` against labelled cases in `eval/cases/` (gitignored — real PII). A meaningful number is blocked on the client's ground-truth label set; `example.json` is a schema demo only.

There are no automated tests anywhere in this repo (ai-service, backend, dashboard all lack test suites).

## Gotchas specific to this repo

- **Mock mode**: if `DATABASE_URL`'s host (`postgres`, the compose service name) isn't reachable when `backend` starts, it silently falls back to fake `/api/forms/pending` data. `docker logs intake-backend` showing no "MOCK MODE" line is your confirmation it's really talking to Postgres. Fix requires the DB up *and then* `docker restart intake-backend` once more.
- **CORS** on both `backend` and `ai-service` is `allow_origin_regex=r"http://localhost:\d+"`, not a fixed origin — `next dev` silently moves to 3001/3002/... whenever 3000 is taken, and a fixed-origin CORS list turns that into a silent, misleading "all caught up" empty queue rather than an error.
- **Model choice has a long, non-obvious history** (`llava` → bad; `minicpm-v` → good, current shippable default; `qwen3-vl:8b` → broken output from a thinking-template mismatch, reverted; `qwen2.5vl:7b` → this Mac's native-Ollama default, needed a `coerce_field_value` fix for its nested-object field shape). Full comparison and reasoning in `RUNNING.md`'s "Model choice" section — don't re-litigate this from scratch.
- **Two Excel templates exist on disk**: `backend/templates/EA_template.xlsx` (canonical, generated by `scripts/build_ea_template.py`, used by the new per-year `/generate` flow) and `backend/templates/EA_2025_template.xlsx` (older placeholder used by the legacy `/review` approval path, `EXCEL_CELL_MAP`). Neither is the client's actual hand-tailored sheet — both are structural reconstructions; verify cell positions before trusting a production write.
- **The model's self-reported confidence is not a usable correctness signal** — it stays flat regardless of correctness. The dashboard instead runs a deterministic "Format Check" (`getFormatFlags()` in the reviewer pages: e-card must be exactly 10 digits, amount fields must contain a digit, address fields can't equal a bare form-label token, etc.) plus a hardcoded `KNOWN_UNRELIABLE_FIELDS` list. See RUNNING.md for why the alternatives (multi-sample agreement, prompt-tuning confidence, a labelled eval set) were rejected or deferred.
- **Vision inference is genuinely slow and hardware-dependent**: CPU-only in a plain Docker Desktop container (minutes per form); native Ollama on Apple Silicon Metal or an NVIDIA GPU (client's Windows box) is ~8s/form. `OLLAMA_KEEP_ALIVE=30m` avoids a ~4min reload penalty on gaps between requests but doesn't touch compute time itself.
- **The client's Windows PC has its own customized compose files**, not in this repo — never overwrite them when deploying code there (they're backed up as `docker-compose.yml.client-backup-*` on that box). See `SESSION-HANDOVER-2026-09-01.md` §4/§9 for the two-compose-files rule and the deploy folder path (the folder name is also the Postgres volume key — deploy into the exact existing folder).
- **The dashboard is on Next.js 16 / React 19**, which postdates typical training data — check `dashboard/node_modules/next/dist/docs/` before assuming older App Router conventions apply (asserted in `dashboard/AGENTS.md`, imported by `dashboard/CLAUDE.md`).
- **`travel_distance_km` is auto-suggested, not fully manual** — a small manually-populated `address_geocode` lookup table plus haversine×1.25 in `compute_travel_suggestion()` (`backend/main.py`), not a live geocoding service (deliberate — see RUNNING.md's "Travel distance geocoding"). Exact-text address matching only; OCR variance across extractions of the same address can miss a lookup hit.
- **n8n's own Postgres tables accumulate duplicate workflow imports** from repeated testing — check `workflow_entity.updatedAt` (or the n8n UI) rather than assuming the first search result is the live copy. Editing `n8n/*.json` on disk does not update an already-imported workflow; you must re-import.
- **Activating an n8n workflow requires a browser session** — no CLI/API shortcut exists (n8n's Active toggle registers the webhook route through its own engine via an authenticated UI action).
