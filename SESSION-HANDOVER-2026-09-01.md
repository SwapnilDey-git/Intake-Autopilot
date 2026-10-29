# SESSION HANDOVER — Intake Autopilot — 2026-09-01

**Full project handoff for moving this codebase to another laptop.**
This is the total-project handoff (not the trimmed client ship-package). It captures
what the project is, its current real state, everything changed recently, the deploy
picture on the client's PC, the hard rules (PII), and exactly how to stand it up on a
fresh machine.

Read order for a new maintainer: this file → `ARCHITECTURE.md` → `RUNNING.md`
(the big operational bible) → `CLAUDE.md` → `CONTEXT.md` (domain glossary) →
`docs/adr/0001-person-centric-year-model.md`.

---

## 0. TL;DR — the one screen you must read

- **What it is:** an **airgapped, local-first** pipeline that ingests an Austrian
  tax practice's client documents (PDF / WhatsApp photos / Gmail), auto-extracts the
  tax numbers with a **local vision LLM** (no cloud, PII never leaves the box), shows
  them on a **human review dashboard**, and fills one **EA (Einnahmen-Ausgaben)
  Excel** per client per tax year.
- **Data model (settled):** `Person (Client) → TaxYear → Documents → one EA sheet per
  (person, year)`. See `CONTEXT.md` + ADR-0001. This superseded the old
  "case = one email / one form" model.
- **Stack:** Docker Compose — Postgres, n8n, Ollama (local model), a FastAPI
  **ai-service** (vision extraction), a FastAPI **backend** (orchestration/API), and a
  Next.js **dashboard**.
- **⚠️ GIT IS STALE — THE WORKING TREE ON DISK IS THE SOURCE OF TRUTH.** Most of the
  real work (person-centric dashboard, `backend/classify.py`, `backend/extractors.py`,
  n8n flows, the E1a/vcf/E9/FamBH extraction work, schema changes) is **uncommitted**
  (untracked or modified). The last commit is far behind. **This zip captures the
  actual files, so you get everything — but do NOT `git reset`/`git checkout` on the
  new machine expecting HEAD to be current; it is not.** See §6.
- **⚠️ PII RULE (non-negotiable):** real client tax documents and WhatsApp images are
  on disk and **gitignored**. This handoff zip **excludes all of it** (`storage/`,
  `reference/`, `testdoc/`, `.scratch/` PII, `demo/`, `eval/reports/`). Never read,
  echo, commit, or transmit client document contents/filenames. See §7.

---

## 1. What the system does (product)

The client is **Sebastian (Stabinger Consulting)**, an Austrian tax practice that files
mostly for **Romanian 24h-care workers**. Today the intake is manual: docs arrive by
email/WhatsApp, a human reads each form, types the numbers into an Excel EA sheet, and
files the return.

Intake Autopilot automates the read-and-transcribe drudgery while keeping a human in
the loop:

1. **Ingest** a client's documents (bulk folder import, or via n8n from Gmail/WhatsApp).
2. **Classify** each document (which are tax-relevant primary forms vs. supporting docs).
3. **Extract** the fields from the primary forms with a local vision/text model.
4. **Merge** all of a year's extracted fields into one per-(person, year) record.
5. **Review** on a dashboard — a human checks/edits every field before it's trusted.
6. **Output** one filled `EA {year}.xlsx` per client per year (the practice's real
   deliverable; their own EA sheets are the canonical template).

Next phase (out of scope now, but the data model already carries it): **drafting**
formal Finanzamt replies (§299 BAO, §303, Beschwerde, Ergänzungsersuchen) per
person/year, human-in-the-loop, with a FinanzOnline-condensed + Romanian version.

See `PRODUCT.md`, `DESIGN.md`, `CONTEXT.md`, `docs/EA-INTAKE-ANALYSIS-AND-PLAN.md`.

---

## 2. Architecture & services

Full detail in `ARCHITECTURE.md` and `RUNNING.md`. Summary:

