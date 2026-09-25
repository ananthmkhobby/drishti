# ACI Mobile / PWA Sync Guide

**Audience:** Android app developers, PWA developers, QA engineers  
**Backend version:** Phase 3 (offline sync)  
**Last updated:** 2026-05-27

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture — Offline-First Model](#architecture--offline-first-model)
3. [Full Sync Flow (Sequence)](#full-sync-flow-sequence)
4. [Step-by-Step Integration](#step-by-step-integration)
   - [Step 1 — Device Registration](#step-1--device-registration)
   - [Step 2 — Local Queue Design](#step-2--local-queue-design)
   - [Step 3 — Bulk Session Sync](#step-3--bulk-session-sync)
   - [Step 4 — Frame Upload with Device Fingerprint](#step-4--frame-upload-with-device-fingerprint)
   - [Step 5 — Acknowledgement](#step-5--acknowledgement)
   - [Step 6 — Sync Status Polling](#step-6--sync-status-polling)
   - [Step 7 — Retry Failed Items](#step-7--retry-failed-items)
   - [Step 8 — Trigger AI Generation](#step-8--trigger-ai-generation)
5. [API Reference](#api-reference)
6. [Idempotency and Duplicate Handling](#idempotency-and-duplicate-handling)
7. [Error Handling Matrix](#error-handling-matrix)
8. [Image Compression Guidelines](#image-compression-guidelines)
9. [Retry Backoff Schedule](#retry-backoff-schedule)
10. [Sync Health Values](#sync-health-values)
11. [Edge Cases and FAQ](#edge-cases-and-faq)

---

## Overview

ACI is designed for classrooms with unreliable internet. The mobile app captures frames locally and syncs when connectivity is restored. The backend exposes a set of sync APIs that:

- Accept bulk session metadata in one call (minimises round-trips on reconnect)
- Track every sync queue item server-side (mirrors the mobile queue for visibility)
- Support idempotent re-submission (safe to retry the same request)
- Report sync health per device

---

## Architecture — Offline-First Model

```
┌─────────────────────────────────────────────┐
│                  Mobile App                 │
│                                             │
│  ┌───────────────┐   ┌────────────────────┐ │
│  │ Capture Queue │   │  SQLite local DB   │ │
│  │ (in-memory)   │──▶│  sessions + frames │ │
│  └───────────────┘   └─────────┬──────────┘ │
│                                │ reconnect  │
└────────────────────────────────┼────────────┘
                                 │ HTTPS
                    ┌────────────▼────────────┐
                    │      ACI Backend        │
                    │                         │
                    │  /devices               │
                    │  /sync/sessions  (bulk) │
                    │  /sessions/{id}/frames  │
                    │  /sync/ack              │
                    │  /sync/status/{fp}      │
                    │  /sync/queue            │
                    │  /sync/retry            │
                    │  /sessions/{id}/generate│
                    └─────────────────────────┘
```

**Key principle:** The mobile app is the source of truth while offline. On reconnect, it pushes everything to the backend. The backend then becomes the long-term store and runs OCR + AI in background tasks.

---

## Full Sync Flow (Sequence)

```
Mobile                              Backend
  │                                    │
  │── POST /devices ──────────────────▶│  1. Register device (once per install)
  │◀─ { device_id, registered } ───────│
  │                                    │
  │  [offline period — capture frames] │
  │                                    │
  │── POST /sync/sessions ────────────▶│  2. Bulk-sync session metadata
  │◀─ { accepted, rejected } ──────────│     Returns remote_session_id per session
  │                                    │
  │── POST /sessions/{id}/frames ─────▶│  3. Upload each frame
  │   (multipart: image + form fields) │     Include device_fingerprint form field
  │◀─ { frame_id, status:"queued" } ───│     Backend queues OCR in background
  │                                    │
  │── POST /sync/ack ──────────────────▶│  4. Acknowledge successful uploads
  │◀─ { acknowledged, created } ───────│
  │                                    │
  │── GET /sync/status/{fp} ──────────▶│  5. Poll sync health (optional)
  │◀─ { pending, done, health } ───────│
  │                                    │
  │── POST /sessions/{id}/generate ───▶│  6. Trigger AI pipeline (after all frames)
  │◀─ { job_id } ──────────────────────│
  │                                    │
```

---

## Step-by-Step Integration

### Step 1 — Device Registration

Register the device once on first launch (or after reinstall). Store the returned `device_id` locally — it is stable across sessions.

**Request**
```
POST /devices
Content-Type: application/json
Authorization: Bearer <teacher_jwt>
```
```json
{
  "device_fingerprint": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "teacher_id": "uuid-of-teacher",
  "platform": "android",
  "os_version": "14",
  "model_name": "Pixel 7",
  "app_version": "1.2.0",
  "push_token": "fcm-token-optional"
}
```

**Response 200**
```json
{
  "device_id": "server-uuid",
  "device_fingerprint": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "teacher_id": "uuid-of-teacher",
  "registered": true,
  "last_seen": null
}
```

- `registered: true` = new device created
- `registered: false` = existing device updated (idempotent re-register)
- Use the Android `Settings.Secure.ANDROID_ID` as `device_fingerprint`, or generate a random UUID stored in encrypted SharedPreferences on first launch
- iOS: use `UIDevice.identifierForVendor` (note: resets on reinstall — re-register is safe)

---

### Step 2 — Local Queue Design

Before going offline, the app should maintain a local SQLite queue:

```sql
CREATE TABLE sync_queue (
    id           TEXT PRIMARY KEY,       -- local UUID
    entity_type  TEXT NOT NULL,          -- 'session_meta' | 'frame'
    local_entity_id TEXT NOT NULL,       -- local session ID or local frame ID
    session_local_id TEXT,              -- parent session's local ID (for frames)
    status       TEXT DEFAULT 'pending', -- pending | uploading | done | failed
    retry_count  INTEGER DEFAULT 0,
    last_attempt TEXT,                   -- ISO 8601
    error_msg    TEXT,
    created_at   TEXT DEFAULT (datetime('now'))
);
```

**State machine:**
```
pending → uploading → done
                   ↘ failed (retry_count < 5)
                   ↘ skipped (retry_count ≥ 5)
```

Add entries to this queue as soon as each session/frame is captured — do not wait for connectivity.

---

### Step 3 — Bulk Session Sync

On reconnect, submit all pending session metadata in a single call (up to 50 sessions per batch).

**Request**
```
POST /sync/sessions
Content-Type: application/json
Authorization: Bearer <teacher_jwt>
```
```json
{
  "device_fingerprint": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "teacher_id": "uuid-of-teacher",
  "sessions": [
    {
      "local_session_id": "local-uuid-1",
      "subject": "Mathematics",
      "grade": "Grade 8",
      "board_type": "chalkboard",
      "capture_mode": "time_based",
      "capture_interval_sec": 30,
      "started_at": "2026-05-27T09:00:00Z",
      "completed_at": "2026-05-27T09:45:00Z",
      "frame_count": 12,
      "classroom_id": null
    }
  ]
}
```

**Response 200**
```json
{
  "device_id": "server-uuid",
  "accepted": [
    {
      "local_session_id": "local-uuid-1",
      "remote_session_id": "server-uuid-for-session",
      "outcome": "created",
      "reason": null
    }
  ],
  "rejected": [],
  "accepted_count": 1,
  "rejected_count": 0
}
```

**After receiving the response:**
1. For each accepted session, store `remote_session_id` in your local DB, mapped to `local_session_id`
2. Update the local queue entry for that session to `status = 'done'`
3. For `outcome = 'already_exists'` — this is **not an error**. Use the returned `remote_session_id` (same as the previously registered one)
4. For `outcome = 'rejected'` — log the `reason`, mark local entry as `failed`

**Batch sizes:** If you have > 50 sessions, split into multiple calls. Process sequentially to avoid race conditions.

---

### Step 4 — Frame Upload with Device Fingerprint

Upload each frame using multipart form data. Include the `device_fingerprint` field so the backend records this upload in the server-side sync queue.

**Request**
```
POST /sessions/{remote_session_id}/frames
Content-Type: multipart/form-data
Authorization: Bearer <teacher_jwt>
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `image` | file | Yes | JPEG or PNG, max 10 MB |
| `captured_at` | string | Yes | ISO 8601 timestamp (UTC preferred) |
| `sequence_no` | integer | Yes | 1-based frame order within the session |
| `local_frame_id` | string | Yes | Stable local UUID for this frame |
| `device_fingerprint` | string | No | Same fingerprint used at registration |

**Response 202**
```json
{
  "frame_id": "server-uuid-for-frame",
  "status": "queued",
  "message": "Frame queued for processing"
}
```

**Android Kotlin example:**
```kotlin
val body = MultipartBody.Builder()
    .setType(MultipartBody.FORM)
    .addFormDataPart("image", "frame.jpg",
        file.asRequestBody("image/jpeg".toMediaType()))
    .addFormDataPart("captured_at", capturedAt.toIso8601())
    .addFormDataPart("sequence_no", sequenceNo.toString())
    .addFormDataPart("local_frame_id", localFrameId)
    .addFormDataPart("device_fingerprint", deviceFingerprint)
    .build()

val request = Request.Builder()
    .url("$BASE_URL/sessions/$remoteSessionId/frames")
    .post(body)
    .header("Authorization", "Bearer $jwt")
    .build()
```

**Upload order:** Upload frames in `sequence_no` order to help the server rebuild the timeline correctly. Use a serial queue (not parallel) for frames within the same session.

**On HTTP 409 (DUPLICATE_FRAME):** The frame was already uploaded. Treat as success — record the previously returned `frame_id` from your local DB and continue.

---

### Step 5 — Acknowledgement

After a successful upload batch, acknowledge items to confirm they reached the server. This closes the loop on the server-side sync queue.

**Request**
```
POST /sync/ack
Content-Type: application/json
Authorization: Bearer <teacher_jwt>
```
```json
{
  "device_fingerprint": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "teacher_id": "uuid-of-teacher",
  "acknowledgements": [
    {
      "local_entity_id": "local-frame-uuid",
      "entity_type": "frame",
      "remote_entity_id": "server-frame-uuid",
      "session_id": "server-session-uuid"
    },
    {
      "local_entity_id": "local-session-uuid",
      "entity_type": "session_meta",
      "remote_entity_id": "server-session-uuid",
      "session_id": null
    }
  ]
}
```

**Response 200**
```json
{
  "acknowledged": 2,
  "created": 0,
  "not_found": 0
}
```

- `acknowledged` — items whose status was updated to `done`
- `created` — items that didn't exist yet (ack auto-creates them as done)
- `not_found` — items that couldn't be resolved (safe to ignore in MVP)

**When to ack:** After every successful HTTP 2xx from the frame upload endpoint. You can batch acks — send them at end of each session upload rather than after every individual frame.

---

### Step 6 — Sync Status Polling

Poll sync status to show the teacher upload progress and detect sync health degradation.

**Request**
```
GET /sync/status/{device_fingerprint}
Authorization: Bearer <teacher_jwt>
```

**Response 200**
```json
{
  "device_fingerprint": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "device_id": "server-uuid",
  "pending": 5,
  "uploading": 1,
  "done": 47,
  "failed": 0,
  "skipped": 0,
  "total": 53,
  "last_sync_at": "2026-05-27T09:12:34Z",
  "health": "healthy"
}
```

**Recommended polling interval:**
- During active sync: every 5 seconds
- Idle / background: every 60 seconds or on-demand

**UI mapping:**

| `health` | UI indicator | Action |
|----------|-------------|--------|
| `healthy` | Green checkmark | None |
| `degraded` | Yellow warning | Show "some uploads pending" |
| `failing` | Red alert | Show retry button |
| `unknown` | Grey — | Device not registered yet |

Progress percentage: `Math.round((done / total) * 100)` where `total > 0`.

---

### Step 7 — Retry Failed Items

When health is `failing` or the teacher taps a "Retry" button, reset failed items back to `pending`.

**Retry all failed items for this device:**
```
POST /sync/retry
Content-Type: application/json
Authorization: Bearer <teacher_jwt>
```
```json
{
  "device_fingerprint": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "item_ids": []
}
```
Sending an empty `item_ids` array resets **all** `failed` and `skipped` items for this device.

**Retry specific items:**
```json
{
  "device_fingerprint": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "item_ids": ["uuid-1", "uuid-2"]
}
```

**Response 200**
```json
{
  "reset_count": 3,
  "items": [
    { "id": "uuid-1", "status": "pending", "retry_count": 2 }
  ]
}
```

After receiving a successful retry response, re-run the upload flow from Step 3.

---

### Step 8 — Trigger AI Generation

Once all frames for a session are uploaded, trigger the AI pipeline to generate quiz questions, experiment suggestions, and missing concept analysis.

**Request**
```
POST /sessions/{remote_session_id}/generate
Content-Type: application/json
Authorization: Bearer <teacher_jwt>
```
```json
{}
```

**Response 202**
```json
{
  "job_id": "server-uuid",
  "status": "queued",
  "message": "AI generation queued"
}
```

**When to trigger:** Only after all frames for a session have received HTTP 202 from the upload endpoint and all OCR jobs are done. You can poll `GET /sessions/{id}` and check that `frame_count` matches your local count before triggering.

**Do not trigger multiple times** for the same session — the backend is idempotent but duplicate jobs waste resources. Use a local flag `ai_generation_requested = true` once triggered.

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/devices` | Register or update device |
| `POST` | `/sync/sessions` | Bulk-sync session metadata (up to 50) |
| `POST` | `/sessions/{id}/frames` | Upload a single frame |
| `POST` | `/sync/ack` | Acknowledge successful uploads |
| `GET` | `/sync/status/{fingerprint}` | Get sync health and counts |
| `GET` | `/sync/queue` | List queue items (debug / support) |
| `POST` | `/sync/retry` | Reset failed items to pending |
| `POST` | `/sessions/{id}/generate` | Trigger AI pipeline |
| `GET` | `/sessions/{id}` | Check session + frame_count |
| `GET` | `/frames/{id}/ocr` | Poll OCR result for a frame |

All endpoints require `Authorization: Bearer <jwt>` except during `SKIP_AUTH=true` dev mode.

---

## Idempotency and Duplicate Handling

The backend is designed to be **safe to retry**:

| Scenario | Backend behaviour | Mobile action |
|----------|-----------------|---------------|
| POST `/sync/sessions` with same `local_session_id` | Returns `outcome: "already_exists"` with same `remote_session_id` | Use returned ID, continue |
| POST `/sessions/{id}/frames` with same `local_frame_id` | Returns HTTP 409 `DUPLICATE_FRAME` | Treat as success, continue |
| POST `/sync/ack` for already-done item | Updates timestamp, no error | No action needed |
| POST `/devices` for existing fingerprint | Updates `last_seen`, returns `registered: false` | Store device_id, continue |

**Never abort a sync batch because of a 409.** Duplicates are expected when the app retries after a partial upload.

---

## Error Handling Matrix

| HTTP Status | Error Code | Mobile Action |
|-------------|-----------|--------------|
| 400 | `INVALID_IMAGE_TYPE` | Convert image to JPEG before retry |
| 400 | `IMAGE_TOO_LARGE` | Compress image further, retry |
| 400 | `FRAME_LIMIT_REACHED` | Stop uploading frames for this session |
| 400 | `SESSION_NOT_ACTIVE` | Check session status via GET /sessions/{id} |
| 401 | `UNAUTHORIZED` | Refresh JWT token, retry |
| 404 | `SESSION_NOT_FOUND` | Re-run bulk session sync first |
| 409 | `DUPLICATE_FRAME` | Treat as success, continue |
| 422 | (validation error) | Fix request payload, do not retry automatically |
| 429 | (rate limit) | Back off using retry schedule below |
| 500 | any server error | Retry with backoff; escalate after 5 failures |
| timeout / no response | — | Retry with backoff |

**4xx errors (except 401 and 429):** Do not auto-retry — these indicate a client-side data problem. Log the error and mark the item `failed` for user review.

**5xx errors and network timeouts:** Auto-retry using the backoff schedule.

---

## Image Compression Guidelines

Compress frames before upload to reduce bandwidth and avoid the 10 MB server limit:

| Metric | Target | Hard limit |
|--------|--------|-----------|
| File size | < 200 KB | < 10 MB |
| Longest dimension | ≤ 1920 px | — |
| Format | JPEG | PNG accepted |
| JPEG quality | 75–85 | — |

**Android (Kotlin):**
```kotlin
fun compressFrame(bitmap: Bitmap, maxSizeKB: Int = 200): ByteArray {
    val out = ByteArrayOutputStream()
    var quality = 85
    do {
        out.reset()
        bitmap.compress(Bitmap.CompressFormat.JPEG, quality, out)
        quality -= 5
    } while (out.size() / 1024 > maxSizeKB && quality > 30)
    return out.toByteArray()
}
```

**Chalkboard-specific:** Dark background images compress very well with JPEG. A 1080×720 px frame at quality 75 typically produces 40–80 KB.

**Do not over-compress:** Very low quality (< 30) degrades OCR accuracy. The 200 KB target is for typical classroom frames; whiteboard / bright images may legitimately be larger.

---

## Retry Backoff Schedule

Use exponential backoff with jitter for all retriable errors:

| Attempt | Base delay | With ±20% jitter |
|---------|-----------|-----------------|
| 1st retry | 30 s | 24 – 36 s |
| 2nd retry | 60 s | 48 – 72 s |
| 3rd retry | 2 min | 96 – 144 s |
| 4th retry | 5 min | 4 – 6 min |
| 5th retry | 15 min | 12 – 18 min |
| Give up | — | Mark `skipped`, notify teacher |

**Android Kotlin backoff helper:**
```kotlin
fun retryDelayMs(attempt: Int): Long {
    val baseMs = when (attempt) {
        1 -> 30_000L
        2 -> 60_000L
        3 -> 120_000L
        4 -> 300_000L
        else -> 900_000L
    }
    val jitter = (baseMs * 0.2 * (Math.random() * 2 - 1)).toLong()
    return baseMs + jitter
}
```

**Note:** When the app comes to the foreground after a background period, always attempt an immediate sync before starting the backoff timer — do not make the teacher wait 30 s for the first retry.

---

## Sync Health Values

The `health` field from `GET /sync/status/{fp}` uses this classification:

| Value | Condition | Meaning |
|-------|-----------|---------|
| `healthy` | failed + skipped = 0 | All uploads succeeded or in progress |
| `degraded` | 0 < failed/skipped < 20% of total | Some failures but mostly OK |
| `failing` | failed + skipped ≥ 20% of total | Significant failures — user action needed |
| `unknown` | total = 0 | No sync queue entries for this device yet |

**UI recommendations:**
- Show `healthy` / `degraded` as passive indicators (icon only)
- Show `failing` as an actionable alert with a "Retry Sync" button
- Show `unknown` only on the settings screen, not the main capture UI

---

## Edge Cases and FAQ

**Q: What if the teacher changes devices mid-session?**  
Register the new device with a different `device_fingerprint`. Submit `POST /sync/sessions` from the new device — sessions already synced from the old device will return `outcome: "already_exists"`. Continue uploading remaining frames from the new device.

**Q: What if the app is killed mid-upload?**  
On restart, scan the local queue for items with `status = 'uploading'` and treat them as `pending`. Re-upload frames — duplicates return 409, which is safe to ignore.

**Q: What if `captured_at` timestamps are wrong (clock skew)?**  
The backend accepts any valid ISO 8601 timestamp. `sequence_no` is the authoritative ordering field — the `captured_at` is stored for display only.

**Q: Can I upload frames before `POST /sync/sessions`?**  
No. You must obtain a `remote_session_id` from the bulk session sync before uploading frames, because frames reference a session by its server UUID.

**Q: How long does OCR take?**  
In development (placeholder OCR): < 1 second. With PaddleOCR installed: typically 1–5 seconds per frame. Poll `GET /frames/{id}/ocr` — it returns 404 with `OCR_NOT_READY` while pending and 200 once done.

**Q: When is it safe to delete local frame files?**  
After receiving HTTP 202 from frame upload AND after `POST /sync/ack` succeeds. Do not delete based on OCR status alone — the backend may need to re-run OCR in future.

**Q: What is the maximum frames per session?**  
Default: 500 frames per session (configurable via `MAX_FRAMES_PER_SESSION` env var). The server returns `FRAME_LIMIT_REACHED` (400) if exceeded.

**Q: Should I sync frames for sessions that failed bulk sync?**  
No. Only upload frames for sessions that received `outcome: "created"` or `"already_exists"` from `POST /sync/sessions`. Sessions with `outcome: "rejected"` cannot accept frames.

---

*For backend implementation details, see [OFFLINE_SYNC.md](./OFFLINE_SYNC.md).*  
*For API schema reference, see [API_SPEC.md](./API_SPEC.md).*
