Type: task
Status: resolved
Blocked by: 15

## Question

Implement the dashboard-side decision from ticket 15: stop presenting the model's per-field confidence score as if it were a meaningful signal (it's proven to always report 1.0 regardless of correctness), and replace it with static reviewer guidance based on what that investigation empirically found.

Concretely, in `dashboard/src/app/page.tsx`:
- Retire (or at minimum de-emphasize) the existing low-confidence-fields banner, since it's driven by a score that's now known to never vary.
- Add a fixed "always double-check these fields" notice — currently `e_card_number`, `name`, `honorare`, `svs_sva` — surfaced regardless of what the model's confidence value says, since those are the fields empirically found to be unreliable.
- Worth deciding at implementation time whether this list should be hardcoded in the frontend or driven by a small backend-side config (env var / constant in `backend/main.py`), so it doesn't require a dashboard redeploy if the known-weak-field list changes after ticket 12/13 give more data.

Backend's `confidence` field in the API response doesn't need to be removed — ticket 15 didn't decide to stop *computing* it, only to stop *trusting* it in the reviewer UI. Leave the plumbing in place in case a differently-calibrated model replaces `minicpm-v` later and confidence becomes meaningful again.

## Answer

Implemented in `dashboard/src/app/page.tsx`. Went with a hardcoded frontend constant (`KNOWN_UNRELIABLE_FIELDS`) rather than backend-driven config — matches this dashboard's existing pattern of no env config, and the list only needs to change when someone edits code anyway.

Removed the old confidence-driven "Low-Confidence Fields" banner and its supporting `currentConfidence`/`lowConfidenceFields`/`LOW_CONFIDENCE_THRESHOLD` computation entirely (dead code once nothing reads it — per project convention, deleted rather than left unused). Replaced with a "Historically Unreliable Fields" banner that always shows `e_card_number, name, honorare, svs_sva` when present and not already caught by the missing-fields banner (so it also catches the more dangerous case: a plausible-looking but wrong value, like a wrong-but-well-formatted e_card_number, which the missing-fields check can't see).

`Form.confidence` and the backend's confidence computation are untouched — still returned by the API, just no longer read by the frontend.

Verified live: pushed the test document through the full pipeline (form 82), confirmed via screenshot the new banner renders correctly ("HISTORICALLY UNRELIABLE FIELDS: e_card_number, name, honorare, svs_sva — the AI model has been wrong on these fields even when it looked confident..."), no trace of the old confidence banner, `npm run lint` clean. Test row deleted afterward.
