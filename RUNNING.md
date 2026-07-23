# Running Intake Autopilot Locally

Practical runbook for every way to start/stop/debug this stack on this machine. See `CLAUDE.md` for the short version and architecture overview; this file is the detailed one.

All commands below assume you're in `S:\intake-autopilot` (Git Bash / WSL-style paths — adjust for PowerShell if needed, noted where it matters). **On macOS**, substitute wherever you put the project (e.g. `~/intake-autopilot`) for `S:\intake-autopilot`, use Terminal instead of PowerShell/Git Bash, and see `SETUP-mac.md` instead of `SETUP.md` for prerequisites — every command below is plain `docker compose`/bash and runs unchanged in Terminal. The one section that's genuinely Windows-only is "`docker info` hangs forever / Docker Desktop won't start" under Troubleshooting (WSL2-specific) — skip it on Mac; if Docker Desktop hangs there, quitting it from the menu bar and relaunching is the equivalent fix.

---

## Quick reference

```bash
docker compose up -d --build     # start everything
docker compose ps                # what's running
docker compose logs -f n8n       # tail logs for one service
docker compose down              # stop everything (keeps data/volumes)
```

n8n UI: http://localhost:5678
Dashboard: http://localhost:3000 (run separately, see Scenario E)
Backend API: http://localhost:8080
AI service: http://localhost:8000

---

## Scenario A — Start the full stack (normal case)

```bash
docker compose up -d --build
docker compose ps
```

First run (or after a `docker-compose.yml`/Dockerfile change) will build `ai-service` and `backend` images and pull `postgres`, `n8n`, `ollama`. Ollama will also pull the vision model (`MODEL_NAME` in `docker-compose.yml`, currently `minicpm-v`) on `ai-service` startup — this can take a while (a multi-GB download) and needs a working internet connection (see Ollama troubleshooting below if it stalls, and "Model choice" further down for the `llava` → `minicpm-v` → `qwen3-vl:8b` (reverted) → `qwen2.5vl:7b` (Mac default) history and why). On the Mac handoff machine this is overridden to `qwen2.5vl:7b` via `docker-compose.override.yml`, served by native Ollama — see the macOS GPU section.

To confirm everything actually came up healthy, not just "started":

```bash
docker compose ps
curl -s -o /dev/null -w "n8n: %{http_code}\n" http://localhost:5678
curl -s -o /dev/null -w "backend: %{http_code}\n" http://localhost:8080/api/forms/pending
curl -s -o /dev/null -w "ai-service: %{http_code}\n" http://localhost:8000/docs
```

## Scenario B — Start/stop individual services

```bash
docker compose up -d n8n                 # start just n8n (+ its dependency postgres)
docker compose stop n8n                  # stop just n8n, keep container
docker compose restart backend           # restart one service
docker compose rm -f n8n && docker compose up -d n8n   # nuke and recreate one container
```

## Scenario C — Rebuild after code changes

`ai-service` and `backend` mount their own source dirs live (`./ai-service:/app`, `./backend:/app`), so plain Python edits take effect on a simple restart — **no rebuild needed**:

```bash
docker compose restart ai-service
docker compose restart backend
```

Only rebuild when `requirements.txt` (or the Dockerfile) changes:

```bash
docker compose up -d --build ai-service backend
```

## Scenario D — Logs / debugging

```bash
docker compose logs -f              # everything, follow
docker compose logs -f n8n          # just n8n
docker compose logs --tail 50 ai-service
docker exec -it intake-db psql -U admin -d intake     # shell into Postgres
docker exec -it intake-n8n sh                          # shell into n8n container
docker exec -it intake-ollama ollama list               # what models Ollama actually has cached
```

## Scenario E — Dashboard (not in docker-compose)

```bash
cd dashboard
npm run dev     # http://localhost:3000
```

## Scenario F — n8n only, without the rest of the stack

If you just want to edit/test the n8n workflow itself and don't need Postgres/AI extraction wired up:

