Type: grilling
Status: built — awaiting label set (ticket 12) for a meaningful run
Blocked by: 12 (label set only; design questions below are resolved)

## Question

Design the accuracy-eval harness: given the labelled set (ticket 12) and the model decision (ticket 03), what does the harness actually measure (per-field exact-match vs. fuzzy/edit-distance, confidence-calibration check against the model's self-reported scores — which the earlier `llava` test showed were falsely high), how is it run (one-off script vs. something wired into CI-equivalent), and how are results reported/tracked over time as models or prompts change?

## Answer

**Built 2026-08-01. Lives in `eval/` (`run_eval.py` driver + `scoring.py` pure core + `README.md`).** Every design question above is now answered by a concrete decision in code:

- **What it measures (per field, all 12 `FIELD_KEYS`):**
  - **exact** — value matches ground truth after light normalization (whitespace collapsed, case-folded, accents stripped, currency/grouping punctuation removed so `€10,000/-` == `10000`). The honest headline number.
  - **near** — exact OR an edit-distance ratio ≥ `NEAR_THRESHOLD` (0.85, `difflib.SequenceMatcher`). Isolates the "off by a single character on bad handwriting" class (`Arnab`→`AnnaB`, `9`→`7`) from genuinely-wrong values, so turning wrong values into almost-right ones still reads as progress.
  - `is_signed` is scored by boolean equality, never string similarity. Missing-vs-present is scored (a false-positive value where GT is blank counts wrong; `Unknown`/`Not Found`/`""` all collapse to one MISSING sentinel).
- **Confidence-calibration check** — buckets self-reported confidence (0–0.5 / 0.5–0.8 / 0.8–1.0) and prints exact-accuracy per bucket, plus the null-confidence count. This re-tests ticket 15's "confidence is flat / not a usable signal" finding on every run; flat accuracy across buckets = still unusable. If a future model's high bucket is genuinely more accurate, that's the trigger to revisit gating review on confidence and to refresh the dashboard's hardcoded `KNOWN_UNRELIABLE_FIELDS`.
- **How it's run** — a **one-off stdlib-only script** (no CI, no new deps; `urllib`/`json`/`difflib`), run by hand before/after a change. It POSTs each labelled doc to the **real** `/extract` (same JSON shape n8n uses), so it exercises the production path, not a test-only branch. `--against <prior report>` prints per-field exact deltas between two runs.
- **How results are tracked over time** — each run writes a timestamped `eval/reports/eval-<model>-<stamp>.json` (stamped with the model label) and appends a one-line summary to `eval/reports/history.jsonl`.
- **PII** — labels contain real client PII, so `eval/cases/` and `eval/reports/` are gitignored except a synthetic `cases/example.json`. Same rule as `.scratch/`.

**Self-tested:** `scoring.py` logic verified (currency/grouping equivalence, missing-vs-present, false-positive, one-digit-off near-miss, boolean, aggregation, calibration); runner plumbing verified end-to-end to the HTTP boundary. A live extraction run needs the stack up **and** a real labelled set.

**Only remaining blocker: ticket 12** — the client's ground-truth label set. Until it arrives the harness runs only against hand-labelled cases; `example.json` is a schema demo with placeholder lower-field values, not verified truth. This ticket supersedes RUNNING.md's Approach-A "Approach D — build a labelled eval set … deferred as future work": the harness is no longer deferred, only its input is pending.
