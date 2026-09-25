# ACI – Offline Architecture

> "Teaching should never stop because the internet failed."

---

## What Is Installed on the Teacher's Device?

**Nothing needs to be installed.**

ACI is a **Progressive Web App (PWA)**. The teacher opens a URL in the browser on any device — phone, tablet, or laptop. On the first visit the browser automatically downloads and caches the entire app shell. From that point on the app loads and runs whether or not there is a network connection.

| Question | Answer |
|---|---|
| App store required? | No |
| APK / IPA download? | No |
| Native code installed? | No |
| Works on Android / iOS / PC? | Yes — any modern browser |
| Offline capable? | Yes — from the first page load |
| Data persists between sessions? | Yes — IndexedDB on the device |

### "Installing" as a Home Screen App (Optional)

On Android (Chrome) the browser offers an **"Add to Home Screen"** prompt automatically. Tapping it creates a full-screen shortcut on the home screen that looks and behaves exactly like a native app — no address bar, no browser chrome. This is purely cosmetic; the offline capabilities are identical whether or not this step is taken.

**iOS (Safari):** Teacher taps the share icon → "Add to Home Screen".

---

## Recommended Device Configuration

### Minimum Requirements

| Component | Minimum | Recommended |
|---|---|---|
| Browser | Chrome 90+ / Safari 16.4+ / Firefox 90+ | Chrome (latest) |
| RAM | 2 GB | 4 GB |
| Storage | 500 MB free | 2 GB free |
| Camera | 5 MP | 12 MP (rear) |
| OS | Android 10 / iOS 15 | Android 13+ / iOS 17+ |

### Recommended Device: Mid-Range Android Phone

A **₹10,000–₹15,000 Android phone** (Redmi Note, Realme C-series, Samsung Galaxy A-series) works well:
- Chrome is pre-installed and auto-updates
- 64 GB internal storage — enough for hundreds of sessions
- Rear camera 13–50 MP — more than enough for board capture
- Can be fixed to a tripod at the back of the classroom and left running

### Not Recommended

- **Very old phones (Android < 9):** IndexedDB storage limits are low; Service Worker may be unreliable
- **iOS < 15:** Service Worker + Background Sync support is incomplete
- **iOS in general:** Apple restricts PWA storage to ~50 MB per site and kills background tasks aggressively; the offline sync works but syncs only when the teacher opens the app

---

## Architecture: PWA vs Native App

This is the most important difference to understand. ACI does **not** follow the classic "Android app with SQLite" architecture. Instead:

```
┌────────────────────────────────────────────────────────────────┐
│                     Teacher's Phone / Tablet                    │
│                                                                │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │                  Chrome / Safari Browser                 │  │
│  │                                                         │  │
│  │  ┌───────────────────┐   ┌──────────────────────────┐  │  │
│  │  │   Service Worker  │   │     React App (PWA)       │  │  │
│  │  │  (background)     │   │                           │  │  │
│  │  │                   │   │  ┌────────────────────┐   │  │  │
│  │  │ • App shell cache │   │  │  useSyncQueue hook │   │  │  │
│  │  │ • Background Sync │   │  │  processSyncQueue  │   │  │  │
│  │  │   registration    │   │  │  processRecQueue   │   │  │  │
│  │  │                   │   │  │  processSessionQ   │   │  │  │
│  │  └────────┬──────────┘   │  └────────────────────┘   │  │  │
│  │           │              │                           │  │  │
│  │           │              │  ┌────────────────────┐   │  │  │
│  │           └──────────────┼─▶│   IndexedDB (IDB)  │   │  │  │
│  │                          │  │  aci_v1  (v4)       │   │  │  │
│  │                          │  │                    │   │  │  │
│  │                          │  │  pending_frames    │   │  │  │
│  │                          │  │  blobs             │   │  │  │
│  │                          │  │  recordingQueue    │   │  │  │
│  │                          │  │  sessionsQueue     │   │  │  │
│  │                          │  │  sessions_cache    │   │  │  │
│  │                          │  │  outputs_cache     │   │  │  │
│  │                          │  │  kv                │   │  │  │
│  │                          │  └────────────────────┘   │  │  │
│  │                          └──────────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                │
└────────────────────────────────────────────────┬───────────────┘
                             HTTPS (when online) │
                    ┌────────────────────────────▼────────────────┐
                    │              ACI Backend (Cloud)             │
                    │                                             │
                    │  POST /sessions          (create session)   │
                    │  POST /sessions/{id}/frames  (upload frame) │
                    │  POST /sessions/{id}/audio   (upload audio) │
                    │  GET  /sessions/{id}/outputs (AI results)   │
                    │  GET  /sync/events           (event poll)   │
                    └─────────────────────────────────────────────┘
```