| Service | Container | Port | Role |
|---|---|---|---|
| Postgres 16 | `intake-db` | 5432 | DB `intake`, user `admin`/`password`. Persons/tax_years/cases/forms/extractions/reviews. |
| n8n | `intake-n8n` | 5678 | Ingest orchestration (Gmail/WhatsApp/webhook → classify → backend). Mounts `./storage`. |
| Ollama | `intake-ollama` | 11434 | Local model host. Model cache in `./storage/ollama_models`. |
| ai-service (FastAPI) | `intake-ai` | 8000 | Vision + text extraction. `/extract`, `/extract_text`. Talks to Ollama. |
| backend (FastAPI) | `intake-backend` | 8080 | API + orchestration: classify, import, merge, EA writing, review endpoints. |
| dashboard (Next.js) | (host `npm run dev`) | 3000 | Human review UI. Runs on the host, not in compose. |

**Bind mounts (edit-and-restart, no rebuild for code):** `./backend → /app`,
`./ai-service → /app`, `./storage → /storage` (in backend, ai-service, n8n).
Dependency changes need `--build`; plain code edits just need `docker restart`.

**`DATABASE_URL` host is `postgres`** (the compose service name). If the DB container is
down, the backend can't resolve it ("Name or service not known") and falls into
**MOCK MODE** (serves fake `/api/forms/pending` data) until the DB is reachable **and
the backend is restarted**. This has bitten us — see §5 gotchas.

### The 4-lane extraction cascade (deterministic-first)

Extraction tries cheap/reliable lanes before expensive/fuzzy ones, per document type:

1. **AcroForm read** — pull field values straight from a fillable PDF's form fields.
2. **Kennzahl label-join text-parse** — for born-digital text PDFs, join Austrian tax
   **Kennzahl** codes (e.g. KZ 9100/9134/9190/9233) to their values by parsing the text
   layer. Deterministic, no model cost.
3. **LLM-over-text (`/extract_text`)** — feed the extracted text layer to the local LLM.
4. **Vision** — render the page and use the vision model (last resort; scans/photos).

Results merge into the per-year record; a deterministic **Format Check** (in the
dashboard) flags shape/plausibility issues the model's own confidence can't be trusted
to catch (see PROPAGATION-MANIFEST §A / RUNNING.md "Approach A").

---

## 3. Repository map (what's in this zip)

```
intake-autopilot-mac-handoff-2026-07-21 2/
├── SESSION-HANDOVER-2026-09-01.md   ← you are here (newest)
├── SESSION-HANDOVER-2026-07-28.md   ← prior handover
├── ARCHITECTURE.md                  ← system architecture
├── RUNNING.md                       ← THE operational bible (64KB; run/debug/deploy)
├── CLAUDE.md                        ← agent working notes / conventions / gotchas
├── CONTEXT.md                       ← domain glossary (Person/TaxYear/EA sheet/…)
├── PRODUCT.md / DESIGN.md           ← product intent & design
├── PROPAGATION-MANIFEST.md          ← Mac-copy → canonical fold-back manifest
├── WHERE-WE-ARE.md                  ← plain-language status snapshot
├── SETUP-mac.md                     ← Mac bring-up steps
├── docker-compose.yml               ← canonical stack (model = minicpm-v)
├── docker-compose.override.yml      ← MAC-LOCAL ONLY (host Ollama + qwen2.5vl:7b); see §4
├── backend/                         ← FastAPI orchestration
│   ├── main.py                      ← API, import, classify orchestration, EA writing, merge
│   ├── classify.py                  ← doc-type classification (UNTRACKED in git)
│   ├── extractors.py                ← the 4-lane extractors incl. Kennzahl + vcf (UNTRACKED)
│   ├── templates/EA_template.xlsx   ← EA output template
│   ├── requirements.txt / Dockerfile
├── ai-service/                      ← FastAPI vision/text extraction (main.py, requirements, Dockerfile)
├── dashboard/                       ← Next.js review UI (src/ only in zip; node_modules/.next excluded)
│   └── src/app/
│       ├── page.tsx                 ← client list (NO inline edit; links to detail)
│       ├── clients/[id]/page.tsx    ← per-client EA fields — EDITABLE, live Gewinn calc (UNTRACKED)
│       ├── reviewer/page.tsx        ← one-at-a-time reviewer w/ Edit toggle + approve (UNTRACKED)
│       ├── DocPreview.tsx           ← document preview (UNTRACKED)
│       └── layout.tsx / globals.css
├── database/schema.sql              ← full schema (persons/tax_years/cases/forms/extractions/…)
├── n8n/                             ← exported n8n workflows (Intake_Flow_*.json) — import by hand
├── scripts/
│   ├── import_person_folder.py      ← bulk folder → person import (ALSO lives at /tmp in container)
│   └── build_ea_template.py
├── windows/                         ← client-PC ops: run-all.ps1, stop-all.ps1, RUNBOOK.md, CLIENT-SETUP.md
├── eval/                            ← extraction eval harness (reports/ excluded — PII)
├── docs/                            ← EA analysis + ADR-0001 (person-centric model)
├── .scratch/phase1-next-steps/      ← wayfinder DEV TICKET TRACKER (map.md + issues/) — PII images stripped
└── .git/                            ← history + tag `baseline-mac-handoff-2026-07-23` (STALE HEAD; see §6)
```

