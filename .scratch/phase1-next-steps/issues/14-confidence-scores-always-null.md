Type: task
Status: resolved

## Question

Surfaced during ticket 01's end-to-end test: `ai-service`'s `_confidence` handling has never been observed to produce a real number. Two independent extractions of the same test document (one via the n8n webhook path, one calling `ai-service` directly) both came back with `confidence: null` for all 12 fields in `backend`'s `/api/forms/pending` response — meaning `float(value)` in `ai-service/main.py`'s confidence loop is hitting its except-fallback every time, for every field, across both runs.

Root-cause it: is the model never including a `_confidence` object at all (prompt-adherence gap), including it in a shape `float()` can't coerce (nested dict/string-with-symbol/etc., same class of problem `coerce_field_value` already handles for the main fields), or something else? Fix or redesign accordingly — this also blocks ticket 13 (eval harness), which wants to check confidence calibration against actual correctness, and undermines the dashboard's "low-confidence field" banner (CLAUDE.md documents it as a feature, but it can never fire if confidence is always null).

## Answer

**Root-caused and fixed.** Added temporary debug logging to `ai-service`, ran a real extraction against the test PDF, and captured the model's actual raw JSON output. It showed the model never produces the separate top-level `_confidence: {field: number, ...}` object the old prompt asked for — instead it scatters `_confidence` keys *inside* each field's own value object (e.g. `"e_card_number": "210...", "_confidence": 1.0` as stray sibling keys at the top level, or a lone bare `_confidence: 1.0` float), the same per-field nesting `coerce_field_value` already recovers values from but the old confidence-extraction code never read from. It's a prompt-adherence gap (the 12-field + parallel 12-entry-confidence-object schema is too much structure for `minicpm-v` to hold together reliably), not a parsing bug.

Fix: restructured the prompt/schema to ask for `{"value": ..., "confidence": ...}` per field (matching what the model already naturally gravitated toward) instead of a separate top-level object, and rewrote `ai-service/main.py`'s field/confidence extraction loop to read confidence from that nested per-field location — each field's confidence is now scored independently, so one field's bad/missing confidence no longer nulls out the rest (the old design was effectively all-or-nothing since it depended on one shared top-level object parsing correctly).

**Verified live**: restarted `ai-service`, re-ran extraction against the test PDF. Result: `confidence: {"tax_year":1.0,"e_card_number":1.0,"name":null,"address_austria":1.0,"home_address":1.0,"honorare":null,"wko_contribution":null,"provision_travel":null,"svs_sva":1.0,"marital_status":0.8,"children":1.0,"is_signed":1.0}` — 8/12 fields now carry real, differentiated confidence scores. The 4 remaining nulls (`name`, `honorare`, `wko_contribution`, `provision_travel`) correspond to fields where the model's extracted *value* also came back unresolved on this run — a legitimate "no confidence for an unresolved field" case, not a recurrence of the bug.

This unblocks ticket 13 (eval harness confidence-calibration check) and means the dashboard's "low-confidence field" banner can now actually fire.
