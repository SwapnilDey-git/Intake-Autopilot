# Extraction accuracy eval harness

Measures how well `ai-service`'s `/extract` reads the 12 intake fields, against a set
of **labelled** documents (known-correct field values). This replaces the project's
"eyeballed accuracy on 2–4 docs" with a repeatable number, so every prompt / model /
DPI change becomes a measured delta instead of a guess. Implements ticket 13.

**Status:** scaffold + scoring built and self-tested. It needs a labelled ground-truth
set (ticket 12, client-side ask) to produce a *meaningful* accuracy number — until then
it runs, but only against whatever cases you hand-label.

## Why it exists (the standing findings it re-tests)
- Confidence is not a usable signal (ticket 15): the model reports ~flat confidence
  whether right or wrong. The harness's calibration table re-checks this every run — if a
  future model's high-confidence bucket is genuinely more accurate, that's when confidence
  becomes usable to gate review.
- The 4 consistently-wrong fields (`e_card_number`, `name`, `honorare`, `svs_sva`) are
  currently a *hardcoded, per-document* list in the dashboard. Real per-field numbers here
  are what eventually replace that stopgap.

## PII safety
Ground-truth labels contain real client PII (names, e-card/SVNR, addresses, income), so
`cases/` and `reports/` are **gitignored** except this README, the two `.gitignore`s, and
the synthetic `cases/example.json`. Same rule as `.scratch/`: labels never get committed.

## Setup
1. Bring the stack up so `/extract` answers on `:8000` (see `RUNNING.md`).
   On the Mac that's the native-Ollama + `docker compose` setup; the model is whatever
   `MODEL_NAME` resolves to (`qwen2.5vl:7b` on the Mac, `minicpm-v` on the shipped default).
2. Label some documents (below).
3. Run it.

## Case (label) schema
One JSON file per document in `cases/`:

```json
{
  "document": "testdoc/Test Doc 2.pdf",
  "notes": "optional free text",
  "fields": {
    "tax_year": "2025",
    "e_card_number": "215362910778",
    "name": "Swoopneel Deg",
    "address_austria": "Not Found",
    "home_address": "Not Found",
    "honorare": "€10,000000/-",
    "wko_contribution": "Not Found",
    "provision_travel": "Not Found",
    "svs_sva": "Not Found",
    "marital_status": "Not Found",
    "children": "Not Found",
    "is_signed": true
  }
}
```

- `document` — path to the PDF/image, absolute or relative to `--docs-root` (default: repo
  root). Real client forms live in `.scratch/` and can be pointed at directly.
- `fields` — the **ground truth**, transcribed by a human exactly as written. Use
  `"Not Found"` (or `""`) for a field the form genuinely leaves blank. `is_signed` is a
  boolean.
- Transcribe values *literally*, matching the extraction prompt's own contract (keep the
  writer's currency symbols/slashes; the scorer normalizes punctuation/whitespace/case
  before comparing, so you don't have to be pixel-perfect on formatting).

## Run

```bash
# score every real case in eval/cases/
python3 eval/run_eval.py --model-label qwen2.5vl:7b

# plumbing smoke test with no real labels (scores the synthetic example only)
python3 eval/run_eval.py --include-example --model-label qwen2.5vl:7b

# compare against a prior run to see per-field movement
python3 eval/run_eval.py --model-label minicpm-v --against eval/reports/eval-qwen2.5vl-7b-<stamp>.json
```

Useful flags: `--ai-url` (default `http://localhost:8000` / `$AI_SERVICE_URL`),
`--docs-root`, `--timeout` (per-doc seconds; CPU inference is slow — default 900),
`--cases-dir`, `--report-dir`.

## Output
- **Console**: per-field exact% / near% table (with deltas vs `--against`), overall, and
  the confidence-calibration table.
- `reports/eval-<model>-<timestamp>.json` — full report incl. per-case, per-field detail.
- `reports/history.jsonl` — one summary line appended per run, for tracking over time.

## Metrics (defined in `scoring.py`)
- **exact** — value matches ground truth after light normalization (whitespace collapsed,
  case-folded, accents + currency/grouping punctuation stripped). The honest headline.
- **near** — exact, or a near-miss above an edit-distance ratio (`NEAR_THRESHOLD`, 0.85).
  Isolates the "off by a single character on bad handwriting" class from genuinely-wrong
  values, so turning wrong-values into almost-right ones still shows as progress.
- **confidence calibration** — buckets self-reported confidence and shows exact-accuracy
  per bucket. Flat across buckets ⇒ confidence isn't usable (the current finding).

## Files
- `run_eval.py` — CLI driver: reads cases, calls `/extract`, scores, writes reports.
- `scoring.py` — pure comparison logic (field normalization, exact/near, calibration).
  No network/FS deps, so it's the unit-testable core.
- `cases/` — labels (gitignored except `example.json`).
- `reports/` — generated reports + `history.jsonl` (gitignored).
