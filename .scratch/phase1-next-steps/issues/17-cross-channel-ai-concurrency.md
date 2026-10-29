Type: grilling
Status: resolved


## Question

With webhook, Gmail, and WhatsApp now merged into one production n8n workflow (ticket 09), each of the three triggers can fire independently and all call the same `ai-service` `/extract` endpoint. Does that create real resource pressure on the host (CPU-only, ~7.6GB RAM ceiling per Docker Desktop WSL2, one `minicpm-v` inference taking 4-9 minutes), and if so, what's the right way to control it?

**Grounded facts (verified against the actual code, not assumed):**

- `ai-service/main.py`'s `/extract` route is declared `async def extract_document(...)`, but the actual model call (`call_model_with_retry` → `client.chat(...)`) uses `ollama.Client()`, the **synchronous** Ollama client, called directly with no `await` and no `run_in_executor`/`asyncio.to_thread`. FastAPI/Starlette only offloads *sync* `def` route handlers to a thread pool automatically — an `async def` handler that calls blocking code directly runs that blocking code straight on the single event-loop thread.
- `ai-service` is started via plain `uvicorn.run("main:app", host="0.0.0.0", port=8000)` — no `workers=` argument, so one process, one event loop.
- **Net effect: `ai-service` is already fully serialized today, accidentally.** While one `/extract` call is inside its 4-9 minute Ollama call, the event loop is completely blocked — a second incoming HTTP request (from any channel) cannot be processed at all until the first finishes. Two concurrent calls to Ollama itself, from this codebase, are not actually possible right now.
- This means the specific failure mode of "multiple simultaneous Ollama inferences blow the RAM ceiling" **cannot currently happen** through this codebase's own call pattern, regardless of how many n8n channels can trigger it.
- What *can* still happen: if webhook, Gmail, and WhatsApp all fire within the same few minutes, n8n starts 3 concurrent workflow executions, each holding open an HTTP call to `ai-service`. They queue up one-at-a-time behind whichever extraction is already running. Each `Call AI Service` node's own HTTP timeout is 20 minutes (`options.timeout: 1200000`, `retryOnFail: true, maxTries: 3, waitBetweenTries: 5000`). Three items queued back-to-back at ~4-9 min each stays under 20 min; a fourth or fifth arriving in the same window could push a caller's wait past its own 20-minute timeout, triggering a retry that just re-joins the same queue — a real (if currently unlikely, low-volume-pilot) retry-storm risk.
- The Gmail branch already has an internal `Loop Over Items (Gmail)` node, but that only serializes multiple attachments *within one Gmail poll's own item batch* (added to avoid one poll's several emails blowing `N8N_RUNNERS_TASK_TIMEOUT`, per `RUNNING.md`) — it does nothing to coordinate against the webhook or WhatsApp branches.
- `docker-compose.yml`'s `ollama` service sets only `OLLAMA_KEEP_ALIVE=30m`; no `OLLAMA_NUM_PARALLEL`, no container CPU/memory limits configured anywhere in the stack.

## Progress notes

(grilling in progress — see conversation)

## Answer

**Resolved 2026-07-23 (grilling + build, same session).**

