Type: grilling
Status: resolved

## Question

A live extraction result (form 79) came back with 10 of 12 fields "Unknown" and confidence=1.0 across the board — the user flagged this as unacceptable ("we can't have so much error and unknown percentage then what's the use of this") and asked to grill it to a real decision: is this fixable, what's the actual plan, and does it change what's safe to show in the planned client demo video.

## Answer

**Root-question decision**: the model needs to be reliably accurate on its own — human review is a lighter-touch double-check, not the real safety net. This raised the stakes on everything below; it's why the investigation kept going instead of stopping at "reviewers will catch it anyway."

**Investigation, evidence-first**: pulled every historical extraction of the one test document used throughout this project (forms 30, 31, 32, 71, 79 — 2026-07-11 through 2026-07-16) and compared field-by-field. Confirmed two distinct problems, not one:
1. Genuine non-determinism — same document, materially different answers every run (e.g. `home_address` returned 3 different values across 5 runs).
2. Confidence is not a real signal — every field reported `confidence: 1.0` regardless of whether the value was correct, missing, or "Unknown." Not a parsing bug (ticket 14 already fixed that plumbing) — the model itself is uncalibrated, the same "falsely high self-reported confidence" failure this project already rejected `llava` for.

Also confirmed the test document itself is not the problem — read it directly, every field is legible to a human at a glance. The failure is in the model/pipeline, not input difficulty.

**Two cheap fixes tested and kept** (both now permanent in `ai-service/main.py`):
- `dpi=150 → dpi=300` in the PyMuPDF rasterization (`page.get_pixmap`). Took "Unknown" fields from 10/12 down to 2/12 on a single run — low input resolution was starving the model of stroke detail it needed for handwriting.
- Added `options={"temperature": 0, "seed": 42}` to the previously-bare `client.chat(...)` call. Fully eliminated non-determinism — verified with 3 repeat runs producing byte-identical output, then reconfirmed through the full n8n → ai-service → Postgres pipeline (form 81), not just the isolated `ai-service` endpoint.

Combined result: 8 of 12 fields now always correct, 4 always wrong the same specific way every time (`e_card_number`, `name`, `honorare`, `svs_sva`) — a fixed, debuggable failure mode instead of a random one. `e_card_number` being one of the consistent failures is the highest-stakes gap, since it's the idempotency key this system uses to block duplicate approvals.

**One prompt fix tried and reverted**: added per-field label hints (the form prints "Income," not "honorare") plus an explicit "don't copy other fields' text" instruction, targeting the `honorare` field's bleed-through bug (it was returning the WKO/travel/SVS lines glommed into one string instead of just its own value). Result: `honorare` was unchanged, and `address_austria` — previously always correct — regressed to bleeding in the Romania address too. Reverted. Read as the model not reliably following negative/fine-grained instructions even when it can visually read the content correctly — closer to a real capability ceiling of this quantized 7.6B model than a fixable prompt bug.

**Confidence/reviewer-UX decision**: since confidence is proven dead (always 1.0, right or wrong), don't keep presenting it to reviewers as if it were a signal. Instead, hardcode reviewer guidance based on what this investigation empirically found: always double-check `e_card_number`, `name`, `honorare`, `svs_sva`. Dashboard implementation not yet built — spun off as ticket 15a.

**Known bugs surfaced but not yet fixed** (none are silent-failure risks since every field is human-reviewed regardless, but real):
- `honorare` field-boundary bleed-through (see above — one fix attempt reverted, not solved).
- Mojibake € encoding (`â‚¬` instead of `€`) seen intermittently on currency fields — not yet root-caused, didn't reappear in the temperature=0 runs but showed up in at least one DPI-300-only run.
- `e_card_number` and `name` are unreliable on this document with no fix found yet — the honest state is these need testing against a diverse document set (ticket 12's client eval set, still pending) to know if this is document-specific or general.

**Demo video implication**: nothing here should be shown as "the model gets it right" — the honest story for the demo is the pipeline + review workflow, not model accuracy on this particular document.

Unblocks/informs ticket 13 (accuracy eval harness) once ticket 12's eval set arrives — this investigation is a single-document proxy for what that harness should formalize across many documents.
