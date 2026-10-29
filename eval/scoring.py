"""Field-comparison logic for the extraction accuracy harness.

Kept separate from run_eval.py (the I/O / HTTP driver) so the scoring rules are
pure functions with no network or filesystem dependencies -- they can be reasoned
about and unit-tested in isolation, which matters because these rules are exactly
what "accuracy" means for this project and will be argued over as the number moves.

The 12 intake fields (FIELD_KEYS, mirrored from ai-service/main.py) are scored
independently. Eleven are free-text strings; `is_signed` is a boolean and is scored
by boolean equality, never string similarity.

Two levels of correctness are reported per field, because the repo's own history
shows both matter:
  - EXACT  : the value matches the ground truth after light normalization
             (whitespace collapsed, case-folded, currency/punctuation noise removed).
             This is the honest headline number.
  - NEAR   : EXACT, OR a single-/few-character miss (edit-distance ratio above
             NEAR_THRESHOLD). The RUNNING.md accuracy notes repeatedly describe
             misses as "off by a single character" on ambiguous handwriting
             (`Arnab`->`AnnaB`, `9`->`7`); NEAR isolates that class from a genuinely
             wrong value so a prompt/model change that turns wrong-values into
             almost-right ones is still visible as progress.

No third-party deps: difflib.SequenceMatcher (stdlib) supplies the similarity ratio,
so the harness runs anywhere Python does without a pip install.
"""

import re
import unicodedata
from difflib import SequenceMatcher

# Mirror of ai-service/main.py's FIELD_KEYS. Kept as a literal (not imported) so the
# harness has no dependency on the service package being importable -- it talks to
# /extract over HTTP, not in-process.
FIELD_KEYS = [
    "tax_year", "e_card_number", "name", "address_austria", "home_address",
    "honorare", "wko_contribution", "provision_travel", "svs_sva",
    "marital_status", "children", "is_signed",
]

BOOL_FIELD = "is_signed"

# Above this SequenceMatcher ratio (0..1) a non-exact string counts as NEAR -- a
# near-miss rather than a wrong answer. 0.85 lets a single wrong/extra/missing char
# through on a short value (e.g. a 10-digit e-card with one bad digit ~= 0.9) while
# still failing a value that's substantively different.
NEAR_THRESHOLD = 0.85

# Values the model/ground-truth use to mean "this field has no answer". All collapse
# to the same MISSING sentinel so "Unknown" (model) and "Not Found" (prompt/label)
# and "" compare equal, and a present-vs-missing mismatch is scored as wrong.
_MISSING_TOKENS = {"", "unknown", "not found", "n/a", "na", "none", "-", "--"}
MISSING = "\x00__missing__"


