#!/usr/bin/env bash
# Run this ONCE, directly on the Pi over SSH.
# Installs Ollama + a small local Qwen model for offline voice-command intent
# parsing (NOT for OCR — that stays on OpenAI vision; this model only turns a
# transcribed voice command into a structured action).
set -euo pipefail

MODEL="${VOICE_INTENT_MODEL:-qwen2.5:3b}"

echo "=== Installing Ollama ==="
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
else
  echo "Ollama already installed: $(ollama --version)"
fi

echo "=== Enabling Ollama service ==="
sudo systemctl enable --now ollama

echo "=== Waiting for Ollama API to come up ==="
for i in $(seq 1 30); do
  curl -s -o /dev/null http://localhost:11434/api/tags && break
  sleep 1
done

echo "=== Pulling $MODEL (this downloads the model — may take a few minutes) ==="
ollama pull "$MODEL"

echo "=== Verifying: asking the model a simple question ==="
curl -s http://localhost:11434/api/generate -d "{
  \"model\": \"$MODEL\",
  \"prompt\": \"Reply with exactly one word: OK\",
  \"stream\": false
}" | python3 -c "import sys,json; print('Model replied:', json.load(sys.stdin)['response'].strip())"

echo ""
echo "=== Done ==="
echo "Ollama is running as a systemd service (auto-starts on boot) with $MODEL pulled."
echo "API available at http://localhost:11434 for the backend to call."
