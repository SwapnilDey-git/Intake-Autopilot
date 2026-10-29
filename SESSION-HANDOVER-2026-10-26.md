# SESSION HANDOVER — Intake Autopilot — 2026-10-26

**Full-project transfer to the second Mac.** That Mac was last synced with the
2026-09-01 handoff zip. This file lists everything done since then, the current
state on the client PC, and how to get the second Mac running.

**Read order:**
1. This file.
2. `SESSION-HANDOVER-2026-09-01.md` for the full system picture: product, architecture, compose rules, PII. It still holds wherever this file doesn't override it.
3. `CLAUDE.md`, `ARCHITECTURE.md`, `RUNNING.md`, `CONTEXT.md`.

---

## 0. TL;DR

- **The working tree in this zip is the source of truth, not git.** Git HEAD is still
  at the July baseline plus a few ticket commits. Every change listed below is
  uncommitted (modified or untracked files).
  - Do not `git reset`, `git checkout .` or `git clean`.
  - First job on the new Mac: commit this state onto `wip/next-steps` (see §6).
- **The client PC is fully up to date.** As of 2026-10-07 it runs drop `intake-ship-2026-10-07`,
  which includes everything in §2.
  - All 5 containers are up and the backend is on the real DB (no MOCK MODE).
  - The dashboard is patched.
- **Since 09-01 we added three things:**
  - a large set of EA extraction accuracy fixes (Sep 25 to Oct 1);
  - a client questionnaire, the "Steuermappe" (Oct 7), which works in the office and as a public link;
  - a public, data-free copy of the questionnaire hosted on Vercel.
