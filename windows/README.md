# Running the full system on Windows

These scripts stand up the **real running system** (not a demo) on a Windows box with
Docker Desktop — the same operational steps used on the Mac, adapted for Windows.

> **Two sides of the setup:**
> - **Client** prepares their PC and grants remote access → give them
>   [`CLIENT-SETUP.md`](CLIENT-SETUP.md) (plain-language, non-technical).
> - **Developer** (this doc) connects over **SSH via Tailscale** and runs `run-all.ps1`.

## Remote access — developer side (SSH over Tailscale)
Access is **SSH reached privately over Tailscale** — no public ports, no AnyDesk. One-time:

1. **Generate a keypair** on your machine (if you don't have one):
   ```bash
   ssh-keygen -t ed25519 -C "you@dev"
   ```
   Send the client the **public** key (`~/.ssh/id_ed25519.pub`, the `ssh-ed25519 …` line — safe
   to share). Keep the private key private.
2. The client installs Docker Desktop + Node + **Tailscale**, then runs
   [`enable-ssh.ps1`](enable-ssh.ps1) with your public key (see `CLIENT-SETUP.md`). They send
   back their **Tailscale IP** (`100.x.y.z`) and **Windows username**.
3. **Install Tailscale** on your machine and join the same tailnet (or accept their shared
   node). Lock it down with a Tailscale **ACL** so only your device can reach their port 22.
4. **Connect** (you land in PowerShell):
   ```bash
   ssh <windows-username>@100.x.y.z
   ```
5. **Get the project onto their PC** (first time), then run the bring-up:
   ```powershell
   cd <path-to-project>
   powershell -ExecutionPolicy Bypass -File windows\run-all.ps1
   ```
   `run-all.ps1` is CLI-only and works fine over SSH. Disconnect when done.

**Caveats over SSH:**
- **Docker Desktop needs a live login session.** The client must be **logged in** (locking the
  screen is fine — don't sign out/shut down) and have Docker set to *start on login*, or
  `docker` calls will fail because the engine isn't running.
- The only GUI-required step is the **optional** Gmail OAuth consent — tunnel it with
  `ssh -L` port-forwarding, or do that one step in a brief screen-share.

## Deployment model (how this is run for the client)
- **The entire system runs on the client's Windows PC** — Postgres, n8n, Ollama, ai-service,
  backend, dashboard, and the `storage\` folder (uploads + Excel outputs) all live on that
  machine. The AI model runs **locally on the box**; no client data leaves it.
- **Developers do not keep a permanent connection.** They connect **over SSH (privately, via
  Tailscale)** **only when the system needs to be set up or reconfigured**, run
  `windows\run-all.ps1`, then disconnect. Day-to-day, the accountant uses the dashboard locally
  on the same PC. Setup steps: see "Remote access — developer side" above and `CLIENT-SETUP.md`.
- **Nothing is exposed to the internet.** All endpoints stay on `localhost` (see the URL list
  the script prints); SSH is reachable **only over the Tailscale private network**, not the
  public internet. There is **no need to open Postgres (5432) or Ollama (11434)** — keep them
  closed. (This is why a "remote model address / remote DB host" handover is **not** needed for
  this deployment — those were for a different, more exposed architecture.)
- **Model:** use a **validated** tag — this script uses `minicpm-v` (the compose default,
  10/12 fields on the reference form). **Do not use `qwen3-vl:8b`** — it returns garbled
  non-JSON with this app (Ollama picks a "thinking" template) and cold-loads very slowly.
  See `CLAUDE.md` / `RUNNING.md` for the model-comparison history.

## Security / data-protection note
This machine holds **real Austrian tax PII**. Keep the service ports closed to the network,
require a login on the remote-control tool (unattended-access password + 2FA), and back up
the Postgres volume and `storage\` regularly. The one part that *does* leave the box, if
enabled, is the **Email (Gmail) channel** — turning it on means client forms pass through
Google; enable it only if the client accepts that.

## Prerequisites (one-time)
- **Docker Desktop** running, using **Linux containers**.
- **Node.js + npm** (for the reviewer dashboard).
- **Internet on the first run only** — to build images and pull the vision model.

## Start everything
```powershell
powershell -ExecutionPolicy Bypass -File windows\run-all.ps1
```
This will, in order:
1. `docker compose up -d --build` — Postgres, n8n, **Ollama (CPU)**, ai-service, backend.
2. Apply `database\schema.sql` (idempotent).
3. Pull the `minicpm-v` vision model (first run only; can be slow).
4. Wait for ai-service / n8n / backend.
5. Import the Postgres credential + the **webhook-active** workflow into n8n, activate it,
   and restart n8n so the webhook registers.
6. `npm install` (first run) and start the dashboard on **http://localhost:3000**.
7. Print a status summary with all URLs and a sample `curl` command.

When it finishes, the **web-upload / webhook** channel is live. Push a form:
```powershell
curl.exe -X POST --data-binary "@testdoc\Test Doc 2.pdf" -H "Content-Type: application/pdf" http://localhost:5678/webhook/upload-real
```
Then review & approve it at http://localhost:3000. (CPU inference takes ~4–9 min/form.)

## Enable the Email (Gmail) channel
1. Do the one-time Google + n8n setup in [`..\demo\GMAIL-SETUP.md`](../demo/GMAIL-SETUP.md).
2. Re-run with `-Full`:
   ```powershell
   powershell -ExecutionPolicy Bypass -File windows\run-all.ps1 -Full
   ```
   With the Gmail credential present, this imports/activates the full 3-channel workflow
   (webhook + email). **WhatsApp stays off** until its Meta credentials are added.

## Stop everything
```powershell
powershell -ExecutionPolicy Bypass -File windows\stop-all.ps1
```
Stops the dashboard and all containers; **data is preserved**. A full reset that deletes
all data is `docker compose down -v`.

## Windows vs Mac (why this differs)
- **Inference**: Windows runs Ollama in a **container on CPU** (`minicpm-v`, ~4–9 min/form).
  The Mac uses **native Ollama on Metal** (`qwen2.5vl:7b`, seconds) via
  `docker-compose.override.yml`, brought up with `--no-deps` to skip the container Ollama.
- **Shell**: PowerShell here vs bash on the Mac. Everything else (containers, DB, n8n,
  activation via CLI + restart) is identical.

## Notes
- Workflow files (both carry an explicit `id` so n8n's CLI import accepts them):
  - `n8n\Intake_Flow_webhook.json` (id `intakewebhook001`) — default/fallback: the full
    workflow **minus the Gmail polling trigger** (which can't activate without OAuth).
  - `n8n\Intake_Flow_full.json` (id `intakefull000001`) — what `-Full` imports (webhook +
    Gmail). Derived from the shipped `n8n\Intake_Flow_Real.json` (the original 3-channel export).
- Use synthetic `testdoc\` PDFs for testing. Real client forms are PII.
