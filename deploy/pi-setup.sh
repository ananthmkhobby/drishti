#!/usr/bin/env bash
# Runs ON the Raspberry Pi. Idempotent — safe to re-run after a re-sync.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Stop the old service BEFORE touching the database. Confirmed live
# (2026-09-21): create_db.py switching dev.db into WAL mode while the
# still-running old aci-backend service held its own connections to the
# same file corrupted it — "database disk image is malformed" on the very
# next connection. SQLite journal-mode changes need exclusive access to the
# file; a "restart at the end" ordering doesn't give them that.
echo "=== Stopping aci-backend (if running) before touching the database ==="
sudo systemctl stop aci-backend 2>/dev/null || true

echo "=== System packages ==="
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip python3-dev build-essential curl openssl sqlite3
# Optional: enables the pytesseract fallback OCR path. OpenAI vision OCR is the
# primary engine and works without this — don't fail the whole deploy if the
# repo doesn't have it.
sudo apt-get install -y tesseract-ocr || echo "WARN: tesseract-ocr unavailable via apt — pytesseract fallback OCR will be disabled (OpenAI vision OCR still works)"

if ! command -v node >/dev/null 2>&1 || [ "$(node -v | sed 's/^v//;s/\..*//')" -lt 20 ]; then
  echo "=== Installing Node 20 LTS ==="
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi

echo "=== Backend: venv + deps ==="
cd "$ROOT/backend"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
# Base deps + OpenAI (vision OCR / AI generation) + pytesseract (fallback OCR).
# Deliberately skipping the "ocr" extra (paddleocr/paddlepaddle) and "audience"
# extra (deepface/tf-keras) — the app doesn't actually use either; audience
# analysis runs on the bundled YuNet/FER+ ONNX models via opencv's own DNN
# module, and OCR is OpenAI vision-first with pytesseract as the only fallback.
.venv/bin/pip install -e ".[ai]" pytesseract aiosqlite

echo "=== Backend: database ==="
# Reads whatever DATABASE_URL this Pi's own backend/.env actually configures
# (never synced from the Mac — see sync-to-pi.sh) via the app's own Settings
# loader, so this branches correctly regardless of which backend is in use.
DB_URL="$(.venv/bin/python -c 'from app.config import get_settings; print(get_settings().database_url)')"
echo "Configured database: $DB_URL"

if [[ "$DB_URL" == postgresql* || "$DB_URL" == postgres* ]]; then
  # Confirmed live 2026-09-21: SQLite corrupted three separate times on this
  # Pi under this app's normal background-task-heavy write pattern (chapter
  # detection, AI generation, guided-practice grading all commit from
  # BackgroundTasks, often overlapping a foreground request) — survived
  # removing WAL, confirming no concurrent process, a full reboot, and a
  # clean disk read/write/verify test, so it wasn't hardware either. Moved
  # this deployment to Postgres, which is built for exactly this kind of
  # concurrent-write workload. See database.py's own history comment.
  echo "=== Installing PostgreSQL (if needed) ==="
  if ! command -v psql >/dev/null 2>&1; then
    sudo apt-get install -y postgresql postgresql-contrib
  fi
  sudo systemctl enable postgresql
  sudo systemctl start postgresql

  # Idempotent — safe to re-run on every deploy without erroring on a role
  # or database that's already there.
  sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='aci'" | grep -q 1 \
    || sudo -u postgres psql -c "CREATE USER aci WITH PASSWORD 'aci';"
  sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='aci'" | grep -q 1 \
    || sudo -u postgres psql -c "CREATE DATABASE aci OWNER aci;"

  echo "=== Backend: Alembic migrations ==="
  DATABASE_URL="$DB_URL" .venv/bin/alembic upgrade head

  # sessions.teacher_id is a real foreign key under Postgres (unlike SQLite,
  # which never enforced it) — skip_auth mode needs an actual teachers row
  # for dev_teacher_id to exist before the very first session can be
  # created. Idempotent; a no-op once it's already there.
  echo "=== Backend: seeding dev teacher (skip_auth mode) ==="
  DATABASE_URL="$DB_URL" .venv/bin/python scripts/seed_dev_teacher.py

  # Automatic daily backups — the actual insurance against ANY future
  # failure mode, not just the SQLite corruption this migration fixed.
  # Idempotent: only appends the crontab line if it isn't already there.
  #
  # Both `|| true` guards are load-bearing under `set -euo pipefail`, not
  # defensive fluff: `crontab -l` exits 1 (not an error, just "no crontab
  # yet") on a user account that has never had one — confirmed live
  # 2026-09-22, this killed the deploy silently right at this line on a
  # freshly-provisioned Pi, three runs in a row, with zero error output
  # (crontab's own message was already routed to /dev/null, and `set -e`
  # exits without printing anything of its own). `grep -v` finding nothing
  # to filter (no prior pg_backup.sh line — the normal case on a first
  # deploy) is the exact same kind of "not wrong, just empty" 1-exit and
  # needs the same guard.
  echo "=== Backend: scheduling daily database backups ==="
  chmod +x "$ROOT/deploy/pg_backup.sh"
  CRON_LINE="0 3 * * * $ROOT/deploy/pg_backup.sh >> $ROOT/backend/db_backups/backup.log 2>&1"
  mkdir -p "$ROOT/backend/db_backups"
  ( { crontab -l 2>/dev/null || true; } | grep -vF "pg_backup.sh" || true; echo "$CRON_LINE" ) | crontab -
  echo "Backups run nightly at 03:00, kept 14 days, in $ROOT/backend/db_backups/"