**Excluded from this zip** (regenerable or PII): `dashboard/node_modules` (513M),
`dashboard/.next` (505M), `ai-service/.venv` (93M), all `__pycache__`, `storage/`
(client PII + model cache + upload blobs, ~236M), `reference/`, `testdoc/`, `.scratch/`
root PII (client PDFs, WhatsApp images) + `.scratch/perfect-extraction/` (80M) +
`.scratch/phase1-next-steps/image/`, `demo/image.png` (screenshot may show PII),
`eval/reports/` (may contain extracted PII values).

---

## 4. The two compose files — DO NOT MERGE THEM BLINDLY

- **`docker-compose.yml`** is the **canonical/shippable** default: containerized Ollama,
  `MODEL_NAME=minicpm-v`. This is what a fresh generic deploy should use.
- **`docker-compose.override.yml`** is **machine-local to this Mac only**: it repoints
  ai-service at the host's **native Ollama** (Metal GPU) via
  `OLLAMA_HOST=http://host.docker.internal:11434` and pins `MODEL_NAME=qwen2.5vl:7b`.
  On the Mac you must **NOT** run a bare `docker compose up -d` (native Ollama already
  owns host :11434 → port clash). Bring the stack up excluding the ollama container:
  ```
  docker compose up -d --build --no-deps postgres n8n backend ai-service
  ```
- **The client's Windows PC has its OWN customized compose** (NOT in this repo): it runs
  `qwen2.5vl:7b` **in-container on the box's NVIDIA GPU** with
  `OLLAMA_CONTEXT_LENGTH=16384`. When deploying code to the client, **never overwrite
  their two compose files** (they're backed up on his box as
  `docker-compose.yml.client-backup-20260821`).

**On a new laptop:** decide which profile you're on. If the new machine runs Ollama in a
container, use the canonical `docker-compose.yml` alone and delete/rename the Mac
override. If it runs native Ollama, keep the override pattern but re-check the model tag
and the host reachability.

---

## 5. How to stand it up on a fresh laptop

Prereqs: Docker Desktop, Node ≥ 20 (repo tested on Node 24), and either a containerized
Ollama (canonical) or native Ollama with the model pulled.

```
# 1. Unzip, then from the project root:
mkdir -p storage/ollama_models          # storage/ is bind-mounted and must exist (zip ships it empty)

# 2. Pull the model your compose expects (canonical = minicpm-v; Mac/client = qwen2.5vl:7b)
#    containerized:  docker compose up -d ollama && docker exec intake-ollama ollama pull minicpm-v
#    native (Mac):   ollama pull qwen2.5vl:7b

# 3. Bring up the stack
#    canonical:  docker compose up -d --build
#    mac local:  docker compose up -d --build --no-deps postgres n8n backend ai-service

# 4. Apply the DB schema (idempotent/additive — creates persons/tax_years/cases, drops nothing)
docker exec -i intake-db psql -U admin -d intake < database/schema.sql

# 5. Dashboard (runs on the host, not compose)
cd dashboard && npm install && npm run dev      # → http://localhost:3000

# 6. Verify
docker ps                                        # 5 containers up
docker logs --tail 30 intake-backend             # NO "MOCK MODE" line = DB reachable
curl localhost:8080/health ; curl localhost:8000/health
```

