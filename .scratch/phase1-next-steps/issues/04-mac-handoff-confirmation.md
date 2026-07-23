Type: task
Status: open

## Question

Did the recipient of `intake-autopilot-mac-handoff.tar.gz` (currently in `~\Downloads`, 7.6MB, built 2026-07-14) actually get the stack running on the M2 Max Mac following `SETUP-mac.md` + `RUNNING.md`? This is a manual/HITL task: send the package, walk the recipient through setup if needed, and collect what broke (if anything) — Docker Desktop for Mac quirks, native-Ollama Metal setup, `qwen3-vl:8b` pull time/size on their hardware, etc.

Not technically blocked by anything else on this map, but practically most useful to run after ticket 01 confirms the pipeline itself is sound (no point debugging Mac-specific issues under a broken pipeline).

## Progress notes

**2026-07-15**: Package has been sent to the recipient; not yet tested / no report back yet. Still genuinely pending — this is HITL, can't be resolved without the recipient's actual run.

**Known risk to flag when they do report back**: this package was built 2026-07-14 with `qwen3-vl:8b` baked in, and per ticket 03 that model was found to return empty/garbled non-JSON output in all 3 test runs (root-caused to Ollama's auto-selected "thinking" template/parser, not a real accuracy gap) — see [qwen3-vl:8b accuracy comparison](02-qwen3-vl-accuracy-comparison.md). The package was **deliberately not rebuilt** with the `minicpm-v` revert (user's explicit call: get the model situation solid first, worry about the Mac package after). So if/when the recipient tests extraction, they're near-certain to hit the same broken-output symptom on `qwen3-vl:8b` — that would be an *expected*, already-diagnosed finding, not a new bug. Worth telling the recipient not to bother debugging extraction quality on this build, or rebuilding the package with `minicpm-v` before they get to that step.

## Answer

(pending — waiting on recipient's actual test run)
