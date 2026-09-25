#!/usr/bin/env bash
# Run this ONCE, directly on the Pi over SSH, after the main deploy
# (sync-to-pi.sh / pi-setup.sh) already has aci-backend / aci-frontend running.
#
# Puts a desktop icon on the Pi's desktop that launches the app fullscreen
# on the connected TV, using the Pi's own USB camera (not a phone). The Pi
# still boots to the desktop automatically (autologin) — a teacher just
# double-clicks the icon to start class.
#
# Safe to re-run — it replaces its own files rather than duplicating them.
set -euo pipefail

USER_NAME="$(whoami)"
LOCAL_URL="http://127.0.0.1:3001"

echo "=== lightdm: autologin as $USER_NAME (boots to desktop, no password needed) ==="
sudo mkdir -p /etc/lightdm/lightdm.conf.d
sudo tee /etc/lightdm/lightdm.conf.d/50-autologin.conf > /dev/null <<EOF
[Seat:*]
autologin-user=$USER_NAME
autologin-user-timeout=0
EOF

echo "=== Removing any old auto-launch-on-boot config (superseded by the icon) ==="
AUTOSTART="$HOME/.config/labwc/autostart"
if [ -f "$AUTOSTART" ] && grep -q "# --- ACI kiosk start ---" "$AUTOSTART"; then
  sed -i '/# --- ACI kiosk start ---/,/# --- ACI kiosk end ---/d' "$AUTOSTART"
fi

echo "=== Removing system default that force-enables GPU rasterization ==="
# /etc/chromium.d/ is Debian's system-wide Chromium defaults, sourced by
# EVERY Chromium launch on this box, and it unconditionally exports
# --enable-gpu-rasterization. Passing --disable-gpu-rasterization on our own
# launch command (below) was meant to override that, but confirmed on real
# hardware (2026-09-24) it does NOT win: the running process still showed
# BOTH flags on its command line, and its gpu-process was still pegged at
# 76-105% CPU continuously (not just spiking) — Chromium's own internal
# flag-precedence almost certainly checks "enable" before "disable"
# regardless of argv order, so the system default kept winning no matter
# where our flag sat in the command line. Removing the default at its
# source, rather than continuing to fight it with a counter-flag, is the
# only way to be sure this actually takes effect. Idempotent — commenting
# an already-commented line is a no-op.
sudo sed -i '/--enable-gpu-rasterization/ s/^\([^#]\)/# DISABLED by ACI kiosk-setup.sh (2026-09-24, see deploy\/kiosk-setup.sh) -- \1/' /etc/chromium.d/* 2>/dev/null || true

echo "=== Desktop icon: ACI Classroom Capture ==="
DESKTOP_DIR="$HOME/Desktop"
mkdir -p "$DESKTOP_DIR"
LAUNCHER="$DESKTOP_DIR/ACI-Kiosk.desktop"

# Not --kiosk: removes ALL window chrome and disables Esc-to-exit entirely,
# so the only way out was Alt+F4 (quits the whole browser, not just
# minimizes) — reported as a real problem once teachers needed to step away
# mid-class.
# Not --start-fullscreen either: that relies on the window manager (labwc)
# honoring a true-fullscreen request, and on this setup it didn't — Chromium
# fell back to a small default window centered on screen instead of filling
# it (confirmed on real hardware 2026-09-11).
# --start-maximized instead: maximizing is a far more universally-supported
# window state than fullscreen across window managers, fills the screen the
# same way, and — the actual point — keeps the window titlebar with a real,
# visible minimize button. That's a more direct fix for "let the teacher
# step away" than relying on a keyboard shortcut in the first place.
# Deliberately WITHOUT --use-fake-ui-for-media-stream: it auto-grants
# camera/mic permission with no prompt, which sounds convenient for a
# kiosk, but Chrome treats it as one of a small set of flags whose
# "unsupported command-line flag" warning bar CANNOT be suppressed by
# --disable-infobars (confirmed on real hardware 2026-09-11 — the bar
# persisted despite that flag already being present) — trading a one-time
# permission prompt for a warning shown on every single launch is a bad
# trade. Without it, Chrome shows its normal camera/mic permission prompt
# the FIRST time the app requests it; that choice is then remembered
# per-origin for the life of this Chromium profile, so it's a one-time
# tap, not a recurring one, for as long as the Pi isn't reset/reimaged.
#
# --disable-gpu-rasterization: kept here too as defense-in-depth, now that
# the conflicting system default is actually removed above (see that step's
# comment for the full story — this flag alone was NOT sufficient while the
# default was still present). The Pi 4's GPU has known weak rasterization
# support in Chromium, so this flag is very likely costing more CPU than it
# saves here. Test with `top` again after this change (the gpu-process
# specifically, not just aggregate %Cpu(s)) before assuming it's the whole
# fix — if it's still pegged, the next thing to try is the fuller
# --disable-gpu (removes the separate GPU process entirely).
CHROMIUM_CMD="chromium --start-maximized $LOCAL_URL --noerrdialogs --disable-infobars --disable-session-crashed-bubble --disable-translate --no-first-run --autoplay-policy=no-user-gesture-required --check-for-update-interval=31536000 --disable-gpu-rasterization"

cat > "$LAUNCHER" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=ACI Classroom Capture
Comment=Launch the classroom board-capture app fullscreen
Exec=$CHROMIUM_CMD
Icon=chromium
Terminal=false
Categories=Education;
EOF
chmod +x "$LAUNCHER"
# Some file managers (GNOME/Nautilus-derived) require this to trust a launcher
# on first double-click instead of just offering to view its text contents.
gio set "$LAUNCHER" metadata::trusted true 2>/dev/null || true

echo ""
echo "=== Done ==="
echo "Reboot the Pi: sudo reboot"
echo "It should boot straight to the desktop (no login needed)."
echo "Double-click the 'ACI Classroom Capture' icon to launch the app"
echo "fullscreen at $LOCAL_URL, with camera permission pre-granted so it"
echo "picks up the Pi's own USB camera."
