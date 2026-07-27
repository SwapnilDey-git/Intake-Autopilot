# Machine Setup — Prerequisites Only (macOS)

This is the macOS counterpart to `SETUP.md` (which is Windows-only — WSL2, winget, PowerShell). Same scope: get a clean Mac to the point where `docker compose up` and `npm run dev` are possible at all. It does not clone/copy the project, pull any AI models, or import the n8n workflow — that's covered later, in `RUNNING.md`.

Target: macOS on Apple Silicon (M-series) or Intel — noted below wherever the two diverge. Run these in **Terminal** (or iTerm2); no admin/sudo needed except where Homebrew's installer asks for your password once.

---

## 1. Homebrew (package manager)

If not already installed:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Follow the "Next steps" it prints at the end (it usually asks you to add Homebrew to your shell `PATH` — copy/paste the two `echo`/`eval` lines it shows you). Verify:

```bash
brew --version
```

## 2. Docker Desktop

```bash
brew install --cask docker
```

Then **open Docker Desktop once manually from Applications** (or `open -a Docker`) and click through its first-run setup (license, permissions). This part is GUI-only, no CLI equivalent — same as on Windows. After that:

```bash
docker --version
docker compose version
docker info          # should return cleanly, not hang
```

If `docker info` hangs, quit Docker Desktop from the menu bar icon and relaunch — on Mac this is a much simpler fix than the Windows/WSL2 zombie-process issue documented in `RUNNING.md`'s Troubleshooting section (that section is Windows-specific; skip it here).

**Apple Silicon note:** the images this project uses (`postgres:16`, `n8nio/n8n`, `ollama/ollama`, plus the two custom-built `ai-service`/`backend` images) all publish/build `arm64` variants, so no Rosetta/emulation flag should be needed. If `docker compose up` ever complains about platform mismatch on an image, that's the thing to search for, but it isn't expected here.

## 3. Node.js (for the dashboard)

The dashboard is Next.js 16.2.10, which needs **Node.js >= 20.9.0**.

```bash
brew install node@20
```

Homebrew installs versioned Node formulae unlinked by default (to avoid clobbering other Node installs) — make sure it's on your `PATH`:

```bash
echo 'export PATH="/opt/homebrew/opt/node@20/bin:$PATH"' >> ~/.zshrc   # Apple Silicon
echo 'export PATH="/usr/local/opt/node@20/bin:$PATH"' >> ~/.zshrc     # Intel
source ~/.zshrc
```

Verify:

```bash
node --version    # should print v20.9.0 or higher
npm --version
```

## 4. Git

Needed to actually receive/clone this project (unlike the Windows dev machine, which had it transferred outside git). Ships with Xcode Command Line Tools:

```bash
xcode-select --install
```

(If that says already installed, you're set.) Verify: `git --version`.

## 5. Native Ollama (macOS) — recommended, for GPU acceleration

`docker-compose.yml` defines an `ollama` service that runs entirely inside a container, which works, but **leaves the M-series GPU/Neural Engine unused**: Docker Desktop for Mac runs containers inside a Linux VM, and there's no Metal passthrough into that VM (unlike NVIDIA-on-Linux GPU passthrough) — so containerized Ollama falls back to CPU-only inference. On an M2 Max that's still faster than the original Windows dev machine's mobile CPU, but it's leaving most of the hardware's actual capability on the table for a workload (vision-model inference) that benefits a lot from Metal.

Install Ollama natively instead and point the `ai-service` container at it over the Docker-to-host bridge:

```bash
brew install ollama
ollama serve &            # or just launch the Ollama.app once — it runs as a background/menu-bar service
ollama pull minicpm-v     # or whatever MODEL_NAME is set to in docker-compose.yml — uses Metal automatically
```

Verify it's serving and using the GPU:

```bash
curl http://localhost:11434/api/tags        # should list minicpm-v
ollama ps                                    # while a request is running, confirm it's not falling back to 100% CPU
```

Then, once the project is on the machine, add a Mac-local `docker-compose.override.yml` (same mechanism used on the Windows dev machine to pin a different model — Compose merges it automatically, and it's already `.gitignore`-style local-only, not part of the handoff) so `ai-service` talks to the host's native Ollama instead of the containerized one:

```yaml
services:
  ai-service:
    environment:
      - OLLAMA_HOST=http://host.docker.internal:11434
```

`host.docker.internal` is Docker Desktop's built-in DNS name for reaching the host machine from inside a container — no extra networking setup needed. The `ollama` service in `docker-compose.yml` can just be left alone; it'll sit idle and unused, which is harmless (skip pulling a model into it to avoid wasting the disk space, since nothing will call it).

This step is **also** the fix if the in-container pull ever fails outright the way it did on the original Windows dev machine (`Error: EOF`, root-caused to antivirus TLS interception on Docker's network path specifically) — but on a Mac, do it upfront for the GPU speedup rather than waiting to hit that failure first.

---

## Not needed yet (later phases)

- **Python 3.11** — only needed if running `ai-service`/`backend` directly on the host instead of via Docker.
- **`psql` client** (`brew install libpq` + add to `PATH`) — optional convenience for applying the DB schema from the host instead of via `docker exec`.

---

## What's next (not covered here)

Once the above is installed and verified, get the project files onto the machine (see the note at the top of `RUNNING.md` about `S:\intake-autopilot`-style paths — on Mac this'll just be wherever you put the folder, e.g. `~/intake-autopilot`) and follow `RUNNING.md` Scenario A onward. All of `RUNNING.md`'s actual run/debug commands are plain `docker compose`/`bash`, so they work unchanged in Terminal — only its Windows/WSL2-specific Troubleshooting subsections don't apply.