### Key Difference from Native Android App

| Aspect | Native Android App | ACI PWA (current) |
|---|---|---|
| Local storage engine | SQLite file | IndexedDB (browser API) |
| Storage location | `/data/user/0/com.app/` | Browser sandbox |
| Image files | `.jpg` files on filesystem | Blobs in IDB `blobs` store |
| Background tasks | Android WorkManager | Service Worker Background Sync |
| Encryption at rest | SQLCipher (AES-256) | Browser sandbox (OS-level protection) |
| Camera access | Native camera API | `getUserMedia()` Web API |
| Installation | APK from Play Store | Browser URL (optional home screen shortcut) |
| Update mechanism | Play Store update | Auto-update via Service Worker on next load |
| Push notifications | FCM | Web Push (not yet implemented) |

---

## How Offline Works — Step by Step

ACI uses a **try-online-first** pattern. The online path is identical to before. Offline only activates on network failure. This guarantees zero behaviour change for teachers with reliable WiFi.

### Phase 1 — Frame Capture (Fully Offline)

```
Teacher taps "Capture" (no network needed)
        │
        ▼
Camera frame grabbed via getUserMedia()
        │
        ▼
Frame compressed in browser canvas
  < 200 KB → keep as-is
  200–500 KB → JPEG quality 0.85
  > 500 KB → quality 0.75
  result > 300 KB → resize to 1280×960
        │
        ▼
Frame blob + metadata saved to IDB
  Store: pending_frames  (metadata + status)
  Store: blobs           (raw Blob data)
        │
        ▼
UI immediately shows "1 pending" in sync bar
        │
        ▼
[When online] processSyncQueue() picks up the frame
  → POST /sessions/{id}/frames
  → On 200/409: mark as 'done', remove blob
  → On error: exponential backoff (30s→1m→2m→5m→15m)
```

**Status:** ✅ Complete and tested

---

### Phase 2 — Read Caching (Offline Browsing)

```
Teacher opens /sessions (online)
        │
        ▼
fetchSessionsCached() calls the API
        │
        ├── Success → store result in IDB sessions_cache (7-day TTL)
        │
        └── Network failure → read from IDB sessions_cache
              → shows amber banner: "Viewing cached sessions"

Teacher opens /sessions/{id}/notes (online)
        │
        ▼
fetchOutputsCached() calls the API
        │
        ├── Success → store AI output in IDB outputs_cache (7-day TTL)
        │
        └── Network failure → read from IDB outputs_cache
              → teacher can read quiz / notes / analysis without internet
```

**Event poller (every 10 s while tab is open):**
```
GET /sync/events?since={cursor}
        │
        ▼
If AI_OUTPUT_READY → SWR revalidates outputs page
If OCR_DONE       → SWR revalidates frame list
        │
        ▼
Cursor saved in IDB kv store ('syncCursor')
```

**Status:** ✅ Complete and tested

---

### Phase 3 — Offline Session Creation

```
Teacher taps "New Session" → fills form → taps "Start"
        │
        ▼
Client generates UUID: clientId = crypto.randomUUID()
        │
        ▼
Try: POST /sessions { client_session_id: clientId, ... }
  Header: Idempotency-Key: clientId
        │
        ├── Success (online) ─────────────────────────────────┐
        │   Server uses clientId as the session's real ID     │
        │   → router.push(/sessions/{clientId}/capture)       │
        │                                                      │
        └── Network failure (offline) ─────────────────────── ▼
              Save to IDB sessionsQueue:
              { id: clientId, payload, status: 'pending', ... }
              → router.push(/sessions/{clientId}/capture)
              Teacher starts capturing immediately!

[When back online] processSessionQueue() runs:
  POST /sessions { client_session_id: clientId }
  Header: Idempotency-Key: clientId
        │
        ├── 200/201 → session exists server-side → remove from IDB queue
        │             dispatch 'aci:session-synced' event
        │             Sessions list removes offline card
        │
        └── Error → exponential backoff (2s→5s→15s→1m→5m, max 5 retries)
```

