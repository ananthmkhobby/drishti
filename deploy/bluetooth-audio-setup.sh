#!/usr/bin/env bash
# Run this ONCE, directly on the Pi over SSH, to pair a Bluetooth handsfree
# (headset/speakerphone) and make it the system's default mic + speaker so
# the browser (Chromium kiosk) picks it up automatically for the voice
# assistant — no per-device selection in the app itself.
#
# Unlike the other deploy/*.sh scripts, this one is NOT fully unattended —
# pairing needs the handsfree in pairing mode and a human picking it off a
# scan list. Run it, follow the prompts.
#
# IMPORTANT CAVEAT (read before assuming a bad transcript is a bug):
# Most Bluetooth "handsfree" mics use the HSP/HFP profile, which is mono,
# low sample rate (8-16kHz), and noticeably worse audio quality than a
# laptop's built-in mic. Every voice test so far in this project was done
# on a Mac's mic — expect Whisper transcription accuracy to measurably
# drop over Bluetooth HFP. If it's unusable, the fix is a wired USB mic,
# not more prompt tuning.
set -euo pipefail

echo "=== Detecting audio stack ==="
if command -v wpctl >/dev/null 2>&1 && systemctl --user is-active --quiet pipewire 2>/dev/null; then
  STACK="pipewire"
elif command -v pactl >/dev/null 2>&1; then
  STACK="pulseaudio"
else
  STACK="unknown"
fi
echo "Detected: $STACK"

echo ""
echo "=== Installing Bluetooth + audio packages ==="
sudo apt-get update -y
if [ "$STACK" = "pipewire" ] || [ ! -x "$(command -v pactl || true)" ]; then
  sudo apt-get install -y bluez bluez-tools pipewire pipewire-audio-client-libraries wireplumber libspa-0.2-bluetooth
else
  sudo apt-get install -y bluez bluez-tools pulseaudio pulseaudio-module-bluetooth
fi

echo "=== Enabling Bluetooth service ==="
sudo systemctl enable --now bluetooth

echo ""
echo "=== Restarting user audio services so the new Bluetooth plugin loads ==="
systemctl --user restart pipewire pipewire-pulse wireplumber 2>/dev/null || pulseaudio -k 2>/dev/null || true
sleep 2

echo ""
echo "=== Pairing ==="
echo "Put your handsfree device into pairing mode NOW (usually hold its power"
echo "button until it flashes/announces pairing), then press Enter."
read -r _

bluetoothctl <<'BTEOF'
power on
agent on
default-agent
scan on
BTEOF

echo ""
echo "Scanning for 15 seconds — note the MAC address (XX:XX:XX:XX:XX:XX) of your device below:"
timeout 15 bluetoothctl devices || true
bluetoothctl scan off >/dev/null 2>&1 || true

echo ""
read -rp "Paste the MAC address of your handsfree device: " MAC
if [ -z "$MAC" ]; then
  echo "No MAC entered — aborting. Re-run this script when you have it."
  exit 1
fi

echo "=== Pairing, trusting, and connecting to $MAC ==="
bluetoothctl pair "$MAC" || echo "WARN: pair reported an error — some devices still connect fine, continuing"
bluetoothctl trust "$MAC"
bluetoothctl connect "$MAC"
sleep 2

echo ""
echo "=== Setting $MAC as the default audio input + output ==="
if [ "$STACK" = "pipewire" ]; then
  BT_SINK=$(wpctl status | grep -i "$(echo "$MAC" | tr ':' '_')" | grep -i sink | grep -oE '[0-9]+\.' | head -1 | tr -d '.') || true
  BT_SOURCE=$(wpctl status | grep -i "$(echo "$MAC" | tr ':' '_')" | grep -i source | grep -oE '[0-9]+\.' | head -1 | tr -d '.') || true
  [ -n "${BT_SINK:-}" ] && wpctl set-default "$BT_SINK" && echo "Default output set (node $BT_SINK)"
  [ -n "${BT_SOURCE:-}" ] && wpctl set-default "$BT_SOURCE" && echo "Default input set (node $BT_SOURCE)"
  [ -z "${BT_SINK:-}${BT_SOURCE:-}" ] && echo "WARN: couldn't auto-detect the node — run 'wpctl status' manually and 'wpctl set-default <id>'"
else
  BT_ID=$(echo "$MAC" | tr ':' '_')
  pactl set-default-sink "bluez_sink.${BT_ID}.handsfree_head_unit" 2>/dev/null \
    || pactl set-default-sink "bluez_sink.${BT_ID}.a2dp_sink" 2>/dev/null \
    || echo "WARN: couldn't auto-set sink — run 'pactl list sinks short' and 'pactl set-default-sink <name>'"
  pactl set-default-source "bluez_source.${BT_ID}.handsfree_head_unit" 2>/dev/null \
    || echo "WARN: couldn't auto-set source — run 'pactl list sources short' and 'pactl set-default-source <name>'"
fi

echo ""
echo "=== Verification ==="
echo "Recording 3 seconds from the default mic — say something..."
arecord -d 3 -f cd /tmp/bt-mic-test.wav 2>&1 | tail -5 || echo "WARN: arecord failed — check 'arecord -l' for available devices"
echo "Playing it back through the default speaker:"
aplay /tmp/bt-mic-test.wav 2>&1 | tail -5 || echo "WARN: aplay failed — check 'aplay -l' for available devices"

echo ""
echo "=== Done ==="
echo "If playback sounded right, Chromium kiosk will use this device automatically"
echo "(browsers default to the OS's default mic/speaker unless told otherwise)."
echo "If it reconnects on reboot inconsistently, re-run 'bluetoothctl connect $MAC'"
echo "or add a systemd unit — ask if that's needed once this is confirmed working."
