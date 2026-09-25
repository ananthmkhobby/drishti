# Drishti — Deploying from Local to the Raspberry Pi

How to get code from your Mac onto the classroom Raspberry Pi, both for the first-ever setup of a
new Pi and for every deploy after that. This is **not** a git-based deploy — the Pi runs a synced
copy of your working tree, pushed directly over SSH. See [Why not git-based?](#why-not-git-based)
at the end if you're wondering.

All commands below run **from your Mac**, from the repo root, unless a step says otherwise.

---

## Prerequisites

| What | Notes |
|---|---|
| SSH access to the Pi | Password or key auth both work; you'll be prompted for the Pi's sudo password during setup either way. |
| The Pi's LAN IP | `hostname -I` on the Pi itself. Confirm this hasn't drifted (DHCP lease changes) before every deploy — see the caution in `deploy/sync-to-pi.sh`. |
| `rsync` on your Mac | Preinstalled on macOS. |
| A Raspberry Pi running Raspberry Pi OS (Debian-based) | The setup scripts use `apt-get`/`systemctl` — this is Pi/Debian-specific, not portable to other OSes as-is. |

Set these once per terminal session if your Pi's address/user/path differ from the scripts' defaults:

```bash
export PI_HOST=xpair@192.168.68.118   # user@ip — update to your Pi's actual address
export PI_DIR=/home/xpair/aci         # where the repo lives on the Pi
```

(These match the defaults already baked into `deploy/sync-to-pi.sh` — only export them if yours differ.)

---

## First-time setup on a brand-new Pi

Run these **in order**, once. Everything after step 2 is idempotent — safe to skip if you're not
using that feature, and safe to re-run later if you are.

### 1. Sync the code and run the main setup

```bash
bash deploy/sync-to-pi.sh
```

This single command:
- `rsync`s the repo to the Pi (excluding `.git`, `backend/.env`, `.venv`, `node_modules`, `.next`,
  local DB files, uploads, and backups — see [What does and doesn't sync](#what-does-and-doesnt-sync))
- SSHes in and runs `deploy/pi-setup.sh` remotely, which:
  - installs system packages (Python, Node 20, build tools, `tesseract-ocr`)
  - creates the backend virtualenv and installs dependencies
  - installs PostgreSQL and runs migrations (or creates a SQLite dev DB — whichever
    `backend/.env` on the **Pi** already specifies; see the note on `.env` below)
  - builds the frontend for production (`npm run build` — a Pi's disk is too slow for `next dev`'s
    on-demand compilation to feel usable)
  - generates a self-signed HTTPS cert bound to the Pi's current LAN IP (needed for camera/mic
    access from a phone browser, which requires a secure context)
  - installs and starts two systemd services: `aci-backend` and `aci-frontend`, both set to
    auto-restart on failure and auto-start on boot
  - schedules nightly Postgres backups via cron (if using Postgres — see `deploy/pg_backup.sh`)

Expected output ends with something like:
```
Backend health:  http://<pi-ip>:8000/health
Frontend (mobile): https://<pi-ip>:3000
```

### 2. `backend/.env` on the Pi (one-time, manual)

`backend/.env` is **deliberately excluded** from every sync — it's per-environment config (e.g.
`LOCAL_LLM_ENABLED=false` on the Pi vs `true` on a faster Mac), not code, and syncing it would
silently clobber Pi-specific settings on every future deploy.

The very first time, SSH in and create it by hand:

```bash
ssh "$PI_HOST"
cd "$PI_DIR/backend"
cp .env.example .env
nano .env   # set DATABASE_URL, OPENAI_API_KEY, JWT_SECRET_KEY, etc. for this Pi
```

Whenever a **new** setting is added to `.env.example` that the Pi also needs, add it here by hand —
it will not arrive automatically from your Mac.

### 3. Wake word — "Hey Drishti" (optional, needs the Pi's mic)

```bash
ssh -t "$PI_HOST" "chmod +x $PI_DIR/deploy/wake-word-setup.sh && bash $PI_DIR/deploy/wake-word-setup.sh"
```

Installs openWakeWord using the already-committed model at `backend/models/hey_xp.onnx` (synced by
step 1 like any other repo file — nothing to train or download here).

### 4. Local voice-command transcription — whisper.cpp (optional)

```bash
ssh -t "$PI_HOST" "chmod +x $PI_DIR/deploy/whisper-setup.sh && bash $PI_DIR/deploy/whisper-setup.sh"
```

Builds whisper.cpp from source and runs it as a systemd service (`whisper-server`, port 8080) for
fast, local transcription of short voice **commands** — not lecture recordings, which always stay
on OpenAI's cloud Whisper regardless of this setting.

### 5. Local intent parsing — Ollama + Qwen (optional)

```bash
ssh -t "$PI_HOST" "chmod +x $PI_DIR/deploy/voice-assistant-setup.sh && bash $PI_DIR/deploy/voice-assistant-setup.sh"
```

Installs Ollama as a systemd service and pulls `qwen2.5:3b` for offline voice-command intent
classification (turning a transcribed command into a structured action — not OCR, which always
stays on OpenAI vision).

### 6. Bluetooth handsfree mic/speaker (optional, interactive)

```bash
ssh -t "$PI_HOST" "chmod +x $PI_DIR/deploy/bluetooth-audio-setup.sh && bash $PI_DIR/deploy/bluetooth-audio-setup.sh"
```

Unlike the others, this one needs a human: put the handsfree unit in pairing mode first, then run
this and follow its prompts to pick it off the scan list and set it as the system default mic +
speaker. Read the script's own caveat about HSP/HFP mono mic quality before assuming a bad
transcript is a software bug.

### 7. Kiosk mode — desktop icon for the classroom TV (optional, do this last)

```bash
ssh -t "$PI_HOST" "chmod +x $PI_DIR/deploy/kiosk-setup.sh && bash $PI_DIR/deploy/kiosk-setup.sh"
```

Only run this after `aci-backend`/`aci-frontend` are already up (step 1). Adds a desktop icon that
launches the app fullscreen on the connected TV using the Pi's own USB camera. Safe to re-run.

---

## Every deploy after that

Once a Pi is fully set up, shipping a code change is one command:

```bash
bash deploy/sync-to-pi.sh
```

This re-syncs your working tree and re-runs `pi-setup.sh`, which is written to be idempotent — it
re-installs only what's changed, re-runs migrations (a no-op if none are pending), rebuilds the
frontend, and restarts both services so the new code actually takes effect. Prefer this single
script over manually SSHing in and running `npm run build`/`systemctl restart` yourself — a stale
`PI_HOST` silently failing at the very first line (see the script's own comment) has, in the past,
made a manual rebuild+restart rebuild the *old* code and look exactly like "the fix didn't work."

### Checking on it afterward

```bash
ssh "$PI_HOST" "sudo systemctl status aci-backend aci-frontend --no-pager"
ssh "$PI_HOST" "sudo journalctl -u aci-backend -f"      # live backend logs
ssh "$PI_HOST" "sudo journalctl -u aci-frontend -f"     # live frontend logs
```

### Database backups

If the Pi is running Postgres, step 1 already scheduled `deploy/pg_backup.sh` nightly at 03:00 via
cron — dumps go to `backend/db_backups/` on the Pi, compressed, pruned after 14 days. To take one
manually:

```bash
ssh "$PI_HOST" "bash $PI_DIR/deploy/pg_backup.sh"
```

---

## What does and doesn't sync

`deploy/sync-to-pi.sh`'s `rsync` excludes (never overwritten on the Pi, even if they exist locally):

| Excluded | Why |
|---|---|
| `.git` | Not a git-based deploy — see below. |
| `backend/.env` | Per-environment config, edited by hand on the Pi (see step 2 above). |
| `backend/.venv`, `frontend/node_modules`, `frontend/.next` | Rebuilt on the Pi by `pi-setup.sh`, not copied — a Mac-built `node_modules`/venv won't run on the Pi's architecture/OS anyway. |
| `backend/*.db`, `backend/uploads`, `backend/db_backups` | The Pi's own live data — never overwritten by whatever's sitting in your local dev DB/uploads folder. |
| `frontend/tsconfig.tsbuildinfo` | Build cache, regenerated. |

Everything else — application code, `backend/models/*.onnx`, `deploy/*.sh` themselves, docs — syncs
and **deletes on the Pi anything you've deleted locally** (`rsync --delete`), so an old file removed
from the repo won't linger on the Pi indefinitely.

---

## Why not git-based?

The Pi is deployed by syncing your actual working tree, not by cloning a GitHub remote and pulling.
This means whatever's on your Mac right now — including uncommitted changes — is exactly what ends
up on the Pi after `sync-to-pi.sh`. That's convenient for fast iteration during development, but
worth knowing: it also means the Pi's code and the GitHub repo's latest commit can silently diverge
if you deploy without committing first. Before a deploy you intend to keep, `git commit` (and
ideally `git push`) first so the Pi's state is traceable to a real commit, not just "whatever was on
disk that afternoon."

---

## Troubleshooting

### `sync-to-pi.sh` fails immediately on the first `ssh` line

`PI_HOST` is stale (the Pi's IP changed — DHCP lease renewal is the usual cause). Run
`hostname -I` on the Pi directly (connect a keyboard/monitor, or SSH in with the last-known-good
address) and re-export `PI_HOST` with the current one before re-running.

### Backend won't start after a deploy

```bash
ssh "$PI_HOST" "sudo journalctl -u aci-backend -n 50 --no-pager"
```
Common causes: a missing/invalid value in the Pi's `backend/.env` (it's never synced — see step 2),
or a migration that needs a manual look (`ssh` in, `cd backend && .venv/bin/alembic upgrade head`
to see the real error instead of systemd's terse failure).

### `database disk image is malformed` (SQLite)

Confirmed root cause historically: `aci-backend` still running (holding open connections) while
`create_db.py`/migrations touch the same SQLite file. `pi-setup.sh` already stops the service before
touching the database for exactly this reason — if you ever bypass the script and run DB commands
by hand, stop `aci-backend` first. This is also the reason Postgres, not SQLite, is the recommended
choice for the Pi's live deployment (see `pi-setup.sh`'s own comment on the concurrent-write history).

### Camera/mic don't work from a phone browser

Needs HTTPS — `pi-setup.sh` regenerates `cert.pem`/`key.pem` automatically whenever the Pi's IP
changes or the cert is close to its 365-day expiry. If a phone still refuses the cert, confirm
you're browsing to `https://<pi-ip>:3000` (not `http://`) and accept the self-signed cert warning.