**Import a client folder** (bulk): the script is `scripts/import_person_folder.py`, also
copied to `/tmp/import_person_folder.py` inside the backend container. Files must be
under the host `storage/` dir so the container sees them at `/storage`:
```
# stage a folder into storage/, then:
docker exec intake-backend python /tmp/import_person_folder.py /storage/<folder> "<ClientName>"
```
Positional args: `<folder> [client_name]`. Poll `forms` for status
(`uploaded → supporting/extracted`). Per-form output is in table `extractions`
(`json_result` jsonb = flat `{field: value}`, `confidence` jsonb; FK→forms ON DELETE CASCADE).

**Schema facts that have bitten us:** `clients` table has **no `name` column** — join
test data by `client_id` via `cases`. Each import leaves harmless UUID-named upload
blobs in `/storage` root, interleaved with real files — don't bulk-delete them.

**MOCK MODE gotcha:** if `docker logs intake-backend` shows a MOCK-MODE warning and the
dashboard shows fake data, the backend started before Postgres was reachable. Fix: bring
the full stack up, confirm `docker exec intake-db pg_isready` accepts, then
`docker restart intake-backend` **once more**.

---

## 6. Git state — READ BEFORE YOU TOUCH GIT

The project `.git` is included, but **HEAD is far behind the working tree.** Confirmed
uncommitted at handoff time:

- **Untracked (never committed):** `backend/classify.py`, `backend/extractors.py`,
  `backend/templates/EA_template.xlsx`, `dashboard/src/app/clients/`,
  `dashboard/src/app/reviewer/`, `dashboard/src/app/DocPreview.tsx`, `n8n/*.json`,
  `scripts/`, `windows/`, `demo/`, `docs/`, `eval/`, `ARCHITECTURE.md`, `CONTEXT.md`,
  `SESSION-HANDOVER-2026-07-28.md`.
- **Modified, uncommitted:** `ai-service/main.py` (+197), `backend/main.py` (+1242),
  `backend/requirements.txt`, `database/schema.sql` (+93), `dashboard/package.json` +
  lockfile, `dashboard/src/app/page.tsx`, `globals.css`, plus `.scratch` tracker files.

Branches: `main`, `public-snapshot`, `wip/next-steps` (current). Tag:
`baseline-mac-handoff-2026-07-23` (the known-good revert point).

**Implication:** the files on disk (which this zip preserves verbatim) are authoritative.
`git status` on the new machine will show this same large uncommitted delta — that's
expected, **not** corruption. A good early task on the new laptop is to actually **commit
this working state** onto `wip/next-steps` so it stops being fragile (the whole reason
it's been living as loose files is the Mac copy history in `PROPAGATION-MANIFEST.md`).

---

## 7. PII rules — non-negotiable

Real client data lives on disk and is **gitignored on purpose** (`.gitignore` excludes
`storage/`, `reference/`, `testdoc/`, most of `.scratch/`). This zip **excludes all of
it.** Standing rules that carry to the new machine and any client work:

- **Never** read, echo, print, log, commit, or transmit the **contents, filenames, or
  folder names** of client documents. Report only **structure/counts/formats** (e.g.
  "subfolder [10]: vcf=1, e1a=2" — by index, never by client name).
- On the **client PC / production**, report **presence + source booleans only**, never
  raw extracted values. The "relax for dev corpus" exception applies **only** to the
  Mac dev corpus, never the client PC.
- The client (**Sebastian**) enters his **own** OAuth/WhatsApp passwords. Never enter
  them. **No autonomous messaging to the client** — messages are drafted only, sent on
  explicit "go".
- Validate on the client's **real** examples, not synthetic data — but do so via
  presence/source checks, without you reading the PII. (Memory:
  `intake-autopilot-validate-on-client-data`.)

---

## 8. This session's work + recent extraction gains (the "perfect extraction" drop)

Shipped to the client on **2026-08-28** as a 4-file code-only drop (zip
`intake-ship-2026-08-28`, still at the repo root here). All validated on the Mac and
smoke-tested on the client PC.

**Capabilities added:**
- **E1a full Kennzahl set** (lane 2, deterministic): `kleinmaterial` (KZ 9100),
  `abschreibung` (9134), `sonstiger_aufwand` (9233), and fixed `provisionen` (9190).
- **vcf → tel/email** — a new deterministic lane parsing WhatsApp contact `.vcf` cards
  into phone/email (no vision cost).
- **E9 → spouse** and **FamBH → children** — doc-type-aware lanes (text/vision).

**The 4 files carrying it:** `backend/extractors.py`, `backend/classify.py`,
`backend/main.py`, `ai-service/main.py`. Full-file overlays — **no new deps, no schema
change, no rebuild** (pymupdf already present from the 2026-08-21 upgrade). `SHIP-README.txt`
inside `intake-ship-2026-08-28.zip` has the exact deploy steps.

**Real-data smoke test (client PC, 2026-08-28) — PASSED:** on a real client folder with
all four new doc types, **vcf→tel ✓, E9→spouse ✓, E1a provisionen/kleinmaterial/
sonstiger_aufwand ✓**. Two legitimate blanks (NOT bugs): `abschreibung` absent (that
client has no 9134 depreciation line) and `children` absent (vision returned "Unknown"
on hard scans — the merge correctly dropped the empty value). FamBH-on-hard-scans
accuracy is a future tuning candidate.

---

## 9. Client-PC deployment picture (context, not in this zip)

The client's Windows box (Sebastian's, reached via TeamViewer) was migrated
**2026-08-21** to the person-centric + 4-lane build, then got the 2026-08-28 code drop.
Details in memory `intake-autopilot-client-pc-upgraded`. Key facts:

