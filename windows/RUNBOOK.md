# Deployment runbook — client's Windows PC, over SSH/Tailscale

Two columns of work: **YOU (developer)** and **CLIENT**. Do them in this order.
The whole system ends up running on the client's PC; you only connect to set it up.

---

## PHASE 0 — YOU: prepare (before contacting the client)

**0.1 Generate an SSH key** (skip if you already have one):
```bash
ssh-keygen -t ed25519 -C "you@dev"
```
Your **public** key is `~/.ssh/id_ed25519.pub` (one line starting `ssh-ed25519 …`). Safe to share.

**0.2 Install Tailscale on your machine** — <https://tailscale.com/download> — sign in.

**0.2b (optional) RDP client for the GUI fallback** — on a **Mac**, install **Windows App**
(formerly "Microsoft Remote Desktop") from the Mac App Store; connect it to the client's
Tailscale IP. On Windows you'd use the built-in `mstsc`. Only needed if you must start Docker
Desktop / click GUI when the client isn't at the PC.

**0.3 Build the deployment bundle** (exclude Mac-only + PII + junk). From the folder that
*contains* the project:
```bash
zip -r intake.zip "intake-autopilot-mac-handoff-2026-07-21 2" \
  -x "*/.scratch/*" -x "*/demo/*" -x "*/node_modules/*" -x "*/.git/*" \
  -x "*/storage/ollama_models/*" -x "*/storage/Clients/*" \
  -x "*/docker-compose.override.yml"
```
> ⚠️ **Must exclude `docker-compose.override.yml`** — it's Mac-only (native Metal Ollama) and
> will break the Windows bring-up. Also excluded: `.scratch/` (real client PII), `demo/`,
> `node_modules/`, the model cache, and prior test outputs.

**0.4 Send the client** (see `CLIENT-SETUP.md` — that's the client's copy of Phase 1):
- your **public key** line (from 0.1),
- the file `windows\enable-ssh.ps1` (or tell them it's in the bundle you'll send),
- the plain-language `CLIENT-SETUP.md`.

---

## PHASE 1 — CLIENT: prepare their PC (they do this; you guide)

**1.1 Check specs:** Windows 10/11 64-bit, **16 GB RAM recommended**, ~20 GB free disk, internet.

**1.2 Install:**
- **Docker Desktop** → launch → wait for "running" → **Settings → General → tick "Start Docker
  Desktop when you log in."**
- **Node.js (LTS)** → default install.
- **Tailscale** → install → **sign in** (they'll appear as a device with a `100.x.y.z` address).

**1.3 Turn on SSH** — in an **Administrator** PowerShell, with your public key:
```powershell
powershell -ExecutionPolicy Bypass -File windows\enable-ssh.ps1 -DevPublicKey "ssh-ed25519 AAAA...you@dev"
```
It prints their **Tailscale IP** and **Windows username**.

**1.4 Client sends you:** the printed **Tailscale IP** + **username**, and confirms Docker is
set to start on login. They **stay logged in** during the session (locking the screen is fine).

---

## PHASE 2 — YOU: connect and stand up the system

**2.1 Join the tailnet** — accept the client's shared node (or have them accept yours). Confirm
you can see their device: `tailscale status`. (Recommended: a Tailscale **ACL** so only your
device can reach their `:22` — see the snippet at the bottom.)

**2.2 Copy the bundle to their PC** (over the Tailscale link):
```bash
scp intake.zip <username>@100.x.y.z:C:/Users/<username>/intake.zip
```

**2.3 SSH in** (you land in PowerShell):
```bash
ssh <username>@100.x.y.z
```

**2.4 Unzip to a clean, space-free path** (on their PC, in your SSH session):
```powershell
Expand-Archive C:\Users\<username>\intake.zip -DestinationPath C:\intake -Force
# the app is one level down (folder name has spaces); move it up for convenience:
Move-Item "C:\intake\intake-autopilot-mac-handoff-2026-07-21 2" C:\intake-autopilot
```

**2.5 Bring up the whole system** (one command; CPU model pull is slow on first run):
```powershell
cd C:\intake-autopilot
powershell -ExecutionPolicy Bypass -File windows\run-all.ps1
```
This does: `docker compose up --build` (Postgres, n8n, Ollama, ai-service, backend) → apply DB
schema → pull `minicpm-v` → import the Postgres credential + workflow → activate + restart n8n
(webhook registers) → `npm install` + start the dashboard → print all URLs.

**2.6 Confirm it's healthy** — the script prints a summary ending in
`Intake webhook (live): POST http://localhost:5678/webhook/upload-real`. If any service says
"not ready", check `docker ps` and `docker logs intake-<service>`.

---

## PHASE 3 — YOU: smoke-test one form

Still in the SSH session, push a **synthetic** test doc through the live pipeline:
```powershell
curl.exe -X POST --data-binary "@testdoc\Test Doc 2.pdf" -H "Content-Type: application/pdf" http://localhost:5678/webhook/upload-real
```
(Wait several minutes — CPU inference.) Then confirm it landed:
```powershell
docker exec intake-db psql -U admin -d intake -c "SELECT id,status,created_at FROM forms ORDER BY id DESC LIMIT 3;"
```
A new `status=extracted` row = the whole chain works (webhook → AI → database).

---

## PHASE 4 — CLIENT: daily use

On the client's PC (their own screen, no SSH), the accountant opens:
**http://localhost:3000** — the reviewer dashboard. They:
1. see each form the system read,
2. correct any field, enter their name,
3. **Approve** → a per-client Excel worksheet is written under `C:\intake-autopilot\storage\Clients\`.

That's the daily loop. Nothing leaves the PC.

---

## PHASE 5 — YOU: disconnect

Just close the SSH session (`exit`). The system keeps running on their PC. To stop it (e.g. for
maintenance): `powershell -File windows\stop-all.ps1` (data preserved). Restart: `run-all.ps1`.

**Revoke access anytime:** client removes your device in Tailscale, or runs `Stop-Service sshd`.

---

## OPTIONAL — enable the Email (Gmail) channel later
1. Client + you do the one-time Google/n8n OAuth in `..\demo\GMAIL-SETUP.md`. The OAuth consent
   needs a browser — tunnel n8n to your machine over SSH to do it from your side:
   ```bash
   ssh -L 5678:localhost:5678 <username>@100.x.y.z
   # then open http://localhost:5678 in YOUR browser
   ```
2. Re-run with the full workflow: `powershell -File windows\run-all.ps1 -Full`.
   WhatsApp stays off (Meta verification, on hold).

---

## Reference: Tailscale ACL (lock their SSH to just your device)
In the Tailscale admin console (Access Controls), restrict who can reach their `:22`:
```jsonc
"acls": [
  { "action": "accept", "src": ["<your-tailscale-user-or-device>"], "dst": ["<client-device>:22"] }
]
```

## Common gotchas
- **`docker` fails over SSH** → the client isn't logged in, or Docker Desktop didn't start.
  Have them log in (lock is fine) and confirm Docker shows "running"; it's set to start on login.
  **If they're unavailable, use the RDP fallback yourself:** `mstsc` → their Tailscale IP → log
  in with their Windows account → start Docker Desktop, then drop back to SSH. (`enable-ssh.ps1`
  turns RDP on, scoped to Tailscale only.)
- **First run is very slow** → CPU model download + build. Subsequent runs are fast (model cached
  in `storage\ollama_models`).
- **Don't copy `docker-compose.override.yml`** to Windows (Mac-only). The bundle step excludes it.
- **Use only `testdoc\` files** for testing. Real forms are client PII.
