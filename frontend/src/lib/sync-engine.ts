/**
 * Sync engine — uploads queued frames and recordings to the backend.
 *
 * This module is browser-only (uses canvas, Blob, fetch).
 */

import {
  getFramesByStatus,
  updateFrame,
  type PendingFrame,
  getPendingRecordingEntries,
  updateRecordingEntry,
  deleteRecordingEntry,
  getBlobFromStore,
  deleteBlobFromStore,
  getPendingSessionQueue,
  updatePendingSession,
  removePendingSession,
} from "./offline-store";

// ── Constants ─────────────────────────────────────────────────────────────────

const MAX_RETRIES = 5;
/** Exponential back-off delays in ms: 30s → 1m → 2m → 5m → 15m */
const BACKOFF_MS  = [30_000, 60_000, 120_000, 300_000, 900_000];
const BASE_URL    = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/v1";

// ── Image compression ─────────────────────────────────────────────────────────

/**
 * Compress `blob` to the target quality/size per OFFLINE_SYNC spec:
 *  - <200 KB  → upload as-is
 *  - 200–500 KB → quality 0.85
 *  - >500 KB  → quality 0.75
 *  - If result still >300 KB → resize to 1280×960 then re-compress
 */
export async function compressImage(blob: Blob): Promise<Blob> {
  const sizeKb = blob.size / 1024;
  if (sizeKb < 200) return blob;

  const quality  = sizeKb > 500 ? 0.75 : 0.85;
  const attempt1 = await _canvasEncode(blob, null, quality);

  if (attempt1.size / 1024 > 300) {
    return _canvasEncode(blob, { w: 1280, h: 960 }, quality);
  }
  return attempt1;
}

async function _canvasEncode(
  blob: Blob,
  resize: { w: number; h: number } | null,
  quality: number
): Promise<Blob> {
  const bmp    = await createImageBitmap(blob);
  const canvas = document.createElement("canvas");

  if (resize) {
    const ratio   = Math.min(resize.w / bmp.width, resize.h / bmp.height);
    canvas.width  = Math.round(bmp.width  * ratio);
    canvas.height = Math.round(bmp.height * ratio);
  } else {
    canvas.width  = bmp.width;
    canvas.height = bmp.height;
  }

  const ctx = canvas.getContext("2d")!;
  ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height);
  bmp.close();

  return new Promise<Blob>((resolve) =>
    canvas.toBlob((b) => resolve(b ?? blob), "image/jpeg", quality)
  );
}

// ── Single-frame upload ───────────────────────────────────────────────────────

interface UploadError extends Error {
  nonRetryable?: boolean;
  status?: number;
}

async function _uploadFrame(frame: PendingFrame): Promise<string> {
  const compressed = await compressImage(frame.blob);

  const fd = new FormData();
  fd.append("image",          new File([compressed], "frame.jpg", { type: "image/jpeg" }));
  fd.append("captured_at",    frame.capturedAt);
  fd.append("sequence_no",    String(frame.sequenceNo));
  fd.append("local_frame_id", frame.id);

  const res = await fetch(`${BASE_URL}/sessions/${frame.sessionId}/frames`, {
    method: "POST",
    body: fd,
  });

  // 409 Conflict = server already has this frame (idempotent dedup)
  if (res.status === 409) {
    const body = await res.json().catch(() => ({}));
    return (body.frame_id as string) ?? frame.id;
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const err: UploadError = new Error(body.message ?? `HTTP ${res.status}`);
    err.status = res.status;
    // 4xx errors (except 409) are non-retryable
    if (res.status >= 400 && res.status < 500) err.nonRetryable = true;
    throw err;
  }

  const body = await res.json();
  return body.frame_id as string;
}

// ── Queue processor ───────────────────────────────────────────────────────────

export interface SyncResult {
  uploaded: number;
  failed:   number;
  skipped:  number;
}

let _activeSyncLock = false;

/** Returns true while a sync pass is in flight. */
export function isSyncing(): boolean {
  return _activeSyncLock;
}

/**
 * Process the offline upload queue.
 * Safe to call concurrently — a second call while one is running is a no-op.
 *
 * `onProgress` is called after each frame attempt so the UI can update counts.
 */