**Idempotency on server:**
```python
# Server checks: does this UUID already exist?
existing = await db.get(Session, clientId)
if existing:
    return existing   # safe retry — same response

# Otherwise create with clientId as primary key
session = Session(id=clientId, ...)
```

**Status:** ✅ Complete and tested (online path); ✅ IDB queue and UI complete; ⚠️ offline path requires genuine network failure to trigger (not testable via JS mocking because Next.js uses an internal fetch wrapper)

---

### Phase 4 — Audio/Video Recording (Offline Queue)

```
Teacher starts audio recording during class
        │
        ▼
MediaRecorder API → chunks buffered in memory
        │
        ▼
On stop: Blob saved to IDB blobs store
         Entry added to IDB recordingQueue:
         { id, sessionId, blobId, type:'audio', ... }
        │
        ▼
[When online] processRecordingQueue():
  → POST /sessions/{id}/audio  (multipart)
  Header: Idempotency-Key: entry.id
  → On 200/409: delete blob + queue entry
  → dispatch 'aci:recording-synced' → capture page refreshes
```

**Status:** ✅ Complete and tested

---

### Phase 5 — AI Output Generation (Server-Side Only)

AI generation (OCR, notes, quiz, class analysis, lesson plan coverage) always runs on the server. It cannot run offline because it requires GPU compute and OpenAI API calls.

```
All frames uploaded + OCR done
        │
        ▼
POST /sessions/{id}/generate
        │
        ▼
Server: run AI pipeline (background task)
  → generate quiz, notes, missing concepts, experiments
  → store in ai_outputs table
        │
        ▼
Event emitted: type='AI_OUTPUT_READY'
        │
        ▼
Client event poller (10s) picks it up
  → SWR revalidates outputs page
  → Teacher sees results without manual refresh
```

**Status:** ✅ Complete. No offline support intended — AI always requires server.

---

## Offline Limits — How Much Can Be Stored and Uploaded?

### Device-Side Storage (IndexedDB)

The browser does not impose a fixed cap. Instead it uses a **percentage of available disk space**:

| Browser | IDB quota |
|---|---|
| Chrome / Android | Up to **60% of free disk space** (capped at 2 GB on some older Android versions) |
| Safari / iOS | Hard cap of **~50 MB per origin** — Apple enforces this regardless of free space |
| Firefox | Up to **50% of free disk space** |

**Practical meaning on a 64 GB Android phone with 20 GB free:**  
IndexedDB can use up to ~12 GB. You will never hit this limit in normal use — a full offline day of teaching uses roughly 20–80 MB (see calculation below).

**On iOS (Safari), the 50 MB cap is a real constraint.** At ~60 KB per compressed frame, that is roughly 800 frames maximum before the browser evicts data. A 45-minute class at 30-second intervals = 90 frames ≈ 5.4 MB — so iOS can hold about 9 full class sessions offline before the cap is reached.

---

### Per-Frame Limits (Server-Enforced)

These are hard limits the server rejects at upload time:

| Limit | Value | Where set |
|---|---|---|
| Max image size per frame | **10 MB** | `config.py → max_frame_size_mb` |
| Max frames per session | **200 frames** | `config.py → max_frames_per_session` |
| Max audio file size | **200 MB** | `audio.py → _MAX_SIZE_MB` |
| Max lesson plan PDF/image | **20 MB** | `lesson_plans.py → _MAX_SIZE_MB` |

After 200 frames the server returns `FRAME_LIMIT_REACHED` (400). The client treats 4xx as non-retryable and marks the item `skipped`.

---

### After Image Compression (What Actually Hits the Queue)

The sync engine compresses frames **before** storing them in IDB. Typical sizes after compression:

| Content type | Raw camera | After compression | IDB blob size |
|---|---|---|---|
| Chalkboard (dark bg) | 2–5 MB | **40–80 KB** | 40–80 KB |
| Whiteboard (bright bg) | 3–8 MB | **80–150 KB** | 80–150 KB |
| Smart board (screenshot) | 1–3 MB | **60–120 KB** | 60–120 KB |

