# Session Handover — Intake Autopilot — 2026-07-28

Full state so a fresh person/agent can continue. Reference paths point at the real
artifacts instead of duplicating them. **This file is LOCAL ONLY** — it references real
client data under `.scratch/`; do not publish it or `demo/` to the public code repo.

---

## 0. Read-me-first — hard constraints (do not violate)
1. **Git repo lives in this subfolder**, not the parent. Run git/docker from:
   `…/intake-autopilot/intake-autopilot-mac-handoff-2026-07-21 2/`
   (The parent `~/Documents/GitHub` is a *different* repo — a footgun.)
2. **`.scratch/` holds REAL CLIENT PII** (handwritten forms, e-cards, IDs, gov docs,
   chat screenshots). Never publish/push/commit it. For repeatable tests prefer
   synthetic `testdoc/` PDFs.
3. **Public repo `0xArchitect/Intake-Autopilot` is CODE ONLY** and already published.
   The harness blocks the agent from pushing there — the USER pushes.
4. **No autonomous client messaging** on any channel. Client-facing text is DRAFT ONLY;
   a human sends. See `.scratch/phase1-next-steps/client-messages-draft.md`.
5. **WhatsApp is ON HOLD** (Meta Business Verification, ticket 08). It's stripped from
   the currently-active workflow. Do not wire it live without explicit sign-off.

## 1. What this is (1 paragraph)
Airgapped Austrian tax-intake automation. A handwritten intake form (PDF/photo) is
submitted → a **local** vision LLM (Ollama) extracts ~12 fields → a human reviews/corrects
in a dashboard → on approval the values are written into a per-client Excel worksheet.
"Airgapped" = the *inference* is on-box; ingestion channels (webhook/email) can be remote.
Full architecture: `CLAUDE.md`; run/stop/debug: `RUNNING.md`; Mac specifics: `SETUP-mac.md`;
Windows: `SETUP.md`. Planning tracker: `.scratch/phase1-next-steps/map.md`.

## 2. Current running state (end of this session)
- **Stack: UP** — `postgres`, `n8n`, `backend`, `ai-service` containers running; **native
  Ollama on Metal** (Mac) serving `qwen2.5vl:7b` (~8-30s/form). Docker Desktop left open.
- **Dashboard: UP** — `http://localhost:3000` (Next.js dev server, background process).
- **n8n: webhook channel LIVE** — a webhook-only copy of the workflow (`webhooktest00001`)
  is **active**; a Postgres credential exists.
- Endpoints: dashboard `:3000` · backend `:8080` · ai-service `:8000/docs` · n8n `:5678` ·
  intake webhook `POST :5678/webhook/upload-real`.

## 3. What was done this session
1. **Ticket 17 (bounded inference concurrency) — live-verified.** 5 concurrent `/extract`
   held the semaphore cap at 2, event loop stayed responsive, no memory blow-up. Details +
   the reverted instrumentation note: `.scratch/phase1-next-steps/issues/17-cross-channel-ai-concurrency.md`.
2. **Two client-message drafts polished** (must-have fields; real filing process). DRAFT
   ONLY: `.scratch/phase1-next-steps/client-messages-draft.md`.
3. **Parsing validated on REAL documents** (new this session — summary here, no separate file):
   - Real 9-page **E1** PDF → proves the render→model→JSON plumbing (HTTP 200, ~127s).
   - **Two real handwritten intake forms** (Cercel Loredana, Stana Daniela) extracted.
   - **Aggregate across the 2 forms: ~68% exact, ~86% correct-or-usable** (near-misses are
     1-2 char OCR slips the reviewer catches), calibrated confidence.
   - **Systematic weakness = one field**: form field 1 "E-Card Nummer **und** Steuerjahr".
     The model mangles the split (invents `tax_year` from e-card digits). All hard-wrong
     reads were this field. **Cheap prompt fix** (treat field-1 value as e-card; only emit
     tax_year from an explicit 4-digit year, else "Not Found"). NOT yet done.
   - Caveat: tiny sample (2 forms) — formalize via ticket 12 (labelled eval set).