```bash
docker compose up -d n8n
```
(`n8n` depends on `postgres` in `docker-compose.yml`, so Postgres starts too — that's required anyway since n8n stores its own state there.)

## Scenario G — n8n without Docker at all (fallback when Docker won't start)

Useful when Docker Desktop itself is broken (disk-full, WSL2 issues — see Troubleshooting below) and you just need to inspect/edit the workflow JSON or run n8n standalone:

```bash
npx n8n start
```
This runs n8n directly on Node (no Postgres backing it — it'll use its default SQLite state instead, stored under `~/.n8n`). UI still comes up at http://localhost:5678. You can import `n8n/Intake_Flow_Real.json` the same way (see below), but the workflow's Postgres nodes won't have a working "Postgres account" credential configured — you'd need to add one manually pointing at wherever your Postgres actually is, or just use this mode for editing/inspecting the workflow rather than running it end-to-end.

## Importing the workflow

The workflow lives as an export at `n8n/Intake_Flow_Real.json`, not auto-loaded into n8n. To import it:

1. Open http://localhost:5678
2. Menu (⋮ top right, or **Workflows**) → **Import from File**
3. Select `n8n/Intake_Flow_Real.json`
4. It imports named "Phase 8: Real Intake Flow (Fixed V2)", inactive by default — set the Postgres credential (id `"1"` / "Postgres account" in the JSON) to point at `postgres:5432`, db `intake`, user `admin` (see `docker-compose.yml` for the password). If you also want the Gmail intake path (see below), set the Gmail credential (id `"2"` / "Gmail account") via n8n's OAuth2 consent flow. Then activate the workflow if you want either trigger live — **on this n8n version there's no separate Active toggle**; the top-right **Publish** button (name a version, click Publish in the dialog) is what flips `active` to true. The `0 / 1` counter next to it is an issues badge, not the activation control.

**If you're logging into an n8n instance someone else set up** (owner account already exists, credentials unknown): query it directly rather than guessing — `docker exec -e PGPASSWORD=password intake-db psql -h localhost -U admin -d intake -c "SELECT email, \"firstName\", \"lastName\" FROM public.user;"` (n8n's own tables live in the same shared Postgres, since `DB_TYPE=postgresdb` is set in `docker-compose.yml` — there's no separate sqlite file to look in). That gives you the actual owner email to pair with whatever password you were handed; it won't recover a lost password (bcrypt-hashed), but it stops you wasting attempts against a guessed email.

**Repeated re-imports create duplicates** — as of 2026-07-14 this Postgres had **13** rows named "Phase 8: Real Intake Flow (Fixed V2)" in `workflow_entity` from testing over time, all inactive, only one current. Don't trust whichever one the UI search happens to show first: `docker exec -e PGPASSWORD=password intake-db psql -h localhost -U admin -d intake -c "SELECT id, active, \"updatedAt\" FROM public.workflow_entity ORDER BY \"updatedAt\" DESC;"` and take the most recently updated id, then open it directly at `http://localhost:5678/workflow/<id>` to bypass the ambiguous list view. Worth deleting the stale copies next time you're in the UI, but nothing currently automates that cleanup.

Webhook URL once active: `POST http://localhost:5678/webhook/upload-real`

**Activating the workflow requires the n8n UI — it cannot be done via CLI/API from outside.** n8n's "Active" toggle registers the webhook route through its own internal engine (not just a DB flag flip), and that only happens through an authenticated browser session — n8n has user accounts enabled on this instance (confirmed via its logs), so there's no anonymous REST/API shortcut either. If you ask Claude to "activate the pipeline," the honest answer is it can fix everything up to that point but the final toggle is a manual click in the browser at `http://localhost:5678`.

**Important — re-import after editing the JSON file:** n8n stores an imported workflow in its own Postgres tables (`workflow_entity`) the moment you import it; it does **not** stay linked to `Intake_Flow_Real.json` on disk. If you (or Claude) edit the JSON file later, any already-imported copy in the n8n UI is now stale and won't reflect the change — re-run **Import from File** (or manually edit the corresponding node in the UI) to actually pick up the update. As of 2026-07-10 there were 7-8 separate stale imported copies of this workflow sitting in the DB from repeated testing — check the `updatedAt` column before trusting any given copy has the latest fixes:
```bash
docker exec -i intake-db psql -U admin -d intake -t -c "SELECT id, name, active, \"updatedAt\" FROM workflow_entity ORDER BY \"updatedAt\" DESC;"
```
Worth deleting the ones you're not using via the n8n UI (Workflows list → ⋮ → Delete) to avoid confusion about which copy is "live."

## Applying the database schema

**Not automatic** — `docker-compose.yml` doesn't mount `database/schema.sql` as a Postgres init script. Run manually after a fresh `postgres_data` volume (or if `forms`/`extractions`/`reviews` tables don't exist yet):

```bash
docker exec -i intake-db psql -U admin -d intake < database/schema.sql
```

(Or from the host if you have `psql` installed: `psql -h localhost -p 5432 -U admin -d intake -f database/schema.sql`, password `password`.)

The whole file is written to be safely re-runnable (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`), since there's no migration tool — if you pull an update that touches `schema.sql` (e.g. the 2026-07-11 idempotency/audit-log columns below), just re-run the same command against an existing DB; it won't touch existing rows.

## Full teardown / reset

```bash
docker compose down              # stop + remove containers, KEEPS volumes (db data, n8n data, ollama models)
docker compose down -v           # DESTRUCTIVE: also deletes volumes — wipes Postgres data, n8n workflows/credentials, Ollama model cache
```

Use `-v` only if you genuinely want a clean slate; `storage/` (uploaded files, `EA_2025.xlsx`) is a bind mount, not a volume, so `-v` doesn't touch it — delete that directory manually if you want to wipe it too.

---

## Model choice — why `minicpm-v`, not `llava`

The original code hardcoded `MODEL_NAME = "llava"`. Tested on 2026-07-10 against a real handwritten sample (`testdoc/Handwritten Intake Form v2.pdf`) by rendering the page(s) exactly as `ai-service` does and calling Ollama directly to see raw output:

| Field | Ground truth | `llava` | `minicpm-v` |
|---|---|---|---|
| tax_year | 2026 | 2015 ❌ | 2026 ✅ |
| e_card_number | 21069669420 | 7846795 ❌ | 2106969420 ⚠️ (1 digit off) |
| name | Ghosh, Anil | Not Found ❌ | Anile Ghosh ✅ |
| address_austria | Adolf Hitler Sarani, Vienna | "Vienna, Austria" ⚠️ (generic) | Adolf Hitler Sareui, Vienna Austria ✅ |
| home_address | Count Dracula Street, Bucharest | Not Found ❌ | Court Dracula Street, Bucharest Romania ✅ |
| honorare | €10,000 | 6034 ❌ | €10,000/- ✅ |
| wko_contribution | €250 | 0.0 ❌ | €250/- ✅ |
| provision_travel | €100 | Not Found ❌ | €100/- ✅ |
| svs_sva | €20 | 0.0 ❌ | €20/- ✅ |
| marital_status | Married | Not Found ❌ | Married ✅ |
| children | 2 | 1 ❌ | 2 ✅ |
| is_signed | true (page 2 only) | true ⚠️ (hallucinated — only page 1 was sent) | true ✅ (grounded, both pages sent) |

`llava` also returned syntactically malformed JSON on some runs (triggering `ai-service`'s parse-failure path, previously silent — see the logging fix above), on top of the accuracy problems shown here. `minicpm-v` parsed cleanly and got 10/12 fields exactly right with the other 2 off by a single character on genuinely ambiguous handwriting (repeated digits/letters). `_confidence` scores came back `null` from `minicpm-v` in this test — the model didn't populate that part of the response; worth a prompt tweak if per-field confidence actually matters downstream, but it's a separate, smaller problem from extraction accuracy itself.

**To pull an additional model** (e.g. to try something else), the same native-host-pull workaround from the Ollama troubleshooting section below applies — Docker's own `ollama pull` is blocked by TLS interception on this machine regardless of which model you ask for:
```powershell
docker compose stop ollama
$env:OLLAMA_MODELS = "S:\intake-autopilot\storage\ollama_models\models"
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull <model-name>   # auto-starts its own server if needed
taskkill /F /IM "ollama app.exe"   # the native install's tray supervisor — kills the server AND stops it respawning
taskkill /F /IM ollama.exe
```
```bash
docker compose up -d ollama
docker exec intake-ollama ollama list      # confirm it's visible
```
Then set `MODEL_NAME=<model-name>` in `docker-compose.yml` under `ai-service` and `docker compose up -d --build ai-service`.

**Note:** the TLS-interception issue that blocks `docker exec intake-ollama ollama pull` on this machine (see the Ollama troubleshooting section further down) is a property of *this host's network*, not of Ollama or the model — a recipient on a different network may find `ai-service`'s own startup pull (`client.pull(MODEL_NAME)` in `ai-service/main.py`) just works. If it doesn't, the native-host-pull workaround above is the fix; it's not specific to `llava`.

### Tried `qwen3-vl:8b` (2026-07-13), reverted (2026-07-15) — broken, not just slower

`MODEL_NAME` was switched to `qwen3-vl:8b` on 2026-07-13 to match the dev spec's original model recommendation ahead of the Mac handoff — a deliberate handoff decision, not a fix for a measured problem, and at the time nobody had re-run the accuracy comparison against it.

That comparison has now been run (3 separate calls against `testdoc/Handwritten Intake Form v2_removed.pdf`, same document as the table above) and the result is a hard revert, not a close call: **`qwen3-vl:8b` returned unusable output in all 3 runs** — not lower-accuracy field values, but an empty response on the first call and garbled, non-JSON, multilingual gibberish on the other two (e.g. `Uploaded.obuf contctsettucch基数NCY::...`). Root cause, from `intake-ollama`'s logs: Ollama auto-selects a "thinking" chat template/parser for this tag (`renderer=qwen3-vl-thinking`) that expects a structured output format the model's raw generation didn't conform to, so `common_chat_peg_parse` discarded it and the API returned an empty or garbled `content` field regardless of what the model generated internally. This may be fixable (a non-thinking tag variant, or a prompt/parser adjustment in `ai-service`) but that's real implementation work someone would need to pick up deliberately — it isn't something a different test run fixes.

On top of the output problem, a cold load took **~35 minutes** — this Docker Desktop VM has only a 7.6GB total memory ceiling shared across all 5 containers, and an 8B model eats nearly all of it (RSS climbed in slow, disk-bound increments, not a straightforward fast load like `minicpm-v`'s). `MODEL_NAME` is back to `minicpm-v` in `docker-compose.yml` as of 2026-07-15. If revisiting `qwen3-vl:8b`, expect to re-pull it from scratch (it was removed from both the container cache and the native host staging copy after this test to reclaim disk space) and to need the native-host-pull workaround below regardless, since `docker exec intake-ollama ollama pull qwen3-vl:8b` hits the same TLS-interception throttling documented for `llava`.

Also worth noting: this test also cast doubt on `minicpm-v`'s own "10/12" baseline — a separate end-to-end test run (see the idempotency/audit-log section below) found it non-deterministic on the same document across two calls. Treat `minicpm-v` as the current default because it at least produces real output, not because its accuracy number is fully trusted either.

### `qwen2.5vl:7b` on the Mac (2026-07-21) — viable, now this Mac's default (after fixing an app normalization bug)

Tested on the M2 Max Mac handoff machine (32GB unified memory) with **native Ollama on Metal** (see the macOS GPU section below), against the same `testdoc/Handwritten Intake Form v2_removed.pdf`. This is the model the research flagged as the one architecturally-safe qwen candidate — it does **not** use Qwen3's "thinking" chat template, so it doesn't hit the JSON-breaking failure class that killed `qwen3-vl:8b` above.

The first end-to-end result through `/extract` looked *bad*: only **3 of 12 fields** (both addresses + `is_signed`), the other 9 returned `"Unknown"` at confidence `1.0`. That verdict was **wrong** — it was an app bug, not a model weakness:

- Calling native Ollama directly with the exact same prompt/images/options, `qwen2.5vl:7b` actually reads **12/12 fields correctly** (`tax_year=2026`, `e_card_number=2106969420`, `name=Ghosh Anil`, `honorare=€10,000/-`, `svs_sva=€20/-`, etc.) — matching or beating `minicpm-v`'s baseline.
- **Root cause:** `qwen2.5vl` doesn't return a flat scalar per field. It wraps each value in a semantic object — `{"value": {"year": 2026}, "confidence": 1.0}`, `{"value": {"amount": "€250/-"}}`, `{"value": {"number": "210..."}}`, `{"value": {"surname": "Ghosh", "first_name": "Anil"}}`. The app's `coerce_field_value()` in `ai-service/main.py` only knew how to unwrap `{"value": <scalar>}` and address-shaped dicts (`street`/`city`/…), so every *other* nested shape fell through to its `return "Unknown"` fallback. The two address fields survived only because they happened to match the one nested shape the function handled. `minicpm-v` returns flat scalars, so this bug was latent until `qwen2.5vl` exposed it.
- **Fix:** one branch added to `coerce_field_value()` — flatten any object whose values are scalars by joining them (preserving field order). This is exactly the "normalize once, here, so `/extract`'s contract is always a flat string or bool no matter what the model does internally" the function's own docstring already promises; it just didn't cover these shapes. It does **not** touch the flat-scalar path, so `minicpm-v` behaviour is unchanged. After the fix, `/extract` returns **12/12** with correct per-field confidence.

Speed on Metal: ~**8.5s** for the 2-page form warm (vs the ~12-minute CPU-only numbers below), deterministic across runs (`temperature: 0, seed: 42` in `call_model_with_retry`).

**Confirmed on a second document (2026-07-21):** `testdoc/Test Doc 2.pdf` (a different handwritten intake form — E-card `215362910778`, name `Swoopneel Deg`, etc.) also extracted **12/12 correct**, verified field-by-field against the actual handwriting (including faithfully reading a deliberately messy `€10,000000/-` income figure exactly as written, and getting `name` in correct first-surname order). So the 12/12 now holds across two distinct forms, not one. One real-but-minor wrinkle on this doc: the lower-half fields (`honorare`, `wko_contribution`, `provision_travel`, `svs_sva`, `marital_status`, `children`) came back with `null` confidence — the values were all correct, the model just omitted the `confidence` key for those fields, so `/extract` honestly reports `null` rather than fabricating a number. Cosmetic (dashboard shows no confidence badge for them); worth a prompt tweak if per-field confidence matters downstream.

Remaining caveats: still only two documents, both from the same synthetic test set — not yet validated on real client intake forms or more complex/varied layouts, and an independent report exists of `qwen2.5vl` OCR misreads on complex layouts (plus a repetition-loop failure mode, workaround: cap `num_predict`). `qwen2.5vl:7b` is set as **this Mac's default** via `docker-compose.override.yml` (`MODEL_NAME=qwen2.5vl:7b`); the shippable `docker-compose.yml` default stays `minicpm-v` (targets varied hardware, not just this GPU box).

### Why the dashboard doesn't trust model confidence — the deterministic "Format Check" (Approach A, 2026-07-21)

**The problem: self-reported confidence is not a usable correctness signal.** Across every test run the model's per-field `confidence` came back essentially flat regardless of whether the value was right — it was ~1.0 under the old prompt and ~0.9 after the literal-extraction rewrite, but in both cases it stayed high on fields it had *misread* just as readily as on fields it got right. A signal that doesn't move with correctness can't gate review. The dashboard had already reached this conclusion independently (`dashboard/src/app/page.tsx`, the `KNOWN_UNRELIABLE_FIELDS` comment citing "ticket 15"): it demoted the live confidence banner and instead hardcodes a fixed list of fields (`e_card_number`, `name`, `honorare`, `svs_sva`) found unreliable by repeated testing against one document. That list is a stopgap — it's per-document, not calibrated.

**Approach A — a deterministic format/plausibility layer** (`getFormatFlags()` in `page.tsx`). Instead of asking the model how sure it is (a signal it can fake), check the *shape* of each extracted value against what the field must look like — something the model cannot misreport because we compute it ourselves from the output:

- `tax_year` must be 4 digits; `children` must be a 1–2 digit whole number.
- `e_card_number` must be **exactly 10 digits** — the Austrian e-card (SVNR) length. **This is a locked decision: strict 10, not a range.** It was calibrated to fire on `testdoc/Test Doc 2.pdf` (a 12-digit misread) while staying quiet on `TestDoc4.pdf` (a legitimate 10-digit card).
- The four amount fields (`honorare`, `wko_contribution`, `provision_travel`, `svs_sva`) must contain at least one digit.
- `address_austria` / `home_address` must not equal a bare printed form-label token (`romania`, `austria`, `address`) — this catches the specific `home_address → "Romania"` misread where the model grabbed the printed label instead of the handwritten street.

Flagged values surface in a **"Format Check"** warning banner ("… these values do not match their expected format and are likely misreads. Verify against the original photo before approving."), complementing (not replacing) the Missing-Fields and low-confidence banners.

**Deliberately calibrated to catch shape violations ONLY, never implausible-but-valid data.** The synthetic test forms carry intentionally odd values — birth-year-like `1937`, huge incomes — which are *valid shapes* and must NOT flag. Approach A flags a wrong-length e-card or a non-numeric amount; it never flags a number for merely being large or a year for being old. Verified live: the banner fires on Test Doc 2's 12-digit e-card and stays silent on TestDoc4's 10-digit one.

**Why not the alternatives** (analysed 2026-07-21, all rejected):
- **B — multi-sample agreement** (extract 3× at temp>0, flag disagreement): ~3× latency on already-slow inference, and misses *confident* misreads where all three samples agree on the same wrong value.
- **C — prompt-tune the confidence score**: fights a known-bad signal; a model that reports flat confidence isn't going to be talked into calibration by wording.
- **D — build a labelled eval set** and measure real per-field accuracy: the *only* path that would genuinely calibrate confidence and refresh `KNOWN_UNRELIABLE_FIELDS` — but it's real work (ties to the "ticket 12/13" note in `page.tsx`), deferred as future work. Approach A is the pragmatic layer that ships now; D is what eventually replaces the hardcoded list.

**Accuracy across the four test docs** (`testdoc/`, all `qwen2.5vl:7b`, 2026-07-21): `Handwritten Intake Form v2_removed.pdf` 12/12; `Test Doc 2.pdf` 12/12; `Test Doc 3.pdf` ~9/12 (messy scan); `TestDoc4.pdf` 11/12. The remaining misses are genuine handwriting ambiguity on poor photos (`Arnab`→`AnnaB`, `9`→`7`) — exactly the class of error the human-review dashboard exists to catch, and which the literal-extraction prompt deliberately transcribes faithfully rather than "correcting" into a confident wrong guess.

## Performance — CPU-only inference is slow, and why

There's no GPU passthrough configured (`docker exec intake-ollama ls /dev/nvidia*` → nothing), so every token is computed on whatever CPU the host has — on this machine, a 12th Gen Intel Core i7-1255U (a 12-thread mobile/efficiency chip, not built for this). Measured on 2026-07-10 for a 2-page form with `minicpm-v`: **12m37s total**, breaking down as roughly **4m17s loading the 5.5GB model into RAM from disk** (only happens when the model isn't already resident) + **7m32s** encoding/processing the two page-images + **47s** generating the answer. The compute portion is a hardware ceiling — it won't get meaningfully faster without different hardware (this is a known Phase 1 prototype constraint; the target is the client's actual NVIDIA server, not this laptop).

The load-overhead portion *is* avoidable: Ollama unloads a model after `OLLAMA_KEEP_ALIVE` of inactivity (default 5 minutes), so if extraction requests come in more than 5 minutes apart — very likely for a human-review workflow — every single call was paying that ~4 minute reload cost on top of compute. `docker-compose.yml` now sets `OLLAMA_KEEP_ALIVE=30m` on the `ollama` service so the model stays warm across normal usage gaps. If you're testing back-to-back and it's still slow, check `docker logs intake-ollama` for `load_tensors` lines — if you see those on every call, the model isn't staying resident (check the container didn't restart, and that 30 minutes really is enough gap between your tests).

### On macOS: run Ollama natively, not in the container, to actually use the GPU

The CPU-only measurement above is specific to this Windows dev machine, but the *reason* it's CPU-only — no GPU passthrough into the container — generalizes to **any** Docker Desktop host, including Apple Silicon Macs. Docker Desktop for Mac runs containers inside a Linux VM, and there's no Metal/Neural Engine passthrough into that VM (this isn't a config flag that can be turned on — it's a platform limitation, the same class of thing as NVIDIA GPU passthrough not existing on Windows/WSL2 without extra driver setup). So if you just `docker compose up` unchanged on a Mac, `ollama` still runs CPU-only inside the VM — a fast CPU (e.g. M2 Max) will beat the i7-1255U numbers above, but it's leaving the GPU that vision-model inference actually benefits from completely unused.

Fix: install Ollama natively (`brew install ollama`, covered in `SETUP-mac.md` step 5) so it runs directly on macOS and picks up Metal acceleration automatically, then repoint `ai-service` at the host's native Ollama instead of the containerized one via a Mac-local `docker-compose.override.yml`:

```yaml
services:
  ai-service:
    environment:
      - OLLAMA_HOST=http://host.docker.internal:11434
      - MODEL_NAME=qwen2.5vl:7b   # this Mac's default; see the qwen2.5vl:7b section above
```

`host.docker.internal` is Docker Desktop's built-in DNS name for the host machine — works out of the box, no extra networking. Same override mechanism the Windows dev machine used to pin a local `MODEL_NAME` without touching the shippable `docker-compose.yml` — it's per-machine and intentionally not part of the handoff package.

**Important (learned 2026-07-21, corrects earlier guidance):** do **not** just leave the containerized `ollama` service running alongside native Ollama and assume it's harmless. Native Ollama binds host `:11434`, and the `ollama` service in `docker-compose.yml` publishes `11434:11434` — so a bare `docker compose up -d` fails with a host-port conflict. Compose override merge also does *not* let an empty `ports:`/`depends_on:` list clear the base, so you can't neutralize the `ollama` service from the override file. Instead, bring the stack up **without** it (it's only a `depends_on` of `ai-service`, so `--no-deps` keeps it from being pulled in):

```bash
docker compose up -d --build --no-deps postgres n8n backend ai-service
```

Verify the wiring: `docker exec intake-ai env | grep -E 'OLLAMA_HOST|MODEL_NAME'`, then `ollama ps` during a request should show the model at `100% GPU` (not CPU). Note that on Mac the `ollama_models` bind-mount cache in `docker-compose.yml` is unused — native Ollama keeps its own model store (`~/.ollama`), so pull with a plain host `ollama pull <model>`.

---

## Cross-channel inference concurrency (added 2026-07-23, wayfinder ticket 17)

All three intake channels (webhook, Gmail, WhatsApp) call the same `ai-service` `/extract`. Two facts about how that's now handled:

1. **`ai-service` bounds its own concurrency.** The `/extract` route runs the blocking Ollama call in a worker thread (`asyncio.to_thread`) so inference no longer freezes the event loop, gated by a semaphore (`AI_MAX_CONCURRENCY`, default **2**) so at most that many inferences run at once. This replaces the *accidental* full-serialization the code used to have (an `async` route calling the sync Ollama client directly) with an **explicit, tunable** cap. Set `AI_MAX_CONCURRENCY=1` to restore strict one-at-a-time; it's surfaced in `docker-compose.override.yml`.
   - **Why a cap at all:** with the accidental serialization gone, nothing else stops two big vision inferences contending for memory. 2 is comfortable on the 32GB Mac with `qwen2.5vl:7b` (~6–8GB weights + per-request KV/image context); 3–4 pushes the ceiling on large multi-page inputs.

2. **Actual parallel throughput also needs native Ollama's `OLLAMA_NUM_PARALLEL`.** `ai-service` allowing 2 concurrent requests only yields real parallelism if Ollama itself will serve 2 at once. That's governed by `OLLAMA_NUM_PARALLEL` — a **global setting on your native Ollama, shared with every other project on this Mac.** It's intentionally left unset here rather than forced, since changing it affects those other projects too. To opt in: `launchctl setenv OLLAMA_NUM_PARALLEL 2` (or set it in however you launch `ollama serve`) and restart Ollama. If it stays at the default, a 2nd concurrent request simply queues *inside* Ollama — still correct, just serialized there instead of in `ai-service`.
   - **Note the risk calculus is hardware-dependent:** the original concern (a caller's 20-min n8n timeout expiring while forms queue up, triggering a retry-storm) needed ~4 forms queued on the old CPU box (4–9 min/form) but ~141 on the Mac (~8.5s/form) — so at pilot volume this is a non-issue on the Mac regardless.

---

## Idempotency, audit log, travel cost, and error handling (added 2026-07-11)

Four things the client's follow-up email asked for. All four are live in `backend/main.py`, `ai-service/main.py`, `dashboard/src/app/page.tsx`, and `n8n/Intake_Flow_Real.json` — schema changes are in `database/schema.sql` (re-run it per above if your DB predates this).

**The dashboard's manual "Upload Real PDF" button now actually persists to Postgres.** Previously it called `ai-service` directly and held the result in browser state with a fake random ID — nothing was ever written to `forms`/`extractions`, and approving one of those forms against a real (non-mock) DB would have failed a foreign-key constraint. There's a new backend endpoint, `POST /api/forms`, that both the dashboard and (implicitly, via its own Postgres nodes) n8n rely on for this. If you're testing the dashboard upload flow and forms aren't showing up after a page refresh, check this endpoint responded with `{"success": true, "id": ...}` — a `mock: true` reply means the backend isn't connected to Postgres (see the mock-mode gotcha in `CLAUDE.md`).

**Idempotency.** Keyed on `(e_card_number, tax_year)`, per the dev spec (`reference/Phase1_Developer_Specification.md.pdf`, §9). Checked only at **approval** time (`POST /api/forms/{id}/review`), not at intake — a form can sit in the queue without being blocked. If a form with the same e-card + tax year is already `approved`, the new approval is rejected outright (`{"success": false, "reason": "duplicate", "conflicting_form_id": ...}`) rather than silently overwriting the prior Excel row; the reviewer has to resolve it manually (reject the new one, or fix the conflicting data first). This was a deliberate choice over spec's literal "update rather than duplicate" wording — auto-overwriting a tax record without a human confirming felt like the wrong default for a first pass.

**Audit log.** New `audit_log` table — `event_type` one of `extraction`, `extraction_failed`, `approval`, `rejection`, `duplicate_blocked`, `write`; `actor` is a free-text reviewer name (no login system exists, so this is honest labeling, not authentication) or `"dashboard"`/`"n8n"` for system-originated events. Query it directly:
```bash
docker exec -e PGPASSWORD=password intake-db psql -h localhost -U admin -d intake -c "SELECT form_id, event_type, actor, created_at FROM audit_log ORDER BY id DESC LIMIT 20;"
```
The dashboard now has a required "Reviewed by" text field — Approve/Reject are blocked client-side and server-side (`reviewer_name is required`) until it's filled in.

**Travel cost (Reisekosten).** Formula from the dev spec (§7): `distance_km × 2 (round trip) × €0.42/km × trip_count`, capped at €6,000 (Kennzahl 9160). `trip_count` is still **manually entered by the reviewer** (not derivable from geography). `travel_distance_km` is now **auto-suggested** when both addresses are known — see "Travel distance geocoding" below — and falls back to manual entry otherwise. The computed `reisekosten` is written into the `C16` cell of the per-client Excel file — see below.

**Error/fallback paths**, matching the dev spec's §11 list:
- *Low-confidence field* → `ai-service`'s per-field `_confidence` score (already existed) now drives a dashboard banner ("Low-Confidence Fields") when any field is below 0.5 — reviewer sees it before approving, nothing is sent anywhere yet (that's Phase-2/on-hold — see below).
- *Missing field* → any field still `"Not Found"`/`"Unknown"` after extraction gets its own dashboard banner ("Missing Fields"), itemized.
- *Duplicate submission* → see idempotency above.
- *Model/service down* → `ai-service` now retries the Ollama call up to 4 times total (0s/2s/5s/10s backoff) before giving up; a persistent failure returns `{"error": "service_unavailable", ...}` instead of the old generic catch-all. The dashboard's manual-upload path turns that into a `forms` row with `status='failed'` (visible in the queue with a red "Extraction Failed" banner, Approve disabled, Reject available to clear it). The n8n path does the equivalent via the HTTP Request node's own `retryOnFail`/`maxTries`/`waitBetweenTries` + `onError: "continueErrorOutput"` (verified field names against the installed `n8n-core` executor source, same as the earlier binaryData fix) — its error branch inserts a `forms` row with `status='failed'` plus an `audit_log` entry, so a failed extraction from either intake path ends up visible and in the queue rather than silently vanishing, matching the spec's "nothing is lost or sent unreviewed."

---

## Travel distance geocoding (added 2026-07-15)

Full research/design writeup: `.scratch/phase1-next-steps/research/05-geocoding-routing.md` and tickets 05/05a/05b on the Phase1 next-steps map. Short version of the decision: **don't run Nominatim/OSRM as persistent services** — the ~7.6GB Docker Desktop RAM ceiling is already under pressure from Ollama alone, and this project's actual need (a small, semi-static set of carer/client addresses, reimbursement math rather than turn-by-turn routing) doesn't justify a standing geocoding+routing stack. Instead:

- **`address_geocode` table** (`database/schema.sql`): a small Postgres lookup, `(address_text, lat, lon, source, geocoded_at)`. `address_text` is matched verbatim after trimming/lowercasing/collapsing whitespace (`normalize_address_text` in `backend/main.py`) — **no fuzzy matching**, so OCR variance between extractions of the same physical address (e.g. `"Adolf Hitler Sareui, Vienna"` vs `"Adolf Hitler Sarei, Vienna"`, both seen from real test runs of the same form) can miss a lookup hit. Known limitation, not yet solved.
- **Adding a new address** is a deliberate **ad hoc manual step**, not an automated pipeline (per ticket 05a's decision — no formal runbook). Get the address's lat/lon from any map tool and insert directly:
  ```sql
  INSERT INTO address_geocode (address_text, lat, lon, source)
  VALUES ('<address, lowercased/trimmed>', <lat>, <lon>, 'manual')
  ON CONFLICT (address_text) DO NOTHING;
  ```
  The "airgapped at runtime" constraint is about the production inference path, not this one-off admin data-entry step, so using any convenient map/geocoding tool for this is fine.
- **Distance calc**: `compute_travel_suggestion()` in `backend/main.py` looks up both `home_address` and `address_austria` for a form, and if both are known, computes haversine distance × a `TRAVEL_CIRCUITY_FACTOR` (1.25, the middle of the researched 1.2-1.3 range, accepted without pre-validation) as `travel_distance_km` — a straight-line-distance approximation instead of real road routing (see the research doc for why this is an acceptable simplification for a reimbursement calc). `GET /api/forms/pending` now returns a `travel_suggestion: {distance_km, missing_addresses}` per form; the dashboard pre-fills `travel_distance_km` as an editable suggested value (same reviewer-can-correct pattern as every other AI-extracted field) when a suggestion exists, and shows a "No Travel Distance Suggestion" banner naming which address(es) weren't found, falling back to the original fully-manual entry.
- **Verified live** (2026-07-15): seeded `address_geocode` with Bucharest/Vienna test coordinates matching a real pending form's extracted addresses, confirmed `travel_suggestion.distance_km` computed correctly (haversine ≈856km × 1.25 ≈ matches real-world Bucharest–Vienna straight-line distance), approved the form with that suggested value, and confirmed the resulting `C16` (Reisekosten) Excel cell (`899.22`) matched the expected `distance × 2 × €0.42 × trips` calculation exactly.

---

## Per-client Excel writes with a real cell mapping (added 2026-07-11)

Approval no longer appends a row to one flat `storage/EA_2025.xlsx` sheet. It now matches the dev spec's §8/§9 design: each approval copies a template into a per-client file and writes only the input cells, leaving the sheet's built-in `Gewinn`/`Grundfreibetrag`/`Einkünfte` formulas untouched.

**Where files land:** `storage/Clients/{Name}_{TaxYear}/EA_{TaxYear}.xlsx`, where `{Name}` is the extracted `name` field sanitized and underscore-joined in the order written (`backend/main.py`'s `CLIENTS_DIR`/`build_client_folder_name`; see "Name naming is order-preserving" below). The folder is created on first approval for that client+year; a second approval for the same client+year re-opens the existing file rather than re-copying the template (duplicate e-card+tax-year approvals are blocked before this point anyway — see idempotency above).

**The template.** `backend/templates/EA_2025_template.xlsx` — **this is a placeholder, not the client's real sheet.** The client's actual EA_2025.xlsx was never handed over into this repo; the cell layout below is reconstructed from the dev spec's §8 "Data model" table, which the spec author says was "confirmed against the supplied sheet" — but we don't have that sheet to verify it ourselves. Swap this file for the real one (same path, same filename) the moment the client provides it, and diff the cell positions in `EXCEL_CELL_MAP` (`backend/main.py`) against the real file before trusting a production write.

**The cell mapping** (`EXCEL_CELL_MAP` in `backend/main.py`):
| Field | Cell | Note |
|---|---|---|
| `tax_year` | B1 | |
| `e_card_number` | B4 | Versnr. |
| `honorare` | C9 | Leistungserlöse |
| `svs_sva` | D11 | Sozialversicherung 9225 — spec text says "B11/D11", ambiguous which is the value cell; used D11 literally |
| `provision_travel` | C13 | Provisionen 9190 |
| `wko_contribution` | C15 | part of Sonstiger Aufwand 9230 |
| `marital_status` | A23 | |
| `children` | A24 | |
| *(reisekosten, computed)* | C16 | Reisekosten 9160 |

Two things the spec's §8 table mentions but this repo can't resolve without the real file: `address_austria` ("master data, not in the calc sheet" — deliberately not written anywhere in the Excel file) and `A25` (listed as a target cell in the spec with no corresponding source field on our 12-field intake schema — left unmapped).

**Name naming is order-preserving (no firstname/surname split; fixed 2026-07-21).** The intake form captures one free-text `name` field, not separate surname/firstname. The earlier `build_client_folder_name()` *assumed* the first whitespace token was the first name and the rest the surname, producing `Surname_Firstname` — but the literal-extraction prompt now transcribes the name exactly as written, and on these forms that is frequently **surname-first** (e.g. "Ray Arnab" for a person named Arnab Ray), which made the split emit a *swapped* `Arnab_Ray`. Word order can't be recovered from a single free-text token, so the split was removed: the folder is now the name **as written** — each whitespace token sanitized (via `sanitize_path_component`, which strips spaces, so tokens are underscore-joined explicitly) and preserved in original order, i.e. `{token1}_{token2}..._{TaxYear}`. This is the only assumption-free option; the folder name simply mirrors whatever order the writer used. (Downstream consequence: two extractions of the same person in different name orders would create two folders — an inherent limitation of a single free-text name field, not fixable here; the real fix is capturing surname/firstname separately at intake, tracked as future work.)

**Diacritics/path sanitization:** per spec §9 ("sanitise names... keep the original in-sheet"), folder/file names strip diacritics and separators (`sanitize_path_component()`), but the raw value (with diacritics) is still written into the sheet cells themselves.

**What's explicitly still missing**, so it isn't mistaken for done: actually *sending* the "please resend a clearer photo" / "missing field X" Romanian reply (on hold — depends on the WhatsApp WABA verification, a client-side step); the real client Excel template (see above — the cell mapping is a best-effort reconstruction, not verified); self-hosted geocoding/routing for travel distance (manual entry stands in for now, see above); `create_client_folder`/`file_documents` only creates the Excel-holding folder as a side effect of the write — it does **not** yet copy the original form image/PDF into that folder per the spec's `form_original.{jpg|pdf}` convention; the accuracy-threshold evaluation harness (on hold per the client's own "still in development phase" framing — needs a labelled facsimile set from the client first).

---

## Gmail intake path (added 2026-07-11)

`n8n/Intake_Flow_Real.json` now has a second trigger, entirely parallel to the webhook path, so both can be active at once: a carer emailing a photo to a monitored inbox lands in the same review queue as a dashboard upload or a WhatsApp-webhook submission, with no code on either side needing to know which channel a form came from.

**The chain:** `Gmail Trigger` → `Split Attachments` (Code node) → `Loop Over Items (Gmail)` (Split In Batches, `batchSize: 1`) → `Call AI Service (Gmail)` → on success `Insert Form DB (Gmail)` → `Insert Extraction DB (Gmail)` → `Insert Audit Log (Extraction, Gmail)` → loops back into `Loop Over Items (Gmail)`; on failure `Insert Failed Form DB (Gmail)` → `Insert Audit Log (Failure, Gmail)` → also loops back. It's a full duplicate of the webhook path's node chain rather than a shared/merged one — deliberately: Postgres nodes reach back to a specific upstream node by name (e.g. `$node["Split Attachments"].json.filename`) rather than the immediate predecessor (see the webhook path's own `$node["Webhook (Receive File)"]` references), and that pattern breaks if two different trigger chains feed into the same shared node, since only one trigger actually runs per execution. Audit log entries from this path use `actor: 'n8n-gmail'` (vs. plain `'n8n'` for the webhook path) so you can tell channels apart in `audit_log` without cross-referencing anything else.

**Why the loop (added 2026-07-13):** n8n runs a node to completion for its entire input item batch before passing anything downstream. Without the loop, 3 emails arriving in the same poll window meant 3 sequential ~5-9min Ollama extractions inside one execution of `Call AI Service (Gmail)` — easy to exceed `N8N_RUNNERS_TASK_TIMEOUT` (1200s/20min, set in `docker-compose.yml`) and fail the *whole* execution, silently losing DB writes for whichever items hadn't reached the Postgres-insert nodes yet. `Loop Over Items (Gmail)` forces one attachment through the entire extract→insert→audit-log chain, back to the loop node, then the next — each item is fully persisted (or fails on its own) before the next one starts, so a slow/failing item can't take out its siblings.

**Why a Code node here, when the project avoided one for the AI-service call itself:** one Gmail message can carry multiple attachments, landing on a single item as `attachment_0`, `attachment_1`, etc. `ai-service` processes one file per call, so `Split Attachments` fans that single item out into one item per attachment, each with its binary renamed to `data` (matching what the webhook path already produces, so `Call AI Service (Gmail)`'s `inputDataFieldName: "data"` works unchanged). This is pure in-memory reshaping — no network calls, no waiting — so it doesn't hit the 300s task-runner subprocess timeout that ruled out a Code node for the actual `ai-service` call (see the n8n bullet in `CLAUDE.md`). Verified the split logic directly with `node --check` plus a fabricated two-attachment/one-attachment test input before wiring it into the workflow.

**Gmail Trigger config:** polls every minute, `simple: false` + `downloadAttachments: true` (required to actually get attachment binaries — `simple: true`, the node's default, only returns a text snippet), filtered (as of 2026-07-13) to `subject:"Tax Intake Form Test_Email" has:attachment (filename:pdf OR filename:jpg OR filename:jpeg OR filename:png)` and unread messages only — the subject filter is a deliberate addition so random unrelated inbox mail with a PDF/image attachment doesn't get pulled into the pipeline; change the quoted subject string in the node's `filters.q` to whatever the real intake convention ends up being. Gmail's own read/unread state is the dedup mechanism — n8n doesn't currently mark processed messages as read, so if you re-run a message manually in the n8n UI it'll get picked up again on the next real poll unless you mark it read yourself. Fine for now; worth revisiting if duplicate processing becomes a real problem.

**Credential setup (manual, browser-only, same limitation as workflow activation):** the workflow references a Gmail credential (id `"2"` / "Gmail account") that doesn't exist until you create it — and it's per-n8n-instance, not something that transfers when you copy the JSON file to a new machine, so this has to be redone from scratch on every new deployment. In the n8n UI: **Credentials** → **New** → **Gmail OAuth2 API**. This needs a Google Cloud OAuth setup first, done once per machine/instance:

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project (or reuse one), then **APIs & Services → Library**, search **Gmail API**, click **Enable**. (A separate step from the OAuth client below — both are required, and enabling can take a couple minutes to propagate.)
2. **APIs & Services → OAuth consent screen**: set it up in **Testing** publishing status, not Production — the scopes n8n's Gmail node requests (`https://mail.google.com/`, `gmail.modify`, `gmail.compose`) are Google "restricted" scopes that require a full Google verification review to publish to Production, which is unnecessary overhead for a single-inbox local setup. Under **Test users**, add the exact Google account you'll sign in with when connecting the credential (Testing mode caps you at 100 test users and skips verification, but only allowlisted accounts can complete the consent flow — everyone else gets a 403 `access_denied`).
3. **APIs & Services → Credentials → Create Credentials → OAuth client ID**, application type **Web application**. Under **Authorized redirect URIs**, add exactly: `http://localhost:5678/rest/oauth2-credential/callback` (n8n's fixed OAuth callback path — a mismatch here is the single most common failure, surfaced as `redirect_uri_mismatch`). Copy the generated Client ID and Client Secret.
4. Back in n8n's **New Gmail OAuth2 API credential** form, paste the Client ID/Secret from step 3, save, then click **Connect my account** and complete the Google consent screen using the Test User account from step 2.

Until that credential exists and is attached to the `Gmail Trigger` node, the workflow will fail to activate with a missing-credential error — this is expected, not a bug. Note also: if the `Gmail Trigger` node errors during workflow activation (e.g. because the Gmail API wasn't enabled yet per step 1), n8n can leave the workflow showing "Active" in the UI while never actually registering — if the webhook/poll doesn't seem to be firing after activation, confirm via `SELECT * FROM webhook_entity;` (webhook path) or just toggle Active off and back on once the underlying issue is fixed, rather than trusting the toggle's visual state alone.

**What's explicitly still missing on this path:** the credential itself (client-side Google Cloud/OAuth setup, not something built from code); marking messages as read/processed after a successful run; and everything downstream that's already missing for the webhook path too (Romanian auto-reply, real Excel template, self-hosted geocoding) — this path converges on the exact same `forms`/`extractions` tables and inherits all of that as-is.

---

## Troubleshooting

### `docker info` hangs forever / Docker Desktop won't start

This happened on this machine on 2026-07-09/10: `C:` drive was 95% full (20GB free out of 378GB), and Docker Desktop's WSL2 backend VM (`docker-desktop` distro) refused to start — `docker info` just hung indefinitely with no error.

**Diagnose:**
```bash
docker info          # if this hangs >15s with no output, the backend VM isn't up
```
```powershell
wsl --list --verbose                          # check docker-desktop distro state
Get-Process | Where-Object Name -like "*docker*"   # backend process alive but VM not responding = stuck, not just "not started"
```

**Fix, in order of effort:**

1. **Free disk space on `C:`** — check what's actually using it:
   ```powershell
   Get-ChildItem "$env:LOCALAPPDATA\Docker\wsl" -Recurse -Filter "*.vhdx" | Select FullName, @{N='SizeGB';E={[math]::Round($_.Length/1GB,2)}}
   pip cache purge
   docker builder prune -af      # once docker IS responding — clears reclaimable build cache (was 18GB+ on this machine)
   docker image prune -a         # removes unused images too (more aggressive)
   ```

2. **Restart Docker Desktop cleanly:**
   ```powershell
   wsl --shutdown
   Get-Process "Docker Desktop","com.docker.backend" -ErrorAction SilentlyContinue | Stop-Process -Force
   Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
   # wait ~30-60s, then:
   docker info
   ```
   **Warning:** force-killing the backend while containers are running stops them ungracefully (`Exited (255)`). Bring the stack back with `docker compose up -d` afterward.

3. **Compact Docker's WSL2 virtual disk** (reclaims space `docker builder prune` frees *inside* the VM but that doesn't shrink the host `.vhdx` file on its own — WSL2 disks are sparse and grow-only until compacted). **Requires an elevated (Administrator) PowerShell** — this sandbox couldn't do it, run it yourself:
   ```powershell
   wsl --shutdown
   $vhdx = "$env:LOCALAPPDATA\Docker\wsl\disk\docker_data.vhdx"
   @"
   select vdisk file="$vhdx"
   attach vdisk readonly
   compact vdisk
   detach vdisk
   exit
   "@ | diskpart
   ```

4. **Relocate Docker's disk image to a drive with more room** (this machine's `S:` has 49GB free, barely used, vs. `C:` at 95% full). No config-file override exists for this — it's a GUI-only setting:
   - Docker Desktop → **Settings** → **Resources** → **Advanced** → **Disk image location** → change to e.g. `S:\DockerData` → **Apply & Restart**. Docker Desktop moves the existing data for you.

### Ollama model pull stuck / failing (`Error: EOF` on "pulling manifest")

Seen on 2026-07-09/10, **separate from the disk-space issue**: `docker exec intake-ollama ollama pull llava` fails almost immediately with `Error: EOF` while "pulling manifest" — before any data even transfers. `ai-service` doesn't hard-block on this (the pull is wrapped in try/except in `ai-service/main.py`), so the service itself comes up fine, but `/extract` will fail at request time since no model is actually cached (`docker exec intake-ollama ollama list` shows empty).

**Root cause: TLS interception on this Windows machine, scoped to traffic through Docker's WSL2 network path.** A plain `curl -sv https://registry.ollama.ai/v2/` from the host succeeds, but only after an SSL/TLS renegotiation round-trip (`schannel: remote party requests renegotiation`) — something (AV HTTPS scanning or similar) is intercepting outbound TLS. `curl` tolerates the renegotiation retry; Ollama's Go HTTP client running *inside the container* doesn't, and fails outright with `EOF`. Confirmed by testing a **native Windows** Ollama install (not through Docker/WSL2 networking) — that pull succeeded cleanly with no EOF, proving it's the container network path specifically, not the whole machine.

**Fix that worked (2026-07-10) — pull natively on the host, into the same shared folder Docker mounts:**

The `ollama` service in `docker-compose.yml` mounts `./storage/ollama_models:/root/.ollama`, i.e. the container's entire Ollama home directory is just that host folder. So a model pulled natively on Windows, straight into that same folder, is immediately visible inside the container — no copying, no format conversion (Ollama's blob/manifest layout is portable).

```powershell
# 1. Free port 11434 so the native server can bind it
docker compose stop ollama

# 2. Point a native Ollama install at the SAME folder Docker mounts, and pull
$env:OLLAMA_MODELS = "S:\intake-autopilot\storage\ollama_models\models"
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" serve   # run this in one window/background process
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull llava   # in another — ~4.7GB, takes a few minutes

# 3. Once "success" prints, stop the native server and give the port back to Docker.
# The native Windows install runs a persistent tray supervisor ("ollama app.exe") that
# respawns the server if you only kill ollama.exe — kill both, tray process first:
taskkill /F /IM "ollama app.exe"
taskkill /F /IM ollama.exe
```
```bash
# 4. Bring Docker's ollama back up — it'll see the model immediately via the bind mount
docker compose up -d ollama
docker exec intake-ollama ollama list          # should now show the model, e.g. llava:latest ~4.7GB
docker compose restart ai-service              # so it picks up the now-present model
```

Requires a native Ollama install on the host (`ollama.exe`) — install from ollama.com if not already present; this machine already had one at `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`. If a pull gets interrupted partway (e.g. session restart), just retry the same `pull` command — Ollama resumes rather than restarting from zero, though it may re-verify/re-download more than you'd expect if the partial data isn't fully intact.

**If this doesn't work / no native install available, other things to try:**
- Temporarily disable antivirus "HTTPS/TLS scanning" (not the whole antivirus) and retry the pull *inside* the container — this was the leading theory before the native-pull workaround confirmed the container-network-path diagnosis.
- Check for a system-wide HTTP(S)_PROXY env var or corporate MITM proxy/cert that Docker Desktop's WSL2 VM inherits (checked on this machine — none present) — if present, Ollama needs `HTTPS_PROXY` set correctly *and* the proxy's CA cert trusted inside the container, or it needs to bypass the proxy entirely.
- Leftover corrupt partial blobs from an earlier failed/interrupted pull can also cause stalls — clean them out before retrying: `rm -f storage/ollama_models/models/blobs/*-partial*`.

### n8n workflow fails with `Task execution timed out after 300 seconds`

Seen on 2026-07-10, **after `llava` was successfully pulled and the pipeline actually started running end-to-end for the first time**. This is n8n's own error, not Docker's or Ollama's, and it's easy to misdiagnose as a networking problem — it isn't.

**Root cause:** n8n's `Code` node type (JavaScript) executes in a separate sandboxed subprocess called a "task runner." That subprocess has a hard wall-clock limit — `N8N_RUNNERS_TASK_TIMEOUT`, default 300 seconds — that kills it regardless of what it's doing, including sitting inside an `await` on a slow external HTTP call. The original "Call AI Service" node in `Intake_Flow_Real.json` was a Code node that manually called `ai-service` via `this.helpers.httpRequest(...)`. Confirmed via `docker logs intake-ollama`: a single `llava` extraction call took **9m14s** end to end (CPU-only inference — image encoding alone was ~115s, then text generation at under 2 tokens/sec) — nowhere close to fitting inside 300s. `docker logs intake-n8n` showed the matching failure: `Task runner timed out during task, restarting... Task execution timed out after 300 seconds`.

**Fix applied (2026-07-10), both parts:**
1. `docker-compose.yml` — added `N8N_RUNNERS_TASK_TIMEOUT=1200` (20 min) to the `n8n` service as a safety margin. Requires recreating the container to take effect (`docker compose up -d n8n`, not just `restart` — env var changes need a recreate).
2. `n8n/Intake_Flow_Real.json` — replaced the Code node with a native **HTTP Request** node (`n8n-nodes-base.httpRequest`, `typeVersion 4.4`) calling `ai-service` directly via multipart form-data. HTTP Request nodes run in n8n's main process, not the task-runner sandbox, so they're never subject to `N8N_RUNNERS_TASK_TIMEOUT` at all — only their own per-node `options.timeout`, which is explicitly set to `1200000` (ms) on this node. (Note: HTTP Request nodes have their *own* separate 300-second default timeout if you don't set this option — confirmed by reading the installed node's source, `HttpRequestV3.node.js` — so this option isn't optional here.)

**If you see this error again after re-importing the updated workflow:** it means a single extraction is taking longer than 20 minutes, which on CPU-only Ollama is possible for a large/complex form image. Raise both numbers together (`N8N_RUNNERS_TASK_TIMEOUT` in `docker-compose.yml` and `options.timeout` on the HTTP Request node, in milliseconds) rather than just one — they're independent settings that both need enough headroom.

**Remember:** editing `Intake_Flow_Real.json` on disk does not update an already-imported workflow in the n8n UI — see the re-import note above.

### n8n "Call AI Service" node fails: `This operation expects the node's input data to contain a binary file 'data', but none was found`

Seen on 2026-07-10, on the first real test upload after the workflow was activated. Not a networking or model problem — the file never made it into a binary property n8n could see.

**Root cause:** the Webhook node's `options` were empty (`{}`), and n8n's Webhook node does **not** always name an uploaded file's binary property `"data"` — the actual behavior (confirmed by reading the installed `Webhook.node.js`/`utils.js` source, not docs) depends entirely on how the client's request was shaped:
- `multipart/form-data` upload → the binary property is named after whatever **form field key** the uploading client used (e.g. curl's `-F "file=@x.pdf"` → property `file`, not `data`). If you instead explicitly set `options.binaryPropertyName` on the node, n8n *still* doesn't use that name literally — it appends a numeric suffix (`data0`, `data1`, ...).
- any other content-type, on this node's `typeVersion: 1` → falls through to a JSON-only branch with **no binary property at all** unless `options.rawBody` is also set.

Neither of those matches what the downstream nodes expect (`data`, no suffix) unless the test client happens to send a multipart field literally named `data` — fragile and easy to break by testing with a different tool next time.

**Fix applied (2026-07-10):** set `"binaryData": true` in the Webhook node's `options`. This is n8n's built-in explicit switch for "treat the whole POST body as one file" — checked *before* the content-type branching, so it produces a deterministic binary property literally named `data` (via `options.binaryPropertyName ?? 'data'`) regardless of what content-type or field name the client sends. No downstream node needed to change — "Call AI Service" and "Insert Form DB" already referenced `data`.

**This requires uploading the file as a raw POST body, not multipart/form-data** (multipart's boundary markers would get treated as part of the file bytes if `binaryData: true` is on — don't mix the two). Correct test command once the workflow is active:
```bash
curl -X POST --data-binary @"testdoc/Handwritten Intake Form v2.pdf" -H "Content-Type: application/pdf" http://localhost:5678/webhook/upload-real
```
(This is a slow call — see "Performance" above; expect several minutes before it returns.)

**Remember to re-import** after this JSON change too, same as any other edit to `Intake_Flow_Real.json` — see the re-import note above.
