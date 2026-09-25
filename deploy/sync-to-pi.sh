#!/usr/bin/env bash
# Run this FROM THE MAC. Syncs the repo to the Pi over SSH, then runs the
# remote setup script. Re-run any time after making local changes.
set -euo pipefail

# Note: the Pi's LAN IP has drifted before (DHCP lease change) — if this
# default stops working, run `hostname -I` on the Pi itself to get the
# current address and pass it via PI_HOST=xpair@<ip> bash deploy/sync-to-pi.sh
#
# This drifted silently once already (2026-09-17): with set -e, a stale
# default here means this script exits at the very first ssh line WITHOUT
# ever syncing a file — and a separate manual `npm run build && restart`
# afterward (using the current, correct IP) then rebuilds and restarts the
# OLD code, looking exactly like "the fix didn't work" for several rounds
# of debugging when the actual files were never updated at all. Update this
# default whenever the IP changes, and where possible prefer re-running
# THIS script (which fails loudly on a bad host) over separate manual
# build/restart commands that don't re-verify the sync succeeded.
PI_HOST="${PI_HOST:-xpair@192.168.68.118}"
PI_DIR="${PI_DIR:-/home/xpair/aci}"
LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== Syncing $LOCAL_DIR -> $PI_HOST:$PI_DIR ==="
ssh "$PI_HOST" "mkdir -p $PI_DIR"
# backend/.env is intentionally excluded below — it's per-environment config
# (e.g. LOCAL_LLM_ENABLED=false on the Pi vs true on the faster Mac), not
# code, and syncing it used to silently clobber Pi-specific overrides on
# every re-deploy. When a genuinely NEW setting is added on the Mac that the
# Pi also needs, add it to the Pi's .env by hand (ssh in and edit it) — it
# will no longer arrive automatically.
rsync -avz --delete \
  --exclude '.git' \
  --exclude 'backend/.env' \
  --exclude 'backend/.venv' \
  --exclude 'backend/__pycache__' \
  --exclude 'backend/**/__pycache__' \
  --exclude 'backend/*.db' \
  --exclude 'backend/uploads' \
  --exclude 'backend/db_backups' \
  --exclude 'frontend/node_modules' \
  --exclude 'frontend/.next' \
  --exclude 'frontend/tsconfig.tsbuildinfo' \
  "$LOCAL_DIR"/ "$PI_HOST:$PI_DIR"/

echo "=== Running remote setup (installs deps, starts services) ==="
echo "You'll be prompted for the Pi's sudo password during this step."
ssh -t "$PI_HOST" "chmod +x $PI_DIR/deploy/pi-setup.sh && bash $PI_DIR/deploy/pi-setup.sh"