4. **n8n webhook path activated via CLI + restart** — **this debunks RUNNING.md's
   "activation is browser-only" claim**: `n8n update:workflow --active=true` + a container
   restart *does* register the webhook (n8n re-registers active workflows at boot). Fired a
   synthetic PDF end-to-end: webhook → ai-service → Postgres (`forms`/`extractions`/
   `audit_log` with `actor='n8n'`).
5. **Dashboard started; approve walkthrough** → verified the full tail: review → approve →
   per-client `EA_*.xlsx` written (input cells only, formulas preserved), Reisekosten
   computed, original filed, full `audit_log` chain.
6. **One-command client showcase built** (see §4).

## 4. Deliverables built this session
**A) Windows full-system bring-up (the "full running version") — primary ask.**
- `windows/run-all.ps1` — stands up the REAL system on a Windows Docker Desktop box, the
  same operational sequence run manually on the Mac: `docker compose up --build` → apply
  `database/schema.sql` → pull `minicpm-v` → import Postgres credential + workflow into n8n
  → activate + restart (webhook registers) → `npm install`/start dashboard → status summary.
  `-Full` flag imports the 3-channel workflow when a Gmail credential already exists; else it
  falls back to the webhook-active workflow. **Not yet run on a Windows box — validate there.**
- `windows/stop-all.ps1` — stops dashboard + containers (data preserved).
- `windows/README.md` — prereqs, usage, Windows-vs-Mac notes.
- `n8n/Intake_Flow_webhook.json` — **new artifact**: the full workflow minus the Gmail
  trigger (which blocks activation without OAuth), explicit id `intakewebhook001`. This is what
  the fallback path activates. Full 3-channel file remains `n8n/Intake_Flow_Real.json`.

**B) Narrated client showcase (secondary — a demo, not the running system).**
- `demo/demo-showcase.sh` (Mac, rehearsed ✓), `demo/demo-showcase.ps1` (Windows mirror),
  `demo/GMAIL-SETUP.md` (one-time real-Gmail OAuth guide). Preflight → webhook → email
  (auto-detected) → review/approve → Excel. Overridable via `DEMO_DOC`/`REVIEWER`.

The Gmail setup guide (`demo/GMAIL-SETUP.md`) is shared by both A and B.

## 5. Intake channels — status
| Channel | Status | Notes |
|---|---|---|
| **Webhook / web upload** | ✅ LIVE now | `POST :5678/webhook/upload-real` |
| **Email (Gmail)** | ⏳ needs 1-time setup | user does `demo/GMAIL-SETUP.md` (Google OAuth + n8n login) → **then I finish wiring**: attach cred, import+activate the FULL workflow (webhook+Gmail), restart. Replaces `webhooktest00001` (same `upload-real` path → must swap, not run both). |
| **WhatsApp** | ⛔ on hold | Meta verification; stripped from active workflow |