Compression logic in `sync-engine.ts`:
- `< 200 KB` → upload as-is
- `200–500 KB` → JPEG quality 0.85
- `> 500 KB` → JPEG quality 0.75
- Result still `> 300 KB` → resize to 1280×960 then re-compress

---

### Real-World Storage Calculation

**Typical 45-minute class session:**

| Setting | Value |
|---|---|
| Capture interval | 30 seconds (default) |
| Frames per session | ~90 frames |
| Frame size (compressed) | ~70 KB average (chalkboard) |
| Session frame storage | ~6.3 MB |
| Audio recording (45 min) | ~43 MB (AAC at 128 kbps) |
| **Total per session** | **~50 MB** |

**How many offline sessions can you store?**

| Device | Free storage | Sessions (frames only) | Sessions (frames + audio) |
|---|---|---|---|
| Android 64 GB, 20 GB free | ~12 GB IDB quota | ~1,900 sessions | ~240 sessions |
| Android 32 GB, 10 GB free | ~6 GB IDB quota | ~950 sessions | ~120 sessions |
| iOS (Safari) | 50 MB hard cap | ~8 sessions | ~1 session |
| iOS (Chrome) | Same as Android | Same as Android | Same as Android |

> **Recommendation for iOS users:** use Chrome or Firefox on iOS, not Safari, to avoid the 50 MB cap.

---

### Retry and Queue Limits

Each item in the queue is retried up to **5 times** with exponential backoff. After 5 failures it is marked `skipped` and shown to the teacher for manual action.

| Queue | Max retries | Backoff schedule |
|---|---|---|
| Frames | 5 | 30s → 60s → 2min → 5min → 15min |
| Audio/Video | 5 | 2s → 4s → 8s → 30s → 60s |
| Offline sessions | 5 | 2s → 5s → 15s → 1min → 5min |

There is **no limit** on how many items can sit in the queue simultaneously. A teacher could theoretically accumulate 2 weeks of offline sessions and they would all upload when connectivity returns (subject to IDB storage and the 200-frames-per-session server cap).

---

### Summary Table

| What | Limit | Where enforced | Configurable? |
|---|---|---|---|
| Frame size | 10 MB (raw) / ~150 KB (compressed) | Server + client compression | Yes (`max_frame_size_mb` in config.py) |
| Frames per session | 200 | Server | Yes (`max_frames_per_session` in config.py) |
| Audio file size | 200 MB | Server | Hardcoded in `audio.py` |
| Lesson plan file | 20 MB | Server | Hardcoded in `lesson_plans.py` |
| Sessions in offline queue | No limit | Client IDB | — |
| IDB total storage (Android) | ~60% free disk | Browser | — |
| IDB total storage (iOS Safari) | 50 MB hard cap | Apple | — |
| Sync retries per item | 5 | Sync engine | Hardcoded in `sync-engine.ts` |
| Sessions listed per page | 20 (default), max 100 | Server API | Query param `limit` |

---

## What Is and Is Not Offline Today

| Capability | Status | Notes |
|---|---|---|
| **Frame capture** | ✅ Fully offline | Camera works, frames stored in IDB |
| **Frame upload queue** | ✅ Fully offline | Auto-syncs on reconnect, backoff retry |
| **Audio recording** | ✅ Fully offline | Recorded to IDB, synced when online |
| **Session creation** | ✅ Offline fallback | Client UUID used; server syncs later |
| **Sessions list browsing** | ✅ Offline (cached) | 7-day IDB cache, amber banner when stale |
| **AI output reading** | ✅ Offline (cached) | Notes / Quiz / Analysis readable offline |
| **Pending sessions in list** | ✅ Visible | Amber "Pending upload" group in sessions list |
| **Sync status bar** | ✅ Live | Frame count, recording count, session count |
| **AI generation** | ❌ Online only | Requires server compute — by design |
| **Lesson plan upload** | ❌ Online only | File upload needs server |
| **OCR results (live)** | ❌ Online only | Runs server-side after frame upload |
| **Push notification when AI done** | ❌ Not built | Poller (10s) used instead |
| **Conflict resolution (multi-device)** | ❌ Not built | Single device per teacher assumed |

