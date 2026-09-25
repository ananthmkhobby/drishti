#!/usr/bin/env bash
# Run this ONCE, directly on the Pi over SSH, after pi-setup.sh has the
# backend venv in place. Installs openWakeWord (on-device "Hey XP"
# detection — see wake_word_enabled in backend/app/config.py for why this
# replaced Picovoice Porcupine: free/open-source, no account, no review
# queue) and turns it on.
#
# The trained "Hey XP" model ships committed at backend/models/hey_xp.onnx
# (trained via openWakeWord's own notebook — see
# https://github.com/dscripka/openWakeWord, "Custom Model Training" in the
# README, if it ever needs retraining) — sync-to-pi.sh already brings it
# over like any other file in the repo. If that file is ever missing,
# detection falls back to a pretrained stock keyword instead — say "Hey
# Jarvis" to verify the pipeline (mic -> backend -> WebSocket -> frontend
# opens) works end to end in that case.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== System packages (PortAudio — sounddevice needs this to open the mic) ==="
sudo apt-get update -y
sudo apt-get install -y libportaudio2 portaudio19-dev

echo "=== Backend: wake-word extras ==="
cd "$ROOT/backend"
.venv/bin/pip install -e ".[wake-word]"
# openwakeword itself installed separately, --no-deps: its own packaging
# unconditionally requires tflite-runtime on Linux even though this service
# only uses its onnx backend, and tflite-runtime has no published wheel for
# this Pi's Python version — a known openwakeword packaging gap, not
# something a version pin fixes (confirmed 2026-09-11). The wake-word
# extra just installed above already covers its real runtime deps.
.venv/bin/pip install --no-deps "openwakeword>=0.6.0"

echo "=== Listing audio input devices (confirm the Pi's mic shows up) ==="
.venv/bin/python -m sounddevice || echo "WARN: couldn't list devices — check the mic is plugged in"

echo "=== Pre-downloading openWakeWord's pretrained models (one-time, needs"
echo "    internet now; cached afterward so the backend never needs it again) ==="
.venv/bin/python -c "import openwakeword; openwakeword.utils.download_models()"

echo "=== Enabling wake word in backend/.env ==="
ENV_FILE="$ROOT/backend/.env"
touch "$ENV_FILE"
if grep -q '^WAKE_WORD_ENABLED=' "$ENV_FILE"; then
  sed -i 's/^WAKE_WORD_ENABLED=.*/WAKE_WORD_ENABLED=true/' "$ENV_FILE"
else
  echo "WAKE_WORD_ENABLED=true" >> "$ENV_FILE"
fi
# backend/.env is deliberately excluded from sync-to-pi.sh's rsync (see the
# comment there) specifically so this Pi-only override survives future
# re-syncs from your Mac instead of being clobbered by its own .env.

echo "=== Restarting aci-backend to pick up the change ==="
sudo systemctl restart aci-backend

echo ""
echo "=== Done ==="
echo "Watch the logs for confirmation:"
echo "  journalctl -u aci-backend -f | grep -i 'wake word'"
echo "You should see 'listening (keyword=.../hey_xp.onnx...)' — say 'Hey XP'"
echo "to test. If it instead says keyword=hey_jarvis, the model file didn't"
echo "make it to this Pi — check backend/models/hey_xp.onnx exists here."