export async function processSyncQueue(
  onProgress?: (result: SyncResult) => void
): Promise<SyncResult> {
  if (_activeSyncLock) return { uploaded: 0, failed: 0, skipped: 0 };
  _activeSyncLock = true;

  const result: SyncResult = { uploaded: 0, failed: 0, skipped: 0 };

  try {
    // Collect pending + previously-interrupted uploads
    const [pending, uploading] = await Promise.all([
      getFramesByStatus("pending"),
      getFramesByStatus("uploading"),  // interrupted from a crashed session
    ]);

    const queue: PendingFrame[] = [...pending, ...uploading];

    for (const frame of queue) {
      // Honour exponential back-off — skip if not yet due
      if (frame.retryCount > 0 && frame.lastAttempt) {
        const delay   = BACKOFF_MS[Math.min(frame.retryCount - 1, BACKOFF_MS.length - 1)];
        const elapsed = Date.now() - new Date(frame.lastAttempt).getTime();
        if (elapsed < delay) continue;
      }

      // Mark as in-flight
      await updateFrame(frame.id, {
        status:      "uploading",
        lastAttempt: new Date().toISOString(),
      });

      try {
        const remoteId = await _uploadFrame(frame);
        await updateFrame(frame.id, {
          status:        "done",
          remoteFrameId: remoteId,
          errorMessage:  null,
        });
        result.uploaded++;
      } catch (err: unknown) {
        const uploadErr = err as UploadError;
        const newCount  = frame.retryCount + 1;
        const maxed     = uploadErr.nonRetryable || newCount >= MAX_RETRIES;

        await updateFrame(frame.id, {
          status:       maxed ? "skipped" : "pending",
          retryCount:   newCount,
          errorMessage: uploadErr.message ?? "Unknown error",
        });

        if (maxed) result.skipped++;
        else       result.failed++;
      }

      onProgress?.(result);
    }
  } finally {
    _activeSyncLock = false;
  }

  return result;
}

/**
 * Register a Background Sync tag with the service worker.
 * Ignored silently if the API is not available (Firefox, iOS < 16.4).
 */
export async function registerBackgroundSync(): Promise<void> {
  try {
    if (!("serviceWorker" in navigator)) return;
    const reg = await navigator.serviceWorker.ready;
    if ("sync" in reg) {
      await (reg as ServiceWorkerRegistration & { sync: { register(tag: string): Promise<void> } })
        .sync.register("aci-frame-sync");
    }
  } catch {
    // Non-fatal — page-level sync covers this
  }
}

// ── Recording queue (audio / video) ──────────────────────────────────────────

// Backoff between attempts while a recording keeps failing. Deliberately
// UNCAPPED by attempt count for anything that isn't a definite server-side
// rejection (see the catch block below) — this app is built for teachers on
// unreliable/rural connectivity, and a real outage routinely outlasts what
// used to be a hard 5-attempt / ~104-second retry budget. Once that budget
// was exhausted the recording was marked "failed" and getPendingRecording
// Entries() only ever reads "pending"/"uploading", so it silently stopped
// being retried forever after — including by the "Sync now" button —
// confirmed live 2026-09-21 as exactly "internet came back, still stuck."
const RECORDING_BACKOFF_MS = [2_000, 4_000, 8_000, 30_000, 60_000];

export interface RecordingSyncResult {
  uploaded: number;
  failed:   number;
}

let _recordingSyncLock = false;

/**
 * Upload any queued audio/video recordings.
 * Safe to call concurrently — a second call while one is running is a no-op.
 *
 * When a recording uploads successfully a CustomEvent "aci:recording-synced"
 * is dispatched on window so the capture page can revalidate its SWR cache.
 */
