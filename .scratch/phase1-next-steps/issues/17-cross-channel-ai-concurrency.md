Type: grilling
Status: open

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

(pending)
