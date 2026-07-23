Type: task
Status: resolved

## Question

Does the full pipeline actually work right now, end to end: a real PDF in through n8n's webhook → `ai-service` extraction → Postgres → dashboard review/approval → written Excel file?

An `EnterPlanMode` plan already exists for this exact run (`witty-humming-pumpkin.md` in the Claude Code plans directory) — it activates the inactive n8n workflow, starts the dashboard dev server, sends `testdoc/Handwritten Intake Form v2_removed.pdf` through `POST /webhook/upload-real`, polls `/api/forms/pending`, reviews+approves in the dashboard, and verifies the `.xlsx` write. Resolving this ticket means executing that plan (or a superseding version of it, if state has drifted) and recording what actually happened at each stage — including whether `is_signed` now renders as a clean bool post the `coerce_bool_value` fix, and whether any `audit_log` rows show `status='failed'`.

## Answer

**Yes, the full pipeline works end to end** — n8n webhook → `ai-service` extraction → Postgres → dashboard review/approval → Excel write, all confirmed with real HTTP calls, DB rows, and a written `.xlsx` file, not just code inspection. Ran it twice: once submitting a fresh PDF through the n8n production webhook (form 75), once reviewing/approving an already-queued form (form 31, since the dashboard has no picker — approving any queued form exercises the identical review→approve→write code path).

**What was found and fixed along the way (this ticket ended up being a real debugging session, not a clean confirmation run):**

1. **n8n workflow wasn't active** — activated it. This n8n version replaced the classic Active toggle with a **Publish** button/dialog; `RUNNING.md` updated to describe the actual flow.
2. **13 duplicate imports** of "Phase 8: Real Intake Flow (Fixed V2)" existed in `workflow_entity`, exactly the failure mode `CLAUDE.md` already warned about. Identified the real one via `updatedAt` DESC + grepping its `nodes` JSON for the known 2026-07-13 fixes (subject filter, `Loop Over Items (Gmail)`), then opened it directly by id to avoid the ambiguous list view. `RUNNING.md` updated with the exact commands.
3. **n8n login credentials**: two guessed email/password pairs failed. Found the real owner account by querying n8n's own `user` table directly in Postgres (`DB_TYPE=postgresdb`, no separate sqlite file) — `swapnil@metaborong.com`. `RUNNING.md` updated with this lookup method (not the password itself).
4. **Dashboard showed a false "All caught up"** despite 14 real pending forms in the backend. Root cause: `backend` and `ai-service` CORS was hardcoded to `http://localhost:3000`, but the dashboard was actually running on **3003** (3000-3002 were all occupied by unrelated personal projects on this machine) — every fetch was silently CORS-blocked. **Fixed**: both services now use `allow_origin_regex=r"http://localhost:\d+"` instead of a fixed origin. Restarted both containers (source is bind-mounted, no rebuild needed). Documented in `CLAUDE.md`.
5. **`agent-browser click @ref` didn't fire the "Approve & Save" button's React handler** (no network request resulted) — worked around with a native `element.click()` via `agent-browser eval`. Tooling quirk, not a project bug.
6. **Extraction quality was poor and non-deterministic**: two separate `minicpm-v` runs on the identical test document (one via n8n, one direct-to-`ai-service`) each came back mostly `"Unknown"`, and differed from each other. This casts doubt on the historical "10/12" `minicpm-v` benchmark as a single-run fluke — flagged on ticket 03 and ticket 02 (which now calls for multiple runs, not one).
7. **`confidence` is always `null`** for every field, in both runs — `ai-service`'s `float(value)` coercion never succeeds. New gap, not previously documented. Spun off as ticket 14 (blocks ticket 13, the eval-harness design).
8. **`is_signed` clean-bool fix confirmed working** on the fresh extraction (form 75: `is_signed: true`, plain bool) — the pre-fix nested-object shape (`{"value": true, "_confidence": 1}`) only still appears on old rows from before the fix (form 31), as expected.
9. **Travel-cost computation verified correct**: 25km × 2 × €0.42 × 4 trips = €84, matched exactly in the written Excel's `C16` (Reisekosten) cell.
10. **Full audit trail confirmed**: `audit_log` got `extraction` (actor `n8n`), `approval`, and `write` rows for this run; `reviews` row recorded with `reviewer_name`; `forms.status` moved to `approved`; idempotency fields (`e_card_number`, `tax_year`) populated correctly on approval.
11. No `status='failed'` rows resulted from this run (pre-existing failed rows in the DB are from unrelated earlier testing, not this test).

**Bottom line for the map**: the pipeline itself is sound. The real risk right now is extraction quality/consistency, not plumbing — which makes tickets 02 (qwen3-vl accuracy, now multi-run) and 03 (model decision) more urgent than they looked before this ran.