else
  # SQLite path — kept for local/dev use (see the Mac's own backend/.env).
  # `alembic upgrade head` doesn't work here on purpose: migrations 0001/0002
  # use raw postgresql.JSONB and a postgresql_where partial index, neither of
  # which SQLite understands. scripts/create_db.py is the real, complete
  # path instead: create_all() (builds today's full schema straight from the
  # current models on a fresh DB) plus a _add_missing_sqlite_columns step
  # that ALTER TABLE ... ADD COLUMNs anything present in the models but
  # missing from an already-existing table.
  DATABASE_URL="sqlite+aiosqlite:///./dev.db" .venv/bin/python scripts/create_db.py
fi

echo "=== Frontend: npm deps ==="
cd "$ROOT/frontend"
npm ci

echo "=== Frontend: production build ==="
# `next dev` recompiles every route on its first visit (Turbopack JIT) — on a
# Pi's slower disk this stalls for a minute or more per route, looking like
# the page never loads. A one-time production build removes that entirely:
# everything is pre-compiled here during deploy, not on every classroom demo.
npm run build

echo "=== Frontend: HTTPS cert ==="
# Modern mobile browsers (Chrome, Safari) often refuse to offer any "proceed
# anyway" bypass for a self-signed cert that lacks a subjectAltName matching
# the address being visited — a bare CN is not enough. Regenerate whenever the
# Pi's LAN IP has changed so the SAN always matches what the phone connects to.
PI_IP="$(hostname -I | awk '{print $1}')"
NEED_NEW_CERT=0
if [ ! -f cert.pem ] || [ ! -f key.pem ]; then
  NEED_NEW_CERT=1
elif ! openssl x509 -in cert.pem -noout -ext subjectAltName 2>/dev/null | grep -q "IP Address:$PI_IP"; then
  NEED_NEW_CERT=1  # SAN doesn't match the Pi's current IP
elif openssl x509 -in cert.pem -noout -checkend $((366 * 24 * 3600)) >/dev/null 2>&1; then
  NEED_NEW_CERT=1  # still valid >366 days out — one of the old 10-year certs
fi
if [ "$NEED_NEW_CERT" = "1" ]; then
  echo "Generating cert for IP $PI_IP"
  # 365 days, not 10 years: Safari/WebKit (and increasingly Chrome) hard-reject
  # certs exceeding ~398-825 days validity, sometimes with no bypass option at all.
  openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 365 \
    -subj "/CN=$PI_IP" \
    -addext "subjectAltName=IP:$PI_IP,IP:127.0.0.1,DNS:localhost"
fi

echo "=== systemd: backend service ==="
BACKEND_AFTER="network.target"
BACKEND_WANTS=""
if [[ "$DB_URL" == postgresql* || "$DB_URL" == postgres* ]]; then
  BACKEND_AFTER="network.target postgresql.service"
  BACKEND_WANTS="Wants=postgresql.service"
fi
sudo tee /etc/systemd/system/aci-backend.service > /dev/null <<EOF
[Unit]
Description=ACI Backend (FastAPI/uvicorn)
After=$BACKEND_AFTER
$BACKEND_WANTS

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$ROOT/backend
ExecStart=$ROOT/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

echo "=== systemd: frontend service ==="
sudo tee /etc/systemd/system/aci-frontend.service > /dev/null <<EOF
[Unit]
Description=ACI Frontend (Next.js production build, custom HTTPS server for camera access)
After=network.target aci-backend.service
Requires=aci-backend.service

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$ROOT/frontend
Environment=NODE_ENV=production
ExecStart=$(command -v node) server.js
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable aci-backend aci-frontend
# restart (not just "enable --now") so a re-sync always picks up new code —
# enable --now is a no-op start if the service is already running
sudo systemctl restart aci-backend aci-frontend

echo ""
echo "=== Done ==="
sleep 2
sudo systemctl --no-pager status aci-backend | head -5
sudo systemctl --no-pager status aci-frontend | head -5

PI_IP="$(hostname -I | awk '{print $1}')"
echo ""
echo "Backend health:  http://$PI_IP:8000/health"
echo "Frontend (mobile): https://$PI_IP:3000"
