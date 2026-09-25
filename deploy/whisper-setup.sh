#!/usr/bin/env bash
# Run this ONCE, directly on the Pi over SSH.
# Builds whisper.cpp from source and runs whisper-server as a systemd
# service — local speech-to-text for the VOICE COMMAND path only (see the
# local_whisper_enabled comment in backend/app/config.py for why this is
# scoped to short command utterances, not the long-form lecture-recording
# pipeline, which stays on OpenAI's cloud Whisper for its richer confidence
# metadata).
#
# Validated on a Mac (Apple Silicon, GPU-accelerated): ~40-100ms per short
# command with a warm server, and the tiny.en model transcribed 6/6 test
# classroom-command phrases correctly. NOT yet validated on this Pi's
# actual CPU-only hardware — do that first thing after this script runs,
# with a real spoken command, before assuming the same latency holds.
#
# No apt package for whisper-cpp on Raspberry Pi OS — building from source
# is the documented path and is well-supported on ARM (NEON acceleration
# picked up automatically by the build).
set -euo pipefail

WHISPER_DIR="${WHISPER_DIR:-/home/$(whoami)/whisper.cpp}"
MODEL="${WHISPER_MODEL:-tiny.en}"
PORT="${WHISPER_PORT:-8080}"

echo "=== Installing build dependencies ==="
sudo apt-get update -y
sudo apt-get install -y build-essential cmake git libsdl2-dev
# ffmpeg: required for whisper-server's --convert flag below. Without it,
# the server only accepts raw WAV uploads — but the browser's MediaRecorder
# sends audio/webm;codecs=opus (its preferred format whenever supported),
# which whisper-server can't decode on its own. That mismatch was silently
# failing every single local-transcription attempt with a 400 Bad Request,
# falling back to slower cloud Whisper every time (confirmed 2026-09-17) —
# invisible in earlier testing here because the bundled JFK sample used to
# verify the server is itself a WAV file, which never exercised this path.
sudo apt-get install -y ffmpeg

if [ ! -d "$WHISPER_DIR" ]; then
  echo "=== Cloning whisper.cpp ==="
  git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git "$WHISPER_DIR"
else
  echo "=== whisper.cpp already cloned at $WHISPER_DIR — pulling latest ==="
  git -C "$WHISPER_DIR" pull
fi

echo "=== Downloading $MODEL model (small — tiny.en scored 6/6 on real command"
echo "    phrases in testing; only step up to base.en if accuracy is actually"
echo "    a problem, since bigger costs more per-request latency) ==="
bash "$WHISPER_DIR/models/download-ggml-model.sh" "$MODEL"

echo "=== Building whisper.cpp (this takes a few minutes on a Pi) ==="
cmake -B "$WHISPER_DIR/build" -S "$WHISPER_DIR" -DCMAKE_BUILD_TYPE=Release
cmake --build "$WHISPER_DIR/build" --config Release -j "$(nproc)" --target whisper-server

WHISPER_SERVER_BIN="$WHISPER_DIR/build/bin/whisper-server"
if [ ! -x "$WHISPER_SERVER_BIN" ]; then
  echo "ERROR: build finished but $WHISPER_SERVER_BIN not found — check the build output above."
  exit 1
fi

echo "=== systemd: whisper-server service ==="
sudo tee /etc/systemd/system/whisper-server.service > /dev/null <<EOF
[Unit]
Description=whisper.cpp local speech-to-text server (voice commands only)
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$WHISPER_DIR
ExecStart=$WHISPER_SERVER_BIN -m $WHISPER_DIR/models/ggml-$MODEL.bin --host 127.0.0.1 --port $PORT --convert
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now whisper-server
# restart (not just enable --now) so a re-run after a code/model change
# actually picks it up, same reasoning as pi-setup.sh's backend/frontend restart
sudo systemctl restart whisper-server

echo "=== Waiting for whisper-server to come up ==="
for i in $(seq 1 30); do
  curl -s -o /dev/null "http://127.0.0.1:$PORT/" && break
  sleep 1
done

echo "=== Verifying: transcribing the bundled JFK sample (WAV path) ==="
JFK_SAMPLE="$WHISPER_DIR/samples/jfk.wav"
if [ -f "$JFK_SAMPLE" ]; then
  curl -s -X POST "http://127.0.0.1:$PORT/inference" \
    -F "file=@$JFK_SAMPLE" -F "response_format=json"
  echo ""
else
  echo "(no bundled sample found to verify with — check manually with a real recording)"
fi

echo "=== Verifying: same sample re-encoded as webm/opus (the REAL browser path) ==="
# A WAV-only check above would have looked fine even with --convert missing
# entirely — that's exactly how this went unnoticed before. Converting the
# same sample to the actual format the browser sends is what proves the
# fix, not just that the server is up.
if [ -f "$JFK_SAMPLE" ]; then
  JFK_WEBM="/tmp/jfk_verify.webm"
  ffmpeg -y -loglevel error -i "$JFK_SAMPLE" -c:a libopus "$JFK_WEBM"
  curl -s -X POST "http://127.0.0.1:$PORT/inference" \
    -F "file=@$JFK_WEBM;type=audio/webm" -F "response_format=json"
  echo ""
  rm -f "$JFK_WEBM"
fi

echo ""
echo "=== Done ==="
echo "whisper-server is running as a systemd service (auto-starts on boot) on port $PORT."
echo "Set LOCAL_WHISPER_ENABLED=true and LOCAL_WHISPER_URL=http://localhost:$PORT in"
echo "backend/.env on the Pi (sync-to-pi.sh will bring these from your Mac's .env if"
echo "already set there — verify after syncing, same as the LOCAL_LLM_ENABLED override)."
echo ""
echo "IMPORTANT: this speed was only validated on a Mac with GPU acceleration."
echo "Test with a REAL spoken command on this Pi before trusting the sub-2s number —"
echo "CPU-only ARM performance for even the tiny model is not yet confirmed here."