- **PII rule unchanged.** This zip contains **no client documents, no DB data, no
  storage/**. Never read, echo, commit or send client document contents or filenames.
  Report structure and counts only.

---

## 1. What's in this zip / what's excluded

Included:
- the full working tree: code, docs, n8n exports, templates, scripts, wayfinder tracker;
- `.git/` (history, branches `main`, `wip/next-steps`, `public-snapshot`, and tag
  `baseline-mac-handoff-2026-07-23`);
- `tools/` with the PII-safe check scripts (see §5);
- `ship-history/` with the README of every client-PC code drop since 09-25.

**Excluded** (PII, or rebuilt locally):

| Excluded | Reason |
|---|---|
| `storage/` | Client documents, generated EA sheets, Ollama model cache |
| `TAX DOCUMENT EXAMPLES 1/` | Real client documents |
| `reference/`, `testdoc/` | Real client documents |
| `.scratch/` root | PII; only `.scratch/phase1-next-steps/` is kept, without `image/` |
| `eval/cases/*` | Real labels; only `example.json` is kept |
| `eval/reports/` | May contain extracted values |
| Postgres data | Lives in a Docker volume; contains client data |
| `dashboard/node_modules`, `dashboard/.next`, `.venv`, `__pycache__`, `tsconfig.tsbuildinfo` | Rebuilt locally |

The Mac's Postgres holds real clients, so it is **not** transferred. The new Mac
starts with an empty DB plus the schema. To test, import a folder with
`scripts/import_person_folder.py` on that machine.

---

## 2. What was done since 2026-09-01 (chronological)

Every item below is in this zip **and** deployed on the client PC. Full per-drop notes,
including deploy steps and rollback, are in `ship-history/`.

### 2026-09-25: extraction accuracy + jump-to-source
- `ai-service/main.py`, E1 cover sheet: the model is no longer asked for money fields the
  form doesn't carry. Before this it invented one number for all three.
- Honorarnote "Gesamtbetrag" is now treated as the person's own income, not a commission.
- The E1a LLM lane now also asks for `kleinmaterial`, `abschreibung` and `sonstiger_aufwand`.
- Stricter anti-hallucination and anti-"tax-office-address" prompt rules.
- Dashboard `clients/[id]/page.tsx`: a field's source badge is clickable and jumps to the
  origin document in the preview pane.

### 2026-09-30: StNr vs SVNR confusion
- `backend/extractors.py` `_extract_e1_identity`: BMF uses the same AcroForm widget name for
  the Steuernummer boxes and the SVNR boxes. The fix tells them apart by the printed row label
  and rejects values shaped like a bare 10-digit SVNR.
- `ai-service/main.py` `_reject_svnr_shaped_stnr`: the same guard on the text and vision lanes.
- `backend/main.py`: re-extract now **replaces** a form's extractions row instead of adding a
  second one. The duplicate rows had caused false conflicts with itself.
- Prompt hints: `honorare` sums stacked monthly Honorarnoten; `sonstiger_aufwand` must never
  be the printed total.

### 2026-10-01: wrong-row amounts / negative Einkünfte
- Vision prompt: a blank Kennzahl row is "Not Found". The model must never shift a figure from a
  neighbouring row or use the Summe/Gewinn rows.
- `_reject_duplicate_money` (vision + text lanes): an expense is dropped if it equals the income,
  equals another expense, equals the sum of the others, or is negative.
- Text lane: every money value must appear among the numbers printed in the text layer.
  Honorarnoten are exempt.
- Routing: an E1a with no euro amounts in its text layer goes to the vision lane.
- Grundfreibetrag is now `=MAX(0,C20*0.15)` in the template (`scripts/build_ea_template.py` →
  `backend/templates/EA_template.xlsx`) and in the dashboard preview.
- Children fallback: with no FamBH and no questionnaire, the count of L1k forms for the year is used.

### 2026-10-01b: more guards + "newer document wins"
- The sample StNr was removed from the prompt; StNr values that look like placeholders are rejected.
- E-card (Versicherungsnummer) is now requested from E1/E1a and must be exactly 10 digits.
- A Kennzahl code read as an amount is rejected.
- "10.136,00" and "10136" no longer count as a conflict.
- **Newer document wins.** Between two copies of the same form type in one year, the newer
  one is used (by PDF creation date, then modification date, then received date).
  - The older copy's value is kept as "superseded" and not shown as a conflict.
  - It still fills gaps where the newer copy is blank.

### 2026-10-01c: cell-by-cell E1a reading
- FinanzOnline "E 1a-PDF" printouts carry labels and Kennzahl codes as text, but draw the
  amounts as shapes. How the new reader works:
  1. The ai-service finds each Kennzahl row from the text layer.
  2. It crops that row's amount cell and decides "blank" from the pixels, without a model call.
  3. The model reads **only that one cell**, so a figure can no longer move to another row.
- The Summe and Gewinn rows are read as well. The record notes whether expenses add up to the
  Summe and whether income minus Summe equals Gewinn.
- Reisekosten 9160 is read into the `reisekosten` field. It is used only when no km/trips are
  entered.
- Newer-doc rule refined: a line that is blank on a cell-read newer E1a stays blank.
- Scanned E1a with no text layer still use the whole-page read plus the guards above.

### 2026-10-01: tools + one real client import
- `tools/compare_ea.py` compares our merged record with the practice's own EA file for that
  year. It prints only MATCH / WRONG / blank per EA line.
  - It is deployed on the client PC.
  - **Still waiting on the user to paste its output** from there.
- One real client folder was imported on the client PC (client id 9 there) for that
  comparison. Name deliberately not recorded here.

### 2026-10-07: Steuermappe client questionnaire (biggest feature)

Files:
- `backend/static/fragebogen.html` is the single source of the questionnaire. Plain HTML/JS, offline.
- `backend/static/jspdf.umd.min.js` is a local copy of jsPDF.
- `backend/main.py` holds the questionnaire endpoints, PDF detection in intake, invites and Lane 0.
- `database/schema.sql` adds the `questionnaire_invites` table. The backend also creates it at
  startup.
- Dashboard:
  - `clients/[id]/FragebogenInvite.tsx` (new)
  - `fragebogen/page.tsx` (new, the "Fragebogen-Links" tracking page)
  - edits to `page.tsx`, `clients/[id]/page.tsx` and `DocPreview.tsx`

How it works:
1. **Office mode.** Open the client page and click "Fragebogen {year} öffnen".
   - The form POSTs to `/api/questionnaire`.
   - The answers go into that year's record as an intake_sheet form plus an extractions row,
     with **no model**. Answers include name, e-card, StNr, address, hometown, marital status,
     spouse, children, km and trips.
   - `Fragebogen_{year}.html` and `.json` are filed in the client folder.
2. **Public mode.** On the client page, "Link für Klientin {year}" copies
   `https://steuermappe-fragebogen.vercel.app/?r=SM-XXXXXX&y={year}`.
   - The link carries only the ref and year, **never personal data**.
   - The page sends nothing (CSP `connect-src 'none'`).
   - The client's phone builds a PDF with jsPDF. The answers sit in the PDF metadata keywords
     as `STEUERMAPPE1:` + base64 JSON.
   - The client sends the PDF by WhatsApp or e-mail.
3. **Intake.** `_ingest_case` recognises that PDF and reads the answers exactly, without AI. It
   then:
   - routes the PDF to the client by its SM- ref;
   - links the sender's phone or e-mail to that client;
   - marks the invite "zurück" (returned).
4. **Tracking.** The home page links to "Fragebogen-Links", which lists every link as open or
   returned.
5. **Lane 0 skip.** E9, FamBH, Bescheid and .vcf documents are **not extracted** when the
   questionnaire already covers their fields.
   - Money documents (Honorar, SVS, E1/E1a) are always extracted.
   - A manual "Re-extract" always runs (force=True).
- **Branding removed** (Oct 7): the practice name, ©, phone and example domains are gone.
  The page header now reads "Personenbetreuung in Österreich".

### Vercel hosting of the public questionnaire
- Project: `steuermappe-fragebogen` in Vercel team `swapnil-5819`. IDs are in
  `web/fragebogen/.vercel/project.json`.
- Live at: https://steuermappe-fragebogen.vercel.app
- **Rebuild + deploy** after editing `backend/static/fragebogen.html`:
  ```
  ./scripts/build_fragebogen_web.sh
  cd web/fragebogen && npx vercel deploy --prod --yes
  ```
  You need `npx vercel login` on the new Mac first, using the same Vercel account.
  `.vercelignore` excludes `.env*`.
- Security headers come from `vercel.json`: strict CSP, no-referrer, noindex.

### Explainer
- There is a private problem-and-solution explainer page (claude.ai artifact):
  https://claude.ai/artifact/RT3Jt1D9QdnU1BvWTuuSuz
- It contains no client data. Share it from the page's Share menu if needed.

---

## 3. Client-PC state (as of 2026-10-07)

- **Deploy folder** (the folder name is the Postgres volume key, so always deploy *into* it):
  `C:\Users\Sebastian\Desktop\intake\intake-autopilot-mac-handoff-2026-07-21 2`
- Running drop `intake-ship-2026-10-07` on top of 10-01c.
  - Backups sit next to each replaced file as `*.pre-2026-10-07` (and `*.pre-2026-10-01b` etc.).
- **Never overwrite** the client's `docker-compose.yml` or `docker-compose.override.yml`.
  They are customized; GPU, qwen2.5vl:7b.
- Deploy pattern used every time:
  1. Build a zip of full files plus a SHIP-README.
  2. The user copies it over via TeamViewer and runs cmd lines step by step.
  3. Dashboard edits go through `patch_dashboard.ps1`, which compares each file with the expected
     old version, backs it up, then copies.
  4. `docker compose restart backend ai-service`.
  5. `docker logs --tail 30 intake-backend` must show **no MOCK MODE**.
     If it does: `docker compose up -d --no-deps postgres`, then `docker compose restart backend`.
- Known lessons from the last deploy:
  - Docker Desktop must be running before anything else.
  - Unzipping on Windows can nest the folder (`...\intake-ship-X\intake-ship-X\`).
  - The client's `clients/[id]/page.tsx` differed from the Mac copy; it lacked the
    "superseded" badge. The fix was to back it up and copy the new file directly.

---

## 4. Open items / next steps

1. **No way to upload the questionnaire PDF by hand yet.** Today the returned PDF reaches the
   dashboard only through Gmail or WhatsApp → n8n → `/api/intake/case`.
   - `/reviewer` upload uses the legacy path and won't detect it.
   - Proposed: a "Fragebogen-PDF hochladen" button on the Fragebogen-Links page and client page,
     posting to `/api/intake/case`. **Waiting on the user's go.**
2. **Check that the n8n Gmail workflow is Active** on the client PC. Activating it needs the n8n
   browser UI.
3. **Port 8080 on the client PC is reachable from outside.** The backend log shows scanner hits
   (/HNAP1/, /cgi/get.cgi, POST /mcp), all 404 so far. Check Windows Firewall and router port
   forwarding.
4. **compare_ea.py output** from the client PC: still waiting on the user.
5. **Romanian version** of the questionnaire.
6. **Labelled eval set** from the client (ticket 12). Accuracy numbers stay anecdotal until it
   arrives.
7. **WhatsApp intake** is still blocked on Meta business verification.
8. **Test data in the origin Mac's DB:** test client "Maria Testfrau" (id 22) with folder and
   invites, and test case 24 (`q-pdf-test-1`). Delete only with the user's yes. Not present on
   the new Mac.
9. Carried over from 09-01:
   - n8n "Classify Attachments" JS mirror of the vcf/e9/fambh rules;
   - the decision on the `IntakeAutopilot-Sync` scheduled task;
   - FamBH accuracy on hard scans.
10. **Commit everything** (§6).

---

## 5. tools/ (PII-safe check scripts, run inside the backend container)

```
docker cp tools/verify_one.py intake-backend:/tmp/verify_one.py
docker exec intake-backend python /tmp/verify_one.py <form_id>     # re-extract one form; prints yes/no, lanes, sources only

docker cp tools/compare_ea.py intake-backend:/tmp/compare_ea.py
docker exec intake-backend python /tmp/compare_ea.py <client_id>   # our record vs practice EA; MATCH/WRONG/blank per line only
```

---

## 6. Setting up the second Mac

```sh
# 0. Prereqs: Docker Desktop, Node 20+, native Ollama (see SETUP-mac.md)
ollama pull qwen2.5vl:7b

# 1. Unzip. Replace the old copy, don't merge into it (back the old one up if it has local edits).
#    Folder name is your choice on the Mac.
cd intake-autopilot

# 2. Stack WITHOUT containerized ollama (native Ollama owns :11434 on a Mac)
docker compose up -d --build --no-deps postgres n8n backend ai-service

# 3. Schema (idempotent; adds questionnaire_invites etc.)
docker exec -i intake-db psql -U admin -d intake < database/schema.sql
docker restart intake-backend
docker logs --tail 30 intake-backend         # must NOT say MOCK MODE

# 4. Dashboard
cd dashboard && npm install && npm run dev   # http://localhost:3000

# 5. Checks
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/fragebogen          # 200
curl -s http://localhost:8080/api/questionnaire/invites                          # JSON list
```

n8n workflows are not in the DB on a fresh machine. Import them from `n8n/*.json` in the n8n UI
(http://localhost:5678) and activate them in the browser.

**Git, first thing:**
```sh
git status                  # expect lots of M / ?? -- that's normal
git switch wip/next-steps
git add -A                  # .gitignore already keeps storage/ etc. out -- double-check `git status` shows no client files
git commit -m "Snapshot working tree 2026-10-26 (post questionnaire)"
```
`TAX DOCUMENT EXAMPLES*/` (real client documents on the origin Mac) is now in `.gitignore`.
It is not in this zip.

The `.agents/` and `.claude/skills/` deletions in `git status` are intentional leftovers. The
skills were removed from the repo before this handoff.

---

_Generated 2026-10-26. The working tree is authoritative. Check against the actual files before
quoting any file:line as fact._