**Re-grounding (the decisive move).** The ticket's "grounded facts" were verified against
the Windows CPU box (7.6GB, 4–9 min/inference, in-container Ollama). This Mac runs native
Ollama on Metal at ~8.5s/form. Re-running the retry-storm math on each box: the failure
mode (a caller's 20-min n8n timeout expiring while forms queue, → retry → rejoin queue)
needs ~4 forms queued on Windows (20min ÷ ~6min) but **~141 on the Mac** (20min ÷ 8.5s).
So the specific risk this ticket was opened for is largely a **CPU-box artifact** — a
non-issue at pilot volume on the Mac. Re-verified 2026-07-23 that ai-service was still
*accidentally* serialized (async `/extract` route calling the sync `client.chat` directly,
single uvicorn process, no `workers`) — which was also the only thing preventing two
inferences from contending for memory at once.

**Decision (user's call): "actually parallelize" — done RIGHT (bounded, not a free-for-all).**
Considered three paths: (A) document the serialization as load-bearing, no code change;
(B) A + pin `OLLAMA_NUM_PARALLEL` globally; (C) genuinely parallelize ai-service. User
chose C. Since naive parallelization would re-open the exact 32GB-ceiling question the
serialization was silently sidestepping, it was built **bounded**:

- `ai-service/main.py`: `/extract` now runs the blocking Ollama call via
  `asyncio.to_thread` (event loop no longer frozen during inference — health checks/other
  requests stay responsive), gated by `INFERENCE_SEMAPHORE = asyncio.Semaphore(AI_MAX_CONCURRENCY)`,
  `AI_MAX_CONCURRENCY` env default **2**. New `call_model_bounded()` wraps
  `call_model_with_retry()`. The shared `ollama.Client` wraps a thread-safe httpx.Client, so
  concurrent `.chat` from the thread pool is safe.
- **Cap rationale:** 2 concurrent is comfortable on 32GB with `qwen2.5vl:7b` (~6–8GB weights
  + per-request KV/image context); 3–4 pushes the ceiling on big multi-page vision inputs.
  `AI_MAX_CONCURRENCY=1` restores strict serialization.
- **The one global knob left to the operator:** true parallel throughput also needs native
  Ollama's `OLLAMA_NUM_PARALLEL >= AI_MAX_CONCURRENCY`. That's a **global host setting shared
  with every other Mac project's Ollama**, so it was deliberately NOT forced in code — it's
  documented as an opt-in (`launchctl setenv`). If left at default, extras queue *inside*
  Ollama (still correct, just serialized there). This is the honest cost of choice C that the
  grill surfaced: the app-side cap is project-scoped, but the throughput payoff isn't.
- `docker-compose.override.yml`: `AI_MAX_CONCURRENCY=2` surfaced for visibility/tuning.
- `RUNNING.md`: new "Cross-channel inference concurrency" section (both facts + the hardware-
  dependent risk calculus + the `OLLAMA_NUM_PARALLEL` opt-in).

**Verification:** `py_compile` clean. Confirmed ai-service targets Python 3.11-slim, where a
module-level `asyncio.Semaphore()` is safe (the loop-binding footgun was removed in 3.10; the
host's 3.9 tripped on it during testing but is not the runtime). Cap logic unit-tested: 10
simultaneous requests → peak concurrent inference = 2 (capped), all complete.

**Live-verified 2026-07-27 (stack up, real inference).** Brought the full stack up on the Mac
(`docker compose up -d --build --no-deps postgres n8n backend ai-service`, native Ollama on
Metal, `qwen2.5vl:7b`), added temporary `[CONCURRENCY-TEST]` logging to `call_model_bounded`
(active/peak counters + `sem_value` at arrival), fired **5 concurrent** `/extract` calls with a
real test PDF, then reverted the instrumentation (ai-service `git status` clean afterward). Results:
- **Cap holds at 2 on the live 3.11 container.** Logs: req#1 ENTER active=1, req#2 ENTER active=2
  (peak=2); req#3/#4/#5 all logged `awaiting semaphore (sem_value=0)` — correctly **queued, not
  dropped, not stampeding Ollama**. Every EXIT was immediately followed by exactly one queued
  request ENTERing; **peak never exceeded 2**. Confirms the module-level `asyncio.Semaphore`
  actually binds and gates under the real event loop (not just the unit test).
- **Event loop stays responsive during inference (the "pure win" half).** Polled `/docs` 10× while
  all 5 inferences were in flight: ~1–6 ms per poll (after the initial upload-read phase). The old
  accidentally-serialized version would have blocked `/docs` for the full inference — it didn't.
- **No memory blow-up.** All 5 returned HTTP 200; 32GB ceiling never stressed at cap=2.
- **The documented `OLLAMA_NUM_PARALLEL` caveat reproduced exactly.** With it unset, completion
  times staggered (~one inference's worth apart) even though 2 held the semaphore — i.e. extras
  queued *inside* native Ollama, matching the code comment's "still correct, just serialized there"
  note. App-side cap is proven; true parallel *throughput* still needs the global opt-in, as documented.

**Trade-off accepted:** more moving parts than the "document only" path, for throughput
headroom that pilot volume doesn't strictly need yet — but the event-loop-unblocking half is
a pure win regardless of throughput, and the bounded cap keeps the memory risk contained.