def _strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize_text(value):
    """Fold a raw field value to a canonical comparison form.

    Removes exactly the noise that should NOT count as an extraction error:
    surrounding/again-internal whitespace, letter case, accents, and currency /
    grouping punctuation (currency symbols, spaces, and the `,`/`.`/`/` `-` marks
    the literal-extraction prompt deliberately preserves in amounts like
    `€10,000/-`). What's LEFT -- the significant digits/letters -- is what a human
    reviewer would call "the same value". Returns the MISSING sentinel for any
    empty / not-found value so present-vs-absent is scored, not silently matched.
    """
    if value is None:
        return MISSING
    if isinstance(value, bool):  # guard: bools must never reach text scoring
        return "true" if value else "false"
    s = str(value).strip().lower()
    s = _strip_accents(s)
    if s in _MISSING_TOKENS:
        return MISSING
    # Drop currency symbols and grouping/punctuation noise ENTIRELY (so `10,000`,
    # `10.000` and `10000` compare equal -- the separators the writer used for a
    # single number must not count as a difference), then collapse real whitespace
    # to single spaces (so distinct tokens like a two-word name stay separated).
    s = re.sub(r"[€$£,./\\\-]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s if s else MISSING


def coerce_bool(value):
    """Match ai-service's own is_signed coercion so the harness compares like-for-like."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1")
    return False


def similarity(a, b):
    """Edit-distance-based similarity in [0,1] between two normalized strings."""
    if a == MISSING or b == MISSING:
        return 1.0 if a == b else 0.0
    return SequenceMatcher(None, a, b).ratio()


def score_field(key, predicted, expected):
    """Score one field against ground truth.

    Returns a dict: {exact: bool, near: bool, ratio: float, predicted, expected,
    pred_missing, exp_missing}. `near` is always True when `exact` is True.
    """
    if key == BOOL_FIELD:
        p, e = coerce_bool(predicted), coerce_bool(expected)
        exact = p == e
        return {
            "exact": exact, "near": exact, "ratio": 1.0 if exact else 0.0,
            "predicted": p, "expected": e, "pred_missing": False, "exp_missing": False,
        }

    p, e = normalize_text(predicted), normalize_text(expected)
    exact = p == e
    ratio = similarity(p, e)
    near = exact or (p != MISSING and e != MISSING and ratio >= NEAR_THRESHOLD)
    return {
        "exact": exact, "near": near, "ratio": round(ratio, 3),
        "predicted": None if p == MISSING else str(predicted),
        "expected": None if e == MISSING else str(expected),
        "pred_missing": p == MISSING, "exp_missing": e == MISSING,
    }


def score_case(predicted_fields, predicted_confidence, expected_fields):
    """Score every FIELD_KEY for one document.

    predicted_fields / predicted_confidence come straight from /extract's
    {"fields": ..., "confidence": ...} response; expected_fields is the ground-truth
    label. Missing keys on either side are treated as absent (MISSING), never crash.
    Returns {field: {...score..., confidence: float|None}}.
    """
    out = {}
    for key in FIELD_KEYS:
        result = score_field(key, predicted_fields.get(key), expected_fields.get(key))
        conf = (predicted_confidence or {}).get(key)
        result["confidence"] = conf if isinstance(conf, (int, float)) else None
        out[key] = result
    return out


# --- Confidence calibration ------------------------------------------------------
# The project's standing finding (ticket 15) is that self-reported confidence is
# ~flat regardless of correctness -- "not a usable correctness signal". This bucketed
# check is how the harness keeps re-testing that claim as models/prompts change: if a
# future model's high-confidence bucket really is more accurate than its low-confidence
# bucket, THAT is when confidence becomes usable to gate review. Until then it prints
# the evidence that it isn't.
CONFIDENCE_BUCKETS = [(0.0, 0.5), (0.5, 0.8), (0.8, 1.0001)]


def calibration_report(scored_cases):
    """Aggregate confidence vs. correctness across all scored cases.

    scored_cases: list of the per-case dicts returned by score_case().
    Returns {buckets: [{range, n, correct, accuracy}], null_confidence, with_confidence}.
    """
    buckets = [{"lo": lo, "hi": hi, "n": 0, "correct": 0} for lo, hi in CONFIDENCE_BUCKETS]
    null_conf = 0
    with_conf = 0
    for case in scored_cases:
        for key, r in case.items():
            conf = r["confidence"]
            if conf is None:
                null_conf += 1
                continue
            with_conf += 1
            for b in buckets:
                if b["lo"] <= conf < b["hi"]:
                    b["n"] += 1
                    b["correct"] += 1 if r["exact"] else 0
                    break
    return {
        "buckets": [
            {
                "range": f"{b['lo']:.1f}-{min(b['hi'], 1.0):.1f}",
                "n": b["n"],
                "correct": b["correct"],
                "accuracy": round(b["correct"] / b["n"], 3) if b["n"] else None,
            }
            for b in buckets
        ],
        "null_confidence": null_conf,
        "with_confidence": with_conf,
    }


def aggregate(scored_cases):
    """Roll per-case field scores up into per-field and overall exact/near rates."""
    per_field = {k: {"exact": 0, "near": 0, "n": 0} for k in FIELD_KEYS}
    for case in scored_cases:
        for key, r in case.items():
            pf = per_field[key]
            pf["n"] += 1
            pf["exact"] += 1 if r["exact"] else 0
            pf["near"] += 1 if r["near"] else 0

    for pf in per_field.values():
        pf["exact_pct"] = round(pf["exact"] / pf["n"], 3) if pf["n"] else None
        pf["near_pct"] = round(pf["near"] / pf["n"], 3) if pf["n"] else None

    total = sum(pf["n"] for pf in per_field.values())
    exact = sum(pf["exact"] for pf in per_field.values())
    near = sum(pf["near"] for pf in per_field.values())
    overall = {
        "total_fields": total,
        "exact": exact,
        "near": near,
        "exact_pct": round(exact / total, 3) if total else None,
        "near_pct": round(near / total, 3) if total else None,
    }
    return overall, per_field