export async function processRecordingQueue(): Promise<RecordingSyncResult> {
  if (_recordingSyncLock) return { uploaded: 0, failed: 0 };
  _recordingSyncLock = true;

  const result: RecordingSyncResult = { uploaded: 0, failed: 0 };

  try {
    const entries = await getPendingRecordingEntries();
    const now     = Date.now();
    const due     = entries.filter((e) => e.nextRetryAt <= now);

    for (const entry of due) {
      // Retrieve raw blob
      let blob: Blob | undefined;
      try {
        const blobEntry = await getBlobFromStore(entry.blobId);
        blob = blobEntry?.data;
      } catch { /* storage error — treat as missing */ }

      if (!blob) {
        await updateRecordingEntry(entry.id, {
          status:       "failed",
          errorMessage: "Blob missing from local storage — may have been cleared",
        });
        result.failed++;
        continue;
      }

      await updateRecordingEntry(entry.id, { status: "uploading" });

      const endpoint = entry.type === "audio"
        ? `${BASE_URL}/sessions/${entry.sessionId}/audio`
        : `${BASE_URL}/sessions/${entry.sessionId}/video`;

      try {
        const fd = new FormData();
        fd.append("file", new File([blob], entry.filename, { type: entry.mimeType }));

        const res = await fetch(endpoint, {
          method:  "POST",
          body:    fd,
          headers: { "Idempotency-Key": entry.id },
        });

        // 409 = server already processed this key (safe duplicate)
        if (!res.ok && res.status !== 409) {
          const body = await res.json().catch(() => ({}));
          const err: UploadError = new Error((body as { message?: string }).message ?? `HTTP ${res.status}`);
          err.status = res.status;
          if (res.status >= 400 && res.status < 500) err.nonRetryable = true;
          throw err;
        }

        // Success — clean up local storage
        await updateRecordingEntry(entry.id, { status: "done" });
        await deleteBlobFromStore(entry.blobId);
        await deleteRecordingEntry(entry.id);

        // Notify the capture page so it can refresh the recordings list
        if (typeof window !== "undefined") {
          window.dispatchEvent(
            new CustomEvent("aci:recording-synced", { detail: { sessionId: entry.sessionId } })
          );
        }

        result.uploaded++;
      } catch (err: unknown) {
        const uploadErr = err as UploadError;
        const newCount  = entry.retryCount + 1;
        // Only a definite server-side rejection (4xx — bad file, session
        // gone, etc.) ever stops retrying; that response is going to be
        // identical next time. Anything else — no network, a timeout, a
        // 5xx — keeps retrying indefinitely at the longest backoff interval,
        // since it's exactly the kind of failure that resolves on its own
        // once connectivity (or the server) comes back.
        const permanentlyFailed = !!uploadErr.nonRetryable;
        const backoffMs = RECORDING_BACKOFF_MS[Math.min(newCount - 1, RECORDING_BACKOFF_MS.length - 1)];

        await updateRecordingEntry(entry.id, {
          status:       permanentlyFailed ? "failed" : "pending",
          retryCount:   newCount,
          nextRetryAt:  Date.now() + backoffMs,
          errorMessage: uploadErr.message ?? "Unknown error",
        });

        result.failed++;
      }
    }
  } finally {
    _recordingSyncLock = false;
  }

  return result;
}

// ── Session create queue ──────────────────────────────────────────────────────

const SESSION_BACKOFF_MS  = [2_000, 5_000, 15_000, 60_000, 300_000];
const SESSION_MAX_RETRIES = 5;

export interface SessionSyncResult {
  synced: number;
  failed: number;
}

let _sessionSyncLock = false;

/**
 * Upload any sessions created offline.
 * Each pending session is POSTed with Idempotency-Key = its client UUID so
 * retries are safe. On 200 or 409 (already exists) the entry is removed.
 * On success a CustomEvent "aci:session-synced" is dispatched so the
 * sessions list can refresh.
 */
export async function processSessionQueue(): Promise<SessionSyncResult> {
  if (_sessionSyncLock) return { synced: 0, failed: 0 };
  _sessionSyncLock = true;

  const result: SessionSyncResult = { synced: 0, failed: 0 };

  try {
    const entries = await getPendingSessionQueue();
    const due = entries.filter((e) => e.nextRetryAt <= Date.now());

    for (const entry of due) {
      await updatePendingSession(entry.id, { status: "syncing" });

      try {
        const res = await fetch(`${BASE_URL}/sessions`, {
          method:  "POST",
          headers: {
            "Content-Type":    "application/json",
            "Idempotency-Key": entry.id,
          },
          body: JSON.stringify({
            ...entry.payload,
            client_session_id: entry.id,
          }),
        });

        // 201 = created, 200 = idempotent hit — both mean the session exists server-side
        if (res.ok || res.status === 200 || res.status === 409) {
          await removePendingSession(entry.id);
          if (typeof window !== "undefined") {
            window.dispatchEvent(
              new CustomEvent("aci:session-synced", { detail: { sessionId: entry.id } })
            );
          }
          result.synced++;
        } else {
          const body = await res.json().catch(() => ({}));
          const err = new Error((body as { message?: string }).message ?? `HTTP ${res.status}`);
          throw Object.assign(err, {
            nonRetryable: res.status >= 400 && res.status < 500 && res.status !== 409,
          });
        }
      } catch (err: unknown) {
        const e = err as Error & { nonRetryable?: boolean };
        const newCount = entry.retryCount + 1;
        const maxed    = e.nonRetryable || newCount >= SESSION_MAX_RETRIES;
        const backoff  = SESSION_BACKOFF_MS[Math.min(newCount - 1, SESSION_BACKOFF_MS.length - 1)];

        await updatePendingSession(entry.id, {
          status:       maxed ? "failed" : "pending",
          retryCount:   newCount,
          nextRetryAt:  Date.now() + backoff,
          errorMessage: e.message ?? "Unknown error",
        });

        result.failed++;
      }
    }
  } finally {
    _sessionSyncLock = false;
  }

  return result;
}