- **Deploy folder (= compose project name; the Postgres volume is keyed to it — deploy
  INTO the exact folder):**
  `C:\Users\Sebastian\Desktop\intake\intake-autopilot-mac-handoff-2026-07-21 2`.
- Runs `qwen2.5vl:7b` in-container on the **NVIDIA GPU**. **Don't overwrite** his two
  compose files (customized + backed up).
- **`IntakeAutopilot-Sync` scheduled task DISABLED (2026-08-28):** a pre-existing task
  (created 2026-08-07, not by us) ran `intake-sync.cmd` every 5 min — a robocopy pushing
  `storage\Clients` up to a `\\10.0.0.85` office share. It popped a cmd window every 5
  min and failed every run (`LastTaskResult 16`). Disabled via elevated PowerShell.
  **Open decision:** leave disabled or fix it (needs the UNC reachable+writable, run
  hidden, trigger on change not every 5 min).

---

## 10. Open / deferred items

- **Commit the working tree** on the new laptop (see §6) so the real state stops living
  as loose files. Then reconcile with `PROPAGATION-MANIFEST.md` (this Mac copy was an
  extracted, partly-unversioned handoff).
- **Fold this session's 4 files back to canonical Windows source** via
  `scripts/build-mac-handoff.sh` (the manifest describes the fold-back; that script
  itself lives on the canonical box, not here).
- **n8n "Classify Attachments" JS mirror** — the vcf/e9/fambh classify-flips exist in the
  backend classifier but are **not yet mirrored** in the n8n Code node, so imports routed
  through n8n won't auto-flag those types (direct import path is fine).
- **`IntakeAutopilot-Sync`** — leave disabled vs. fix (see §9).
- **FamBH-on-hard-scans** extraction accuracy tuning.
- **Waiting on client** (`WHERE-WE-ARE.md`): must-have field list, how they file the real
  return today, Romanian reply wording, first auto-reply copy. **Waiting on Meta:**
  WhatsApp business verification before WhatsApp intake goes live.
- **Ticket 17 (cross-channel AI concurrency)** and the wayfinder ticket board live in
  `.scratch/phase1-next-steps/` (`map.md` + `issues/`).

---

## 11. Related memory files (on the origin Mac, not in this zip)

- `intake-autopilot-client-pc-upgraded` — the client-PC deploy record (most detailed).
- `intake-autopilot-mac-propagation-pending` — Mac→canonical fold-back status.
- `intake-autopilot-version-tree-and-pii` — revert points + PII-on-disk note.
- `intake-autopilot-case-grouping` — multi-file case grouping (built, not yet live).
- `intake-autopilot-validate-on-client-data` — the standing "test on real data, don't
  read the PII" rule.

_Generated 2026-09-01 as a full-project handoff. The working tree on disk is
authoritative; verify against actual files before asserting any file:line as fact._
