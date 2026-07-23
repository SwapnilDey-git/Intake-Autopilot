Type: grilling
Status: resolved
Blocked by: 02

## Question

Given ticket 02's accuracy score for `qwen3-vl:8b`: keep it as `MODEL_NAME` in the shippable `docker-compose.yml`, or revert to the empirically-validated `minicpm-v`? What's the threshold for "good enough," and does the answer differ for the Mac handoff package vs. this dev's own local container (already deliberately left on `minicpm-v`)?

**Context from ticket 01:** the "empirically-validated" 10/12 result for `minicpm-v` may not be as solid as assumed — two back-to-back extractions of the same test document during the end-to-end test (one via n8n, one direct-to-`ai-service`) both came back mostly `"Unknown"` across fields, and differed from each other run-to-run (non-deterministic). Worth treating `minicpm-v`'s baseline as needing a re-check with multiple runs, not just a single historical data point, before using it as the bar `qwen3-vl:8b` has to clear.

## Answer

**Reverted. `MODEL_NAME` is back to `minicpm-v` in `docker-compose.yml`** — user's explicit decision, given ticket 02's evidence (0/12, unusable output in all 3 runs, not just a lower score). No real threshold-setting was needed; this wasn't a borderline call.

Changes made:
- `docker-compose.yml`: `MODEL_NAME=qwen3-vl:8b` → `MODEL_NAME=minicpm-v`.
- `RUNNING.md`: rewrote the "Switched to qwen3-vl:8b — untested" section into "Tried qwen3-vl:8b, reverted — broken, not just slower", with the full failure writeup (empty/garbled output, thinking-template root cause, ~35min cold-load under the 7.6GB Docker Desktop memory ceiling) and a note that `minicpm-v`'s own baseline is now in question too (ticket 01).
- `CLAUDE.md`: updated the `ai-service` route description, the data-flow diagram, and the dedicated model-choice gotcha bullet to reflect the revert.
- Local dev container was already back on `minicpm-v` (via `docker-compose.override.yml`, restored at the end of ticket 02's testing) — no restart needed for this dev's own environment.

**Explicitly deferred, not done**: the Mac handoff package (`intake-autopilot-mac-handoff.tar.gz` in `~/Downloads`, built 2026-07-14) still has `qwen3-vl:8b` baked in from before this revert. User's call: "not needed right now, first let's work on something that works" — i.e. get the model situation solid before touching the handoff package again. Whoever sends that package next should rebuild it first, or it'll ship the broken model. Flagged in `CLAUDE.md` so this isn't forgotten.

**Not resolved by this ticket** (left for whoever picks it up): the `qwen3-vl:8b` thinking-template mismatch might be fixable (non-thinking tag variant, or a prompt/parser change in `ai-service`) — that's real implementation work, out of scope for this decision ticket. Also still open: `minicpm-v`'s own accuracy needs a proper multi-run re-check (ticket 01 found it non-deterministic), so "keep minicpm-v" here means "keep the working option," not "confirmed accurate."
