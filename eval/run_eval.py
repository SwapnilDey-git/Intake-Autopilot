#!/usr/bin/env python3
"""Extraction accuracy eval harness (ticket 13).

Runs the REAL ai-service /extract endpoint against a set of labelled documents and
scores the returned fields against known-correct ground truth. This is the harness
the project has deferred repeatedly ("accuracy is eyeballed on 2-4 docs") -- it turns
every future prompt/model/DPI change into a measured delta instead of a guess.

WHAT IT IS, DELIBERATELY:
  - A one-off script, not CI. Vision inference is slow and needs the stack up; you run
    this by hand before/after a change and compare the two reports.
  - Stdlib-only (urllib, json, difflib). No pip install, runs anywhere Python does.
  - PII-safe by construction: it reads labels from a cases/ directory that is
    gitignored except for one synthetic example. Real client forms + labels live
    there locally and never get committed (same rule as .scratch/).

USAGE:
  1. Bring the stack up so ai-service answers on :8000 (see RUNNING.md), e.g.
       docker compose up -d        # or the Mac native-Ollama setup
  2. Put labelled cases in eval/cases/  (one JSON per document -- see cases/example.json
     and eval/README.md for the schema). Documents are resolved relative to --docs-root
     (default: repo root), so a label can point at `testdoc/Test Doc 2.pdf` or an
     absolute path into `.scratch/`.
  3. Run:
       python3 eval/run_eval.py --model-label qwen2.5vl:7b
     Add --against a prior report JSON to print a per-field delta.

A JSON report is written to eval/reports/ and a one-line summary is appended to
eval/reports/history.jsonl so accuracy is tracked over time as models/prompts change.
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

# Import the pure scoring module as a sibling regardless of CWD.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scoring  # noqa: E402

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CASES_DIR = os.path.join(EVAL_DIR, "cases")
DEFAULT_REPORT_DIR = os.path.join(EVAL_DIR, "reports")
DEFAULT_DOCS_ROOT = os.path.dirname(EVAL_DIR)  # repo root
DEFAULT_AI_URL = os.environ.get("AI_SERVICE_URL", "http://localhost:8000")


def load_cases(cases_dir):
    """Load every *.json label in cases_dir (except the reserved example on request).

    A case file is: {"document": <path>, "fields": {<field>: <value>, ...},
    optional "notes": <str>}. Returns list of (case_path, case_dict).
    """
    if not os.path.isdir(cases_dir):
        sys.exit(f"cases dir not found: {cases_dir}")
    cases = []
    for name in sorted(os.listdir(cases_dir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(cases_dir, name)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "document" not in data or "fields" not in data:
            print(f"  ! skipping {name}: missing 'document' or 'fields'", file=sys.stderr)
            continue
        cases.append((path, data))
    return cases


def extract(ai_url, doc_path, timeout):
    """POST one document to /extract and return (fields, confidence).

    Sends the same JSON shape n8n uses ({"filename","file_base64"}) so the harness
    exercises the exact production code path, not a test-only branch. Raises on
    transport error or a service-level {"error": ...} response so a broken run fails
    loudly instead of scoring zeros.
    """
    with open(doc_path, "rb") as f:
        content = f.read()
    payload = json.dumps({
        "filename": os.path.basename(doc_path),
        "file_base64": base64.b64encode(content).decode("ascii"),
    }).encode("utf-8")

    req = urllib.request.Request(
        ai_url.rstrip("/") + "/extract",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if "error" in body:
        raise RuntimeError(f"/extract returned error: {body.get('error')}: {body.get('message', '')}")
    return body.get("fields", {}), body.get("confidence", {})


def fmt_pct(x):
    return "  n/a" if x is None else f"{x * 100:5.1f}%"


def print_table(overall, per_field, calibration, against=None):
    """Human-readable console report. `against` is a prior report's per_field for deltas."""
    print("\n" + "=" * 68)
    print("PER-FIELD ACCURACY")
    print("=" * 68)
    print(f"{'field':<20}{'n':>4}{'exact':>9}{'near':>9}   {'delta(exact)':>12}")
    print("-" * 68)
    for key in scoring.FIELD_KEYS:
        pf = per_field[key]
        delta = ""
        if against and key in against and pf["exact_pct"] is not None \
                and against[key].get("exact_pct") is not None:
            d = (pf["exact_pct"] - against[key]["exact_pct"]) * 100
            delta = f"{d:+6.1f}pp"
        print(f"{key:<20}{pf['n']:>4}{fmt_pct(pf['exact_pct']):>9}{fmt_pct(pf['near_pct']):>9}   {delta:>12}")
    print("-" * 68)
    print(f"{'OVERALL':<20}{overall['total_fields']:>4}"
          f"{fmt_pct(overall['exact_pct']):>9}{fmt_pct(overall['near_pct']):>9}")

    print("\n" + "=" * 68)
    print("CONFIDENCE CALIBRATION  (is high confidence actually more correct?)")
    print("=" * 68)
    print(f"{'confidence range':<20}{'n':>6}{'exact-accuracy':>18}")
    print("-" * 68)
    for b in calibration["buckets"]:
        print(f"{b['range']:<20}{b['n']:>6}{fmt_pct(b['accuracy']):>18}")
    print(f"\n  fields with a confidence score : {calibration['with_confidence']}")
    print(f"  fields with NULL confidence    : {calibration['null_confidence']}")
    print("  (flat accuracy across buckets => confidence is NOT a usable signal; ticket 15)")


