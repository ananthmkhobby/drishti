# ACI — Android Local Camera Test Guide

Test board image capture from an Android phone against a backend and frontend running on your laptop's LAN.

---

## Capture Flow Overview

The camera UI follows a deliberate **capture → preview → confirm** flow:

```
[Start Camera]
      │
      ▼
[Live Viewfinder]  ←─── Retake ────┐
      │                             │
  [Shutter]                         │
      │                             │
      ▼                             │
[Photo Preview]  ──── "Use Photo" ──┘──► saved to device (IndexedDB)
                                              │
                                         [compress]
                                              │
                                         [upload when online]
                                              │
                                    Status bar: Saving → Uploading → Uploaded ✓
```

**Offline behaviour:** If the phone has no network when the user taps "Use Photo", the frame
is compressed and saved to IndexedDB.  The viewfinder shows an amber "Offline — saved locally"
badge.  The sync engine re-tries automatically when the network returns.

---

## Quick Reference

| What | Command / Value |
|---|---|
| Find laptop IP | `ifconfig \| grep "inet " \| grep -v 127.0.0.1` |
| Start backend | `make dev` (already binds `0.0.0.0:8000`) |
| Start frontend | `npm run dev -- --hostname 0.0.0.0` |
| API URL for phone | `http://<laptop-ip>:8000/v1` |
| Frontend URL for phone | See [camera workaround section](#camera-access-workarounds) — plain HTTP will NOT work for camera |

> **Example laptop IP used in this guide:** `192.168.1.3`
> Substitute your own everywhere you see `192.168.1.3`.

---

## Step 1 — Find Your Laptop's LAN IP

```bash
# macOS / Linux
ifconfig | grep "inet " | grep -v 127.0.0.1
```

Or more explicitly on macOS:

```bash
networksetup -getinfo Wi-Fi
```

Expected output:
```
IP address: 192.168.1.3
Subnet mask: 255.255.255.0
Router: 192.168.1.1
```

Both the laptop and Android phone must be on the **same Wi-Fi network** as the router.

---

## Step 2 — Start the Backend

```bash
cd backend
source .venv/bin/activate
make dev
```

`make dev` runs:
```
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The `--host 0.0.0.0` flag makes the server reachable on all interfaces, including the LAN. No extra change needed.

Confirm from the phone: open Chrome and navigate to:
```
http://192.168.1.3:8000/health
```

Expected response:
```json
{"status": "ok"}
```

If this fails, see the [Firewall Checklist](#firewall-checklist) below.

---

## Step 3 — Configure the Frontend for LAN Access

### 3a. Set the API base URL

Edit `frontend/.env.local` (create it from the example if it does not exist):

```bash
cd frontend
cp .env.example .env.local    # if not already done
```

Then open `frontend/.env.local` and update:

```dotenv
# Replace 192.168.1.3 with your actual laptop IP
NEXT_PUBLIC_API_URL=http://192.168.1.3:8000/v1
```

> **Important:** Next.js bakes `NEXT_PUBLIC_*` vars at build time. Any time you change this file you must restart the dev server for the change to take effect.

### 3b. Start the frontend bound to all interfaces

```bash
cd frontend
npm run dev -- --hostname 0.0.0.0
```

Expected output:
```
▲ Next.js 16.x.x
   - Local:        http://localhost:3000
   - Network:      http://192.168.1.3:3000
   - Environments: .env.local
Ready in Xs
```

The **Network** line is the address you open on the phone.

---

## Step 4 — Verify CORS

CORS is already configured to allow all origins when `ENVIRONMENT=development` (the default in `.env`):

```python
# backend/app/main.py (already in the codebase)
if settings.is_development:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
```

Confirm your `.env` contains:
```dotenv
ENVIRONMENT=development
```

No further CORS changes are needed.

---

## Step 5 — Camera Access (Critical!)

> **⚠️ Plain HTTP will NOT work for camera capture.**

Chrome on Android only grants `navigator.mediaDevices.getUserMedia()` — the camera API used by `CameraCapture.tsx` — in a **secure context**:

- `https://` any origin, **or**
- `http://localhost` / `http://127.0.0.1` (loopback only)

Opening `http://192.168.1.3:3000` in Chrome Android loads the app but the camera button will silently fail or show a permission-denied error. The video stream will never start.

Choose **one** of the four workarounds below.

---

## Camera Access Workarounds

### Option A — ngrok HTTPS Tunnel (Recommended for first-time testing)

Easiest setup. Requires a free ngrok account.

**On the laptop:**

```bash
# Install (macOS)
brew install ngrok/ngrok/ngrok

# Authenticate once
ngrok config add-authtoken <your-token>   # from https://dashboard.ngrok.com

# Tunnel the frontend (run in a separate terminal)
ngrok http 3000
```

ngrok prints two lines like:
```
Forwarding   https://a1b2c3d4.ngrok-free.app -> http://localhost:3000
```

**On the phone:** Open `https://a1b2c3d4.ngrok-free.app` in Chrome.

The camera will work because the URL is HTTPS.

> **Note:** The API calls from the browser still go to `http://192.168.1.3:8000` which is HTTP. This triggers a **mixed content** block (HTTPS page calling HTTP endpoint). To avoid it, tunnel the backend too:
>
> ```bash
> # Second terminal
> ngrok http 8000
> ```
>
> Then update `frontend/.env.local`:
> ```dotenv
> NEXT_PUBLIC_API_URL=https://<backend-ngrok-id>.ngrok-free.app/v1
> ```
> And restart the frontend dev server.

---

### Option B — Chrome Flag (No Install Required)

Tells Chrome to treat a specific plain-HTTP LAN address as secure. No certificates, no tunnels.

1. On the Android device, open Chrome and navigate to:
   ```
   chrome://flags/#unsafely-treat-insecure-origin-as-secure
   ```

2. In the text field that appears, enter the **exact** frontend origin:
   ```
   http://192.168.1.3:3000
   ```

3. Set the flag dropdown to **Enabled**.

4. Tap **Relaunch** at the bottom.

5. Navigate to `http://192.168.1.3:3000`. Camera permissions will now be grantable.

> **Scope:** This flag applies only to Chrome on that specific Android device. It does not affect the laptop or other devices. Ideal for a single developer's test device.

> **Mixed content:** Because the page itself is still HTTP (not HTTPS) and the API is also HTTP, there is no mixed content block. Both are HTTP, so all API calls work without changes to `.env.local`.

---

### Option C — adb Reverse Port Forward (USB, No Wi-Fi Required)

Uses Android Debug Bridge to forward the phone's `localhost` ports to the laptop. The phone sees the app as if it were running on its own `localhost` — a secure context by definition.

**Requirements:** USB cable, ADB installed, USB Debugging enabled on the Android device.

**Enable USB Debugging on Android:**
1. Settings → About Phone → tap **Build Number** 7 times
2. Settings → Developer Options → **USB Debugging** → On
3. Connect USB cable and accept the RSA fingerprint prompt

**On the laptop:**

```bash
# Install ADB (macOS)
brew install android-platform-tools

# Verify device connected
adb devices
# Should show: <serial>   device

# Forward phone localhost:3000 → laptop localhost:3000
adb reverse tcp:3000 tcp:3000

# Forward phone localhost:8000 → laptop localhost:8000
adb reverse tcp:8000 tcp:8000
```

**On the phone:** Open `http://localhost:3000` in Chrome.

Because the phone is accessing `localhost`, Chrome treats it as a secure context. Camera works. API calls to `http://localhost:8000` also work (forwarded to the laptop backend).

> **`.env.local`:** Leave it as the default `http://localhost:8000/v1` — the forwarding makes `localhost` resolve correctly on the phone.

```dotenv
NEXT_PUBLIC_API_URL=http://localhost:8000/v1
```

---

### Option D — mkcert Local HTTPS Certificate

Creates a locally-trusted certificate. Requires `mkcert` installed and trusted on both the laptop and the Android device.

**On the laptop:**

```bash
# Install
brew install mkcert

# Install the local CA (laptop trusts it)
mkcert -install

# Generate cert for your LAN IP
mkcert 192.168.1.3 localhost 127.0.0.1

# Output:
#   192.168.1.3+2.pem  (certificate)
#   192.168.1.3+2-key.pem  (private key)
```

**Configure Next.js for HTTPS** — create `frontend/server.js`:

```javascript
const { createServer } = require('https');
const { parse } = require('url');
const next = require('next');
const fs = require('fs');

const app = next({ dev: true });
const handle = app.getRequestHandler();

const options = {
  key: fs.readFileSync('../192.168.1.3+2-key.pem'),
  cert: fs.readFileSync('../192.168.1.3+2.pem'),
};

app.prepare().then(() => {
  createServer(options, (req, res) => {
    handle(req, parse(req.url, true), res);
  }).listen(3000, '0.0.0.0', () => {
    console.log('> Ready on https://192.168.1.3:3000');
  });
});
```

Run it:

```bash
node server.js
```

**Trust the CA on Android:**

```bash
# Copy the CA cert to an accessible path
cp "$(mkcert -CAROOT)/rootCA.pem" /tmp/mkcert-ca.crt
```

Transfer `mkcert-ca.crt` to the phone (AirDrop, email, USB) then:
1. Settings → Security → Install from Storage
2. Select the `.crt` file → name it **mkcert** → install as **CA Certificate**

**On the phone:** Open `https://192.168.1.3:3000`. Camera works.

> This is the most production-like option but has the most setup steps.

---

## Firewall Checklist

### macOS Application Firewall

1. System Settings → Network → Firewall
2. If the firewall is **On**, click **Firewall Options...**
3. Ensure `node` and `python3` (or `uvicorn`) are in the allow list, **or** temporarily turn the firewall off during testing

### macOS Packet Filter (if applicable)

```bash
# Check if pf is blocking ports
sudo pfctl -sr | grep "3000\|8000"
# No output = no block
```

### Quick connectivity check

From the Android Chrome address bar:

```
http://192.168.1.3:8000/health
```

Expected: `{"status": "ok"}`

If you get a timeout or "site can't be reached":
- Both devices on the same Wi-Fi network?
- `make dev` running?
- Firewall blocking port 8000?

---

## Android Chrome Camera Permission Steps

After loading the app URL in Chrome:

1. Tap the camera button in the ACI capture UI
2. Chrome shows a permission prompt: **"Allow [site] to use your camera?"**
3. Tap **Allow**
4. The camera viewfinder appears showing the rear camera

**If the prompt never appears** (camera silently fails):
- The page is not a secure context — re-read [Step 5](#step-5--camera-access-critical)

**If you previously denied and need to re-grant:**
1. In Chrome, tap the **lock icon** (or ⓘ info icon) in the address bar
2. Tap **Permissions** → **Camera** → **Allow**
3. Reload the page

**If camera access is blocked system-wide:**
1. Android Settings → Apps → Chrome → Permissions → Camera → **Allow only while using the app**

---

## End-to-End Test Checklist

Run these steps from the Android phone to validate the full pipeline.

### Pre-flight

- [ ] Laptop and phone on same Wi-Fi network
- [ ] `make dev` running on laptop (port 8000)
- [ ] Frontend running with `--hostname 0.0.0.0` (port 3000)
- [ ] Camera workaround applied (Option A / B / C / D)
- [ ] `http://192.168.1.3:8000/health` returns `{"status": "ok"}` from phone browser

### On the phone — camera capture flow

- [ ] Navigate to app URL (ngrok URL, or `http://192.168.1.3:3000` with flag/forwarding)
- [ ] App loads without console errors
- [ ] Create a new session (Subject: Physics, Grade: 10, Board: CBSE)
- [ ] Open the **Capture** tab
- [ ] Tap **Start Camera** — viewfinder opens with rear camera
- [ ] Green "Online" pill visible in top-left of viewfinder
- [ ] Grant camera permission when prompted
- [ ] Point at a whiteboard, chalkboard, or printed page
- [ ] Tap the shutter button (large red circle) — white flash, then photo preview appears
- [ ] Preview shows the captured image with resolution chip (e.g. `1920×1080`)
- [ ] Tap **Retake** — returns to live viewfinder (test this at least once)
- [ ] Capture again, then tap **Use Photo** — returns to viewfinder
- [ ] Status bar below viewfinder shows: `Saving to device…` → `Uploading to server…` → `Uploaded · NNN KB`
- [ ] Sync status bar (above the camera card) shows queue count drop to 0

### On the phone — offline mode

- [ ] Disable Wi-Fi on the phone (or enable Airplane mode)
- [ ] Viewfinder top-left pill turns amber: **"Offline — saved locally"**
- [ ] Capture a photo and tap **Use Photo** — no error shown
- [ ] Sync bar shows `1 frame pending upload · Will upload on reconnect`
- [ ] Re-enable Wi-Fi — sync bar briefly shows `uploading…` then `All synced`

### Back on the laptop

- [ ] `GET /v1/sessions/{session_id}/frames` returns the uploaded frame with `status: "processed"` (allow 5–10 s for OCR)
- [ ] Frame has non-empty `ocr_text`
- [ ] `POST /v1/sessions/{session_id}/generate` triggers AI generation
- [ ] `GET /v1/sessions/{session_id}/outputs` returns notes, questions, and summary
- [ ] TiQer export `GET /v1/sessions/{session_id}/export/tiqer` returns valid JSON with `schema_version: "1.0"`

---

## Common Issues and Fixes

### Camera button does nothing / viewfinder is black

**Cause:** Page is not in a secure context; `getUserMedia` is silently blocked.

**Fix:** Apply one of the [Camera Access Workarounds](#camera-access-workarounds). The Chrome flag (Option B) is the fastest for a one-time test.

---

### Viewfinder shows "Camera access blocked" with step-by-step instructions

**Cause:** Camera permission was previously denied in Chrome or Android Settings.
This is the intentional in-app UI for permission errors — the component shows numbered steps inline.

**Fix (Chrome address bar):**
1. Tap the lock / ⓘ icon in Chrome's address bar
2. Permissions → Camera → Allow
3. Reload the page

**Fix (Android system):**
Settings → Apps → Chrome → Permissions → Camera → Allow only while using the app

---

### Tapped shutter but no preview appeared

**Cause:** `canvas.toBlob` returned `null` (rare on some Android WebViews).

**Symptom:** Flash fires, but the preview overlay never appears.

**Fix:** The component recovers automatically and returns to the live viewfinder. Retry the capture. If it happens consistently, switch to the File Upload tab.

---

### "Use Photo" tapped but status bar stays on "Saving to device…"

**Cause:** IndexedDB write is slow (first write, or private browsing mode).

**Note:** Private/Incognito mode in Chrome limits IndexedDB storage. If you see a persistent spinner, try a normal (non-incognito) tab.

---

### Status bar shows "Uploading to server…" indefinitely

**Cause:** The backend is unreachable from the phone at upload time.

**Check from the phone browser:**
```
http://192.168.1.3:8000/health
```

If that times out, the frame is already saved locally and will retry automatically.
See [Firewall Checklist](#firewall-checklist) and the backend connectivity issue below.

---

### Status bar shows "Upload failed — queued for retry"

**Cause:** Network was lost mid-upload. The frame stays in IndexedDB and will retry
with exponential back-off (30 s → 1 min → 2 min → 5 min → 15 min).

**Manual retry:** Tap **Sync now** in the sync status bar (shown when online + queue > 0).

---

### Offline badge not shown / viewfinder always says "Online"

**Cause:** `navigator.onLine` can return `true` even when the LAN backend is unreachable
(e.g., connected to a different network or firewall blocking the backend port).

**What this means:** The component correctly reflects the browser's network state.
If uploads fail despite "Online" being shown, the issue is backend reachability —
check the firewall and confirm the phone is on the same Wi-Fi network as the laptop.

---

### App loads but API calls fail (network error / 0 response)

**Cause:** `NEXT_PUBLIC_API_URL` still points to `localhost:8000` or `127.0.0.1:8000`, which the phone cannot reach over Wi-Fi.

**Fix:**
```dotenv
# frontend/.env.local
NEXT_PUBLIC_API_URL=http://192.168.1.3:8000/v1
```
Restart the frontend dev server after editing `.env.local`.

**Exception:** If you are using `adb reverse` (Option C), leave it as `http://localhost:8000/v1` — the port forwarding makes it work.

---

### Mixed content block (HTTPS page + HTTP API)

**Cause:** Frontend served over HTTPS (ngrok / mkcert) while `NEXT_PUBLIC_API_URL` uses `http://`.

**Symptom:** Chrome blocks the API requests. DevTools console shows:
```
Mixed Content: The page ... was loaded over HTTPS, but requested an insecure resource ...
```

**Fix:** Tunnel the backend too and point the API URL at the HTTPS tunnel:

```dotenv
# frontend/.env.local
NEXT_PUBLIC_API_URL=https://<backend-ngrok-id>.ngrok-free.app/v1
```

Or use Option C (`adb reverse`) which keeps everything on `http://localhost` with no mixed content.

---

### `http://192.168.1.3:8000/health` times out from phone

**Cause:** Firewall blocking port 8000, or devices not on the same subnet.

**Check:**
```bash
# On laptop — is uvicorn listening?
lsof -i :8000
# Should show uvicorn listening on *:8000

# Ping test (run from a second terminal on the laptop)
ping 192.168.1.3          # should reply immediately
```

**Fix:**
- macOS: System Settings → Network → Firewall → Firewall Options → allow `python3` / `node`
- Or temporarily disable the firewall for testing
- Confirm both devices show the same router IP (`networksetup -getinfo Wi-Fi`)

---

### Images upload but `ocr_text` is empty

**Cause:** PaddleOCR not installed; backend returns placeholder OCR result.

**Check:**
```bash
cd backend
.venv/bin/python -c "import paddleocr; print('ok')"
```

**Fix (optional):**
```bash
pip install -e ".[ocr]"
```

Without OCR installed the pipeline still runs end-to-end — frames are accepted, queued, and processed; `ocr_text` is just empty. AI generation still runs with empty OCR input and returns synthetic outputs. This is expected behaviour for a smoke test without the OCR extra installed.

---

### Frontend shows "Failed to fetch" after changing `.env.local`

**Cause:** Next.js still using cached value from the previous build.

**Fix:** Stop the dev server (`Ctrl-C`) and restart it:
```bash
npm run dev -- --hostname 0.0.0.0
```

---

### ngrok shows 429 / "Too Many Connections"

**Cause:** Free ngrok plan limits concurrent tunnels to 1.

**Fix:** Stop any existing ngrok sessions (check other terminals) and restart. Or open `http://localhost:4040` on the laptop — the ngrok inspector shows active tunnels.

---

### `adb devices` shows "unauthorized"

**Cause:** USB debugging RSA key not accepted on the phone.

**Fix:** On the phone, pull down the notification shade — there should be a prompt "Allow USB Debugging?". Tap **Allow**. Then re-run `adb devices`.

---

## Reference: Network Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│  Wi-Fi Router (192.168.1.1)                                      │
│                                                                  │
│  ┌─────────────────────┐          ┌──────────────────────────┐  │
│  │  Laptop (192.168.1.3)│         │  Android Phone            │  │
│  │                     │         │  (192.168.1.x)            │  │
│  │  uvicorn :8000 ──── │── LAN ──│──► http://:8000/health    │  │
│  │  next dev :3000 ─── │── LAN ──│──► http://:3000  (⚠ HTTP) │  │
│  │                     │         │                            │  │
│  │  (Option A) ngrok ──│── WAN ──│──► https://xxx.ngrok.app  │  │
│  │  (Option C) adb  ───│── USB ──│──► http://localhost:3000  │  │
│  └─────────────────────┘         └──────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

---

## Related Files

| File | Purpose |
|---|---|
| `frontend/src/components/capture/CameraCapture.tsx` | Camera capture component — viewfinder, preview, retake/confirm, upload status bar |
| `frontend/src/app/(dashboard)/sessions/[sessionId]/capture/page.tsx` | Capture page — compresses before IDB, drives `uploadStatus` prop, sync status bar |
| `frontend/src/lib/sync-engine.ts` | `compressImage()` + queue processor — re-compresses before upload |
| `frontend/src/lib/offline-store.ts` | IndexedDB wrapper — stores frames when offline |
| `frontend/src/hooks/useSyncQueue.ts` | React hook — `isOnline`, `isSyncing`, `triggerSync` |
| `frontend/.env.local` | `NEXT_PUBLIC_API_URL` — set this to the laptop LAN IP |
| `backend/app/main.py` | CORS config (`allow_origins=["*"]` when development) |
| `backend/app/config.py` | `is_development` property — controls CORS |
| `backend/Makefile` | `make dev` — already binds `0.0.0.0:8000` |
| `docs/LOCAL_RUNBOOK.md` | Full local dev setup (Track A SQLite / Track B Postgres) |
| `docs/LOCAL_SMOKE_TEST.md` | End-to-end smoke test from laptop curl |
| `docs/API_SPEC.md` | Full API reference |
| `docs/OFFLINE_SYNC.md` | Offline queue, retry logic, image compression targets |
