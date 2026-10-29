# Getting your PC ready — so we can set up the system remotely (over SSH)

Everything runs **on your own PC**. Your clients' data never leaves this machine — the AI
model runs locally on it. We connect **only over a private, encrypted link (Tailscale)** to a
command window — nothing on your PC is opened to the internet, and you can cut off our access
at any time.

Please do the four short steps below and send us the details in step 4.

---

## 1. Check the PC can run it
- **Windows 10 or 11** (64-bit)
- **16 GB RAM recommended** (8 GB minimum — it will just run slower)
- **~20 GB free disk space**
- **Internet connection** (needed during setup, and for reading forms)

## 2. Install three free programs (about 15 minutes)
1. **Docker Desktop** — <https://www.docker.com/products/docker-desktop/>
   Install and launch it; wait until it shows **"Docker Desktop is running"**.
   Then open its **Settings → General** and tick **"Start Docker Desktop when you log in."**
2. **Node.js (LTS)** — <https://nodejs.org/> — install with default settings.
3. **Tailscale** — <https://tailscale.com/download/windows> — install, open it, and
   **sign in** (a Google/Microsoft/email account is fine). This is the private link we use to
   reach your PC. Once signed in, your PC appears in Tailscale with an address like
   `100.x.y.z`. *(We may ask you to accept our device into your Tailscale network, or to sign
   in with an account we share — we'll tell you which.)*

## 3. Turn on SSH access (run one command we provide)
We'll send you a short text line called an **SSH public key** (safe to share) and a script
file. Then:
1. Click **Start**, type **PowerShell**, right-click it → **Run as administrator**.
2. Paste the command we send (it points at the script and includes our key), for example:
   ```powershell
   powershell -ExecutionPolicy Bypass -File windows\enable-ssh.ps1 -DevPublicKey "ssh-ed25519 AAAA... us@dev"
   ```
3. It prints a short summary at the end — **copy that** and send it to us (step 4).

*(This switches on Windows' built-in SSH — plus Remote Desktop as a backup way in — and
authorises our key. Both are locked to the private Tailscale link only: **nothing is opened to
the internet**, and your Windows password isn't changed. Keep that password strong, since
Remote Desktop uses it.)*

## 4. Send us these
- The **summary the script printed** (it contains your Tailscale address + the username), or
  simply: your **Tailscale address** (`100.x.y.z`) and the **Windows username** you use.
- Confirmation that Docker Desktop is set to **start on login** (step 2.1).
- A **time window** that suits you for the ~1-hour setup.

Please also **keep the PC logged in** during our session — you can **lock the screen**
(Windows key + L), just don't fully sign out or shut down, so Docker keeps running.

---

### What happens in the setup session
We connect over SSH, copy the software onto your PC, and run one command that sets everything
up (database, the local AI model, the automation, and the review dashboard). When it's done,
you open **one web page on your own PC** to review and approve forms. We then disconnect.

### About your data & security
- Your clients' tax information **stays on this PC** — nothing is uploaded to us or any cloud.
- We reach your PC **only through Tailscale** (a private encrypted link); no ports are opened
  to the public internet.
- Our access is **login-by-key only** and **only when you allow it**. Revoke it any time:
  remove our device in Tailscale, or turn off SSH (tell us and we'll send the one-line
  command, or run `Stop-Service sshd`).
- *(Optional, only if you ask for it later:)* to have forms arrive **by email** routes them
  through Gmail — we'll explain the trade-off before enabling it.

> Prefer not to run the script yourself? We can do steps 2–3 together on a quick screen-share
> the first time, then switch to SSH for everything after.