---

## IDB Database Layout (What's on the Device)

Database name: **`aci_v1`** · Version: **4**

| Store | Key | Contents | TTL |
|---|---|---|---|
| `pending_frames` | frame UUID | Frame metadata + sync status + retry count | Until uploaded |
| `blobs` | blob UUID | Raw Blob data (image / audio) | Until uploaded |
| `recordingQueue` | entry UUID | Audio/video queue entry + metadata | Until uploaded |
| `sessionsQueue` | session UUID | Offline-created session payload + status | Until synced |
| `sessions_cache` | teacher UUID | Serialised session list response | 7 days |
| `outputs_cache` | session UUID | Serialised AI outputs response | 7 days |
| `kv` | string key | Event poller cursor, misc settings | Manual |

**Storage used:** Typically 5–50 MB depending on session length and number of cached items. Blobs are removed immediately after successful upload, so storage stays low during normal use.

---

## Sync Triggers (When Does Upload Fire?)

| Event | Action |
|---|---|
| Browser tab comes online (`online` event) | All three queues run immediately |
| App initialises (page load, online) | All three queues run immediately |
| Service Worker Background Sync | Runs when browser has connectivity (even if tab is closed — Android Chrome only) |
| Periodic timer (every 30 min) | Runs if there are pending frames |
| Manual "Retry" tap | User-triggered via sync status bar |

---

## Sync Queue Processors (Code)

Three queues run in parallel on every sync pass:

```
triggerSync()
    │
    ├── processSessionQueue()     ← sessions created offline
    │     POST /sessions
    │     Header: Idempotency-Key: clientId
    │     Backoff: 2s → 5s → 15s → 1m → 5m
    │
    ├── processSyncQueue()        ← board frames
    │     POST /sessions/{id}/frames  (multipart JPEG)
    │     Backoff: 30s → 1m → 2m → 5m → 15m
    │
    └── processRecordingQueue()   ← audio / video
          POST /sessions/{id}/audio
          Header: Idempotency-Key: entryId
          Backoff: 2s → 4s → 8s → 30s → 60s
```

Sessions queue runs first (logically) so that a session exists server-side before frames try to attach to it. If frames fail because the session doesn't exist yet, they will retry on the next sync pass once the session is confirmed.

---

## Network Conditions: What to Expect

| Connection | Frame upload | Audio upload | Session creation |
|---|---|---|---|
| 4G / WiFi | Instant (<1s per frame) | Fast | Instant |
| 3G (1–5 Mbps) | 2–5s per frame | 5–30s | 1–2s |
| 2G / EDGE (< 200 Kbps) | 30–60s per frame | Very slow | 3–10s |
| No network | Queued in IDB | Queued in IDB | Queued in IDB |

Image compression keeps frames at **< 200 KB** (typically 40–80 KB for chalkboard content), which makes 2G upload viable.

---

## Security Notes

- All data in IDB lives in the **browser sandbox** — no other app or website can read it
- Data is protected by the OS at rest (Android Full Disk Encryption on modern devices)
- No SQLCipher-level encryption is applied (unlike a native app approach) — acceptable for non-PII classroom content
- JWT tokens stored in memory (not localStorage) — cleared on browser close
- HTTPS enforced for all API calls — data is encrypted in transit

---

## Roadmap: What Would Phase 4 Look Like?

If ACI were to become a native Android app the architecture would shift:

| Layer | PWA (now) | Native Android (future) |
|---|---|---|
| Local DB | IndexedDB | Room (SQLite) |
| Background sync | Service Worker | WorkManager |
| Camera | `getUserMedia()` | CameraX |
| Storage | Browser sandbox | App private dir |
| Encryption | OS-level | SQLCipher |
| Distribution | URL | Play Store APK |
| Offline data limit | ~500 MB (browser quota) | Device storage limit |

The sync engine logic and backend APIs would remain identical — only the client storage layer would change.

---

*For API endpoint details, see [API_SPEC.md](./API_SPEC.md).*  
*For mobile integration details (Android native), see [MOBILE_SYNC_GUIDE.md](./MOBILE_SYNC_GUIDE.md).*  
*For local development runbook, see [LOCAL_RUNBOOK.md](./LOCAL_RUNBOOK.md).*