## 5b. Deployment decision — CONFIRMED with the client (2026-07-28)
**The entire system runs on the client's Windows PC.** Access method (confirmed): **SSH over
Tailscale** — native Windows OpenSSH Server reached over a private Tailscale link (Docker
Desktop + auto-login/stay-logged-in so the engine is up for `docker` over SSH). **Not** AnyDesk.
Devs connect **only to set up / reconfigure**, run `windows/run-all.ps1`, then disconnect — no
permanent connection, nothing exposed to the public internet. Keeps tax PII on the client's
machine (airgapped promise holds). Client bootstrap: `windows/CLIENT-SETUP.md` + one-time
`windows/enable-ssh.ps1` (client runs as admin with the dev's SSH public key). Dev connect
steps: `windows/README.md` → "Remote access — developer side". Docker-over-SSH caveat: the
client must stay logged in (lock, don't sign out) with Docker set to start on login.

**This corrects the client's original handover list** (which assumed devs connect *remotely to
the client's model + DB*):
- `http://IP:11434/v1` remote model → **not used**. Ollama runs locally; app uses the native
  API on `localhost:11434` (no `/v1`). Don't expose `:11434`.
- `qwen3-vl:8b` → **wrong/broken** here → use **`minicpm-v`** (what `run-all.ps1` pulls).
- Remote DB host + exposed `:5432`, and the standalone `docker run … intake-postgres` (user
  `postgres`) → **not needed and conflicts** with the compose `intake-db` (user `admin`) on
  `:5432`. Skip it.
- **Corrected dev handover** = remote-control creds + Docker Desktop/Node on the PC + the repo
  + run `windows/run-all.ps1`. Client-facing prep: `windows/CLIENT-SETUP.md`.

## 6. Windows vs Mac (for the .ps1 / a Windows deployment)
- **Inference**: Mac = native Ollama on Metal (via `docker-compose.override.yml`, `qwen2.5vl:7b`,
  fast). Windows = **containerised Ollama on CPU**, model `minicpm-v`, **~4-9 min/form** + a
  one-time model load. The `.ps1` waits accordingly and warns the presenter.
- **Bring-up**: Mac = `docker compose up -d --build --no-deps postgres n8n backend ai-service`
  (skip the container Ollama to avoid a :11434 clash with native). Windows = `docker compose up
  -d --build` (WITH the ollama container). Schema (fresh volume): pipe `database/schema.sql`
  into `psql` (command in the .ps1 header).
- **Activation** is identical on both: CLI `update:workflow --active=true` + restart.

## 7. Known issues / caveats
- **Excel template is a placeholder** (cell `A1` says so) reconstructed from the spec, not
  the client's real EA sheet. Two cells are guesses.
- **Excel values written as raw strings** — e.g. honorare `"€21.600"`, so the `Gewinn`/
  `Grundfreibetrag` formulas won't compute until values are numeric. Optional fix: parse
  numbers on write in `backend/main.py` (EXCEL_CELL_MAP write loop, ~line 453).
- **E-Card/Steuerjahr prompt bug** (see §3.3) — the one real accuracy fix worth doing.
- **Accuracy sample is 2 forms** — directional only; ticket 12 for a real harness.

## 8. Artifacts created this session (cleanup candidates)
- n8n: workflow `webhooktest00001` (active), one Postgres credential.
- DB rows: synthetic `forms` #3/#4 (+ extractions/audit); real-form rows if the demo was run
  on a real doc.
- Disk: `storage/Clients/Swoop_neel_Deg_2023/` — **synthetic leftover** from the approve
  walkthrough; safe to delete before a real client demo.
- The pipeline auto-saves each uploaded file to `storage/` — clean real-form copies after tests.

## 9. Open decisions / next steps
1. **Gmail**: user completes `demo/GMAIL-SETUP.md`, then pings me to activate the full workflow.
2. **Deploy the demo to the Windows box** and validate `demo-showcase.ps1` there.
3. Optional: clear the synthetic `Swoop_…` folder; add Excel number-parsing so totals compute
   live; apply the E-Card/Steuerjahr prompt fix and re-measure.
4. Standing/unrelated: verify WhatsApp greeting (20a) on Meta test tier (blocked on creds).

## 10. Key files
- `CLAUDE.md`, `RUNNING.md`, `SETUP.md`, `SETUP-mac.md`, `WHERE-WE-ARE.md`
- `ai-service/main.py` (`/extract`, `call_model_bounded`, extraction prompt ~line 217)
- `backend/main.py` (review/approve, `EXCEL_CELL_MAP`, travel calc)
- `n8n/Intake_Flow_Real.json` (full 3-channel workflow, live id `sn3IWsWJ04lCYkYG`)
- `n8n/Intake_Flow_webhook.json` (id `intakewebhook001`, webhook-active) + `n8n/Intake_Flow_full.json` (id `intakefull000001`, webhook+Gmail) — both new
- `docker-compose.yml` + `docker-compose.override.yml` (Mac native-Ollama)
- `.scratch/phase1-next-steps/` (tracker `map.md`, issue files, client drafts)
- `windows/` (Windows "full running version": `run-all.ps1`, `stop-all.ps1`, `README.md`, **`CLIENT-SETUP.md`** — the plain-language client prep/remote-access page)
- `demo/` (narrated showcase scripts + `GMAIL-SETUP.md`)
- Memory index: `~/.claude/projects/-Users-arnabray-Documents-GitHub/memory/MEMORY.md`

## 11. Suggested skills for the next agent
- **`/handoff`** — regenerate this doc if state moves materially.
- **`using-n8n-mcp-skills`** (+ `n8n-*`) — before editing the n8n workflow (channels, activation).
- No code-writing skill is needed for the immediate next step (Gmail is manual browser setup;
  then a small CLI activation I perform).
