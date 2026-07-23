Type: task
Status: resolved

## Question

How accurate is `qwen3-vl:8b` (the current shippable `MODEL_NAME`, switched from `minicpm-v` on 2026-07-13 to match the dev spec, never re-tested) against the same real handwritten test document used for the earlier `llava` vs. `minicpm-v` comparison in `RUNNING.md`?

Run the same field-by-field exact-match scoring methodology documented in `RUNNING.md`'s model-comparison section against `qwen3-vl:8b`, using the same test sample and known-correct ground truth (`llava` scored ~2/12, `minicpm-v` scored 10/12 exact + 2 off-by-one-character). Record the resulting per-field score.

**Run it more than once.** Ticket 01's end-to-end test incidentally found `minicpm-v` non-deterministic on this same document — two back-to-back extractions gave different, both mostly-`"Unknown"` results, which doesn't match the historical 10/12 figure at all. A single `qwen3-vl:8b` run won't be trustworthy either; do at least 2-3 runs and report the spread, not just one score.

## Answer

**`qwen3-vl:8b` scored 0/12 across 3 runs — every field came back `"Unknown"`, not because the model got the handwriting wrong, but because it never produced a parseable response at all.** This isn't a close call; recommend reverting `MODEL_NAME` to `minicpm-v` in the shippable `docker-compose.yml` (see ticket 03).

**What happened, run by run** (all 3 against `testdoc/Handwritten Intake Form v2_removed.pdf`, same ground truth as the `llava`/`minicpm-v` table in `RUNNING.md:153-166`):

- **Run 1 (cold)**: 35 min to load the model (RSS crept from 0→6.5GB in ~5-10 min increments — this Docker Desktop VM only has a 7.6GB total memory ceiling shared across *all 5* containers, and an 8B model eats nearly all of it) + 16m13s generating. Total ≈ 51 minutes for one extraction. Result: empty response (`Expecting value: line 1 column 1 (char 0)`).
- **Run 2 (warm, cache hit)**: 9.4s — reused the cached prompt/image encoding. Result: garbled multilingual gibberish (`Uploaded.obuf contctsettucch基数NCY::...`), not JSON, not even coherent text in one language.
- **Run 3 (warm, cache hit)**: 14.6s. Same failure mode, different gibberish (`ablynn statistically 讫...`).

**Root cause, found in `intake-ollama`'s logs**: Ollama auto-selected `renderer=qwen3-vl-thinking parser=qwen3-vl-thinking` for this model tag — a "thinking"-mode chat template that expects a specific structured output format. The model's actual raw generation didn't conform to it, so `common_chat_peg_parse: unparsed Content-only output` fired and Ollama's API returned an **empty or garbled `content` field** to `ai-service` regardless of what the model internally generated. This is a template/parser mismatch between Ollama's default handling of this tag and `ai-service`'s `format='json'` request — not necessarily proof the underlying model is incapable, but it means the tag as pulled (`qwen3-vl:8b`, no variant suffix) doesn't work with this codebase's calling convention out of the box.

**Also confirmed, independent of the above**: `MODEL_NAME=qwen3-vl:8b` cannot be pulled via `docker exec intake-ollama ollama pull` on this machine — same TLS-interception throttling documented in `RUNNING.md` for `llava` (crawled to ~2 KB/s, ETA "99h+"). Required the native-host-pull workaround, which itself needed extra troubleshooting beyond what `RUNNING.md` documents (the native tray supervisor `ollama app.exe` auto-starts with its own default `OLLAMA_MODELS`, ignoring a client-side env var override unless it's killed *before* pulling, not just after — `RUNNING.md`'s existing recipe undersells this ordering requirement). Not fixed in this pass since it didn't change the outcome, but worth tightening if this workflow is repeated.

**For whoever picks up ticket 03 or revisits this**: the actual bug (thinking-template mismatch) might be fixable — e.g. a non-thinking tag variant, or a prompt/parser adjustment in `ai-service` — but that's real implementation work, not another accuracy run, and each attempt costs ~35+ min to reload the model from cold. The model was fully removed from both the container's cache and the native host cache after this test (disk space reclaimed, `docker-compose.override.yml` reverted to `minicpm-v` and containers restarted) — re-testing that hypothesis means re-pulling from scratch.

**Also worth flagging for ticket 03**: the historical "`minicpm-v` scored 10/12" benchmark itself is now suspect — ticket 01 independently found `minicpm-v` non-deterministic on the same document (two runs, both mostly `"Unknown"`, differing from each other). Between that and this result, neither model currently has a *reliable*, reproduced-more-than-once accuracy number on record.
