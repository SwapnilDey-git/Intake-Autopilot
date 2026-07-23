Type: task
Status: resolved

## Question

Did the recipient of `intake-autopilot-mac-handoff.tar.gz` (currently in `~\Downloads`, 7.6MB, built 2026-07-14) actually get the stack running on the M2 Max Mac following `SETUP-mac.md` + `RUNNING.md`? This is a manual/HITL task: send the package, walk the recipient through setup if needed, and collect what broke (if anything) — Docker Desktop for Mac quirks, native-Ollama Metal setup, `qwen3-vl:8b` pull time/size on their hardware, etc.

Not technically blocked by anything else on this map, but practically most useful to run after ticket 01 confirms the pipeline itself is sound (no point debugging Mac-specific issues under a broken pipeline).

## Progress notes

**2026-07-15**: Package has been sent to the recipient; not yet tested / no report back yet. Still genuinely pending — this is HITL, can't be resolved without the recipient's actual run.

**Known risk to flag when they do report back**: this package was built 2026-07-14 with `qwen3-vl:8b` baked in, and per ticket 03 that model was found to return empty/garbled non-JSON output in all 3 test runs (root-caused to Ollama's auto-selected "thinking" template/parser, not a real accuracy gap) — see [qwen3-vl:8b accuracy comparison](02-qwen3-vl-accuracy-comparison.md). The package was **deliberately not rebuilt** with the `minicpm-v` revert (user's explicit call: get the model situation solid first, worry about the Mac package after). So if/when the recipient tests extraction, they're near-certain to hit the same broken-output symptom on `qwen3-vl:8b` — that would be an *expected*, already-diagnosed finding, not a new bug. Worth telling the recipient not to bother debugging extraction quality on this build, or rebuilding the package with `minicpm-v` before they get to that step.

## Answer

**Resolved 2026-07-23 — superseded by reality: the stack demonstrably runs on the M2 Max Mac.**

The recipient-report framing (built around the OLD `intake-autopilot-mac-handoff.tar.gz`,
2026-07-14, `qwen3-vl:8b` baked in) is moot. Work has since been happening directly ON the
M2 Max Mac from the successor **2026-07-21 handoff** (this project dir), and on 2026-07-23 the
full stack was brought up and both features verified end-to-end live:

- `docker compose up -d --build --no-deps postgres n8n backend ai-service` (the native-Ollama
  form) → all four containers healthy; ai-service wired to native Ollama on Metal
  (`OLLAMA_HOST=host.docker.internal:11434`, `MODEL_NAME=qwen2.5vl:7b`, `AI_MAX_CONCURRENCY=2`).
- **Extraction validated live**: 3 concurrent `/extract` on `testdoc/Test Doc 2.pdf` → all
  HTTP 200, full 12-field results, model at 100% GPU on Metal (~6–8s/inference warm). The old
  ticket's `qwen3-vl:8b` broken-output risk does NOT apply — this handoff runs `qwen2.5vl:7b`,
  which reads cleanly.
- Backend review path, completeness check (ticket 21), and bounded concurrency (ticket 17)
  all confirmed working against the live stack.

**The one Mac-specific quirk found** (worth recording for any future fresh bring-up): right
after Docker Desktop starts cold, the first `docker compose build` failed twice with
`DeadlineExceeded: context deadline exceeded` fetching `python:3.11-slim` metadata — the
registry connection hadn't settled. Fix: an explicit `docker pull python:3.11-slim` once (it
succeeded immediately), after which the compose build ran clean. Not a package defect; a
Docker-Desktop-cold-start networking artifact. Also note the macOS `date +%N` / `timeout` /
zsh-no-word-split gotchas hit during scripting — host is zsh + BSD userland, not GNU.

No blocker remained; closing as confirmed-working rather than waiting on a separate recipient
run that the current working setup already answers.