def main():
    ap = argparse.ArgumentParser(description="Extraction accuracy eval harness (ticket 13)")
    ap.add_argument("--cases-dir", default=DEFAULT_CASES_DIR)
    ap.add_argument("--docs-root", default=DEFAULT_DOCS_ROOT,
                    help="base dir for resolving relative 'document' paths (default: repo root)")
    ap.add_argument("--ai-url", default=DEFAULT_AI_URL)
    ap.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    ap.add_argument("--model-label", default="unknown",
                    help="model name to stamp on the report (e.g. qwen2.5vl:7b) -- for tracking")
    ap.add_argument("--timeout", type=int, default=900,
                    help="per-document /extract timeout in seconds (CPU inference is slow)")
    ap.add_argument("--against", default=None,
                    help="path to a prior report JSON; prints per-field exact deltas")
    ap.add_argument("--include-example", action="store_true",
                    help="also score cases/example.json (skipped by default -- it's synthetic)")
    args = ap.parse_args()

    cases = load_cases(args.cases_dir)
    if not args.include_example:
        cases = [(p, c) for p, c in cases if os.path.basename(p) != "example.json"]
    if not cases:
        sys.exit(f"no labelled cases found in {args.cases_dir} "
                 f"(add JSON labels -- see cases/example.json). Use --include-example to test-run.")

    print(f"eval: {len(cases)} case(s) against {args.ai_url}  [model: {args.model_label}]")
    scored_cases = []
    case_records = []
    for case_path, case in cases:
        doc = case["document"]
        doc_path = doc if os.path.isabs(doc) else os.path.join(args.docs_root, doc)
        label = os.path.basename(case_path)
        if not os.path.exists(doc_path):
            print(f"  ! {label}: document not found: {doc_path}  -- skipping", file=sys.stderr)
            continue
        print(f"  - {label}  ->  {doc}")
        t0 = time.time()
        try:
            fields, confidence = extract(args.ai_url, doc_path, args.timeout)
        except (urllib.error.URLError, RuntimeError, TimeoutError) as e:
            print(f"    FAILED: {e}", file=sys.stderr)
            continue
        elapsed = round(time.time() - t0, 1)
        scored = scoring.score_case(fields, confidence, case["fields"])
        scored_cases.append(scored)
        n_exact = sum(1 for r in scored.values() if r["exact"])
        print(f"    {n_exact}/{len(scoring.FIELD_KEYS)} exact   ({elapsed}s)")
        case_records.append({
            "label": label, "document": doc, "elapsed_s": elapsed,
            "exact": n_exact, "fields": scored,
        })

    if not scored_cases:
        sys.exit("no cases scored (all failed or missing) -- nothing to report.")

    overall, per_field = scoring.aggregate(scored_cases)
    calibration = scoring.calibration_report(scored_cases)

    against_per_field = None
    if args.against:
        with open(args.against, "r", encoding="utf-8") as f:
            against_per_field = json.load(f).get("per_field")

    print_table(overall, per_field, calibration, against=against_per_field)

    # Persist a full report + append a compact history line (tracking over time).
    os.makedirs(args.report_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_model = args.model_label.replace("/", "_").replace(":", "-")
    report = {
        "timestamp": stamp,
        "model_label": args.model_label,
        "ai_url": args.ai_url,
        "num_cases": len(scored_cases),
        "overall": overall,
        "per_field": per_field,
        "confidence_calibration": calibration,
        "cases": case_records,
    }
    report_path = os.path.join(args.report_dir, f"eval-{safe_model}-{stamp}.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    history_path = os.path.join(args.report_dir, "history.jsonl")
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "timestamp": stamp, "model_label": args.model_label,
            "num_cases": len(scored_cases),
            "overall_exact_pct": overall["exact_pct"],
            "overall_near_pct": overall["near_pct"],
            "report": os.path.basename(report_path),
        }) + "\n")

    print(f"\nreport : {report_path}")
    print(f"history: {history_path}")


if __name__ == "__main__":
    main()
