/**
 * Offline frame store — IndexedDB wrapper.
 *
 * DB:  aci_v1  (version 2 adds blobs + recordingQueue stores)
 * Stores:
 *   pending_frames   — v1: JPEG frame blobs queued for upload
 *   blobs            — v2: raw audio/video blobs
 *   recordingQueue   — v2: audio/video upload queue entries
 */

import { generateUUID } from "@/lib/uuid";

export type FrameStatus =
  | "pending"
  | "uploading"
  | "done"
  | "failed"
  | "skipped";

export interface PendingFrame {
  id: string;
  sessionId: string;
  sequenceNo: number;
  blob: Blob;
  capturedAt: string;
  sizeKb: number;
  status: FrameStatus;
  retryCount: number;
  lastAttempt: string | null;
  errorMessage: string | null;
  remoteFrameId: string | null;
}

// ── v2 types ─────────────────────────────────────────────────────────────────

export interface BlobEntry {
  id: string;
  data: Blob;
}

export type RecordingQueueStatus = "pending" | "uploading" | "done" | "failed";

export interface RecordingQueueEntry {
  /** UUID — used as idempotency key sent to server. */
  id: string;
  sessionId: string;
  type: "audio" | "video";
  /** Key in the blobs store. */
  blobId: string;
  mimeType: string;
  filename: string;
  status: RecordingQueueStatus;
  retryCount: number;
  /** Epoch ms — when to next attempt (respects backoff). */
  nextRetryAt: number;
  createdAt: number;
  errorMessage: string | null;
}

// ── DB bootstrap ──────────────────────────────────────────────────────────────

const DB_NAME    = "aci_v1";
const DB_VERSION = 4;
const FRAMES_STORE    = "pending_frames";
const BLOBS_STORE     = "blobs";
const RECORDING_STORE = "recordingQueue";
// v3: read-cache stores
const SESSIONS_CACHE_STORE = "sessions_cache";
const OUTPUTS_CACHE_STORE  = "outputs_cache";
const KV_STORE             = "kv";
// v4: offline session create queue
const SESSIONS_QUEUE_STORE = "sessionsQueue";

let _db: IDBDatabase | null = null;

export async function openDB(): Promise<IDBDatabase> {
  if (_db) return _db;

  if (typeof indexedDB === "undefined") {
    throw new Error("IndexedDB is not available in this environment");
  }

  return new Promise<IDBDatabase>((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);

    req.onupgradeneeded = (ev) => {
      const db = (ev.target as IDBOpenDBRequest).result;

      // ── v1 store (preserve on upgrade) ──────────────────────────────────────
      if (!db.objectStoreNames.contains(FRAMES_STORE)) {
        const store = db.createObjectStore(FRAMES_STORE, { keyPath: "id" });
        store.createIndex("by_session",     "sessionId",              { unique: false });
        store.createIndex("by_status",      "status",                 { unique: false });
        store.createIndex("by_sess_status", ["sessionId", "status"],  { unique: false });
      }

      // ── v2 stores ────────────────────────────────────────────────────────────
      if (!db.objectStoreNames.contains(BLOBS_STORE)) {
        db.createObjectStore(BLOBS_STORE, { keyPath: "id" });
      }

      if (!db.objectStoreNames.contains(RECORDING_STORE)) {
        const rq = db.createObjectStore(RECORDING_STORE, { keyPath: "id" });
        rq.createIndex("by_session", "sessionId", { unique: false });
        rq.createIndex("by_status",  "status",    { unique: false });
      }

      // ── v3 stores: read cache ─────────────────────────────────────────────────
      if (!db.objectStoreNames.contains(SESSIONS_CACHE_STORE)) {
        db.createObjectStore(SESSIONS_CACHE_STORE, { keyPath: "key" });
      }

      if (!db.objectStoreNames.contains(OUTPUTS_CACHE_STORE)) {
        db.createObjectStore(OUTPUTS_CACHE_STORE, { keyPath: "key" });
      }

      if (!db.objectStoreNames.contains(KV_STORE)) {
        db.createObjectStore(KV_STORE, { keyPath: "key" });
      }

      // ── v4 store: offline session create queue ───────────────────────────────
      if (!db.objectStoreNames.contains(SESSIONS_QUEUE_STORE)) {
        const sq = db.createObjectStore(SESSIONS_QUEUE_STORE, { keyPath: "id" });
        sq.createIndex("by_status", "status", { unique: false });
      }
    };

    req.onsuccess = () => { _db = req.result; resolve(req.result); };
    req.onerror   = () => reject(req.error);
    req.onblocked = () => reject(new Error("IndexedDB blocked — close other Drishti tabs"));
  });
}

// ── Generic promise wrapper ───────────────────────────────────────────────────

function wrap<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror   = () => reject(req.error);
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// FRAME STORE (v1 — unchanged API)
// ═══════════════════════════════════════════════════════════════════════════

export async function addPendingFrame(
  frame: Omit<PendingFrame, "status" | "retryCount" | "lastAttempt" | "errorMessage" | "remoteFrameId">
): Promise<void> {
  const db = await openDB();
  const tx = db.transaction(FRAMES_STORE, "readwrite");
  await wrap(tx.objectStore(FRAMES_STORE).put({
    ...frame,
    status:        "pending",
    retryCount:    0,
    lastAttempt:   null,
    errorMessage:  null,
    remoteFrameId: null,
  } satisfies PendingFrame));
}

export async function updateFrame(
  id: string,
  patch: Partial<Omit<PendingFrame, "id">>
): Promise<void> {
  const db    = await openDB();
  const tx    = db.transaction(FRAMES_STORE, "readwrite");
  const store = tx.objectStore(FRAMES_STORE);
  const existing = await wrap<PendingFrame>(store.get(id));
  if (!existing) return;
  await wrap(store.put({ ...existing, ...patch }));
}

export async function getFrame(id: string): Promise<PendingFrame | undefined> {
  const db = await openDB();
  return wrap(db.transaction(FRAMES_STORE, "readonly").objectStore(FRAMES_STORE).get(id));
}

export async function getFramesByStatus(status: FrameStatus): Promise<PendingFrame[]> {
  const db    = await openDB();
  const store = db.transaction(FRAMES_STORE, "readonly").objectStore(FRAMES_STORE);
  return wrap(store.index("by_status").getAll(status));
}

export async function getFramesBySession(sessionId: string): Promise<PendingFrame[]> {
  const db    = await openDB();
  const store = db.transaction(FRAMES_STORE, "readonly").objectStore(FRAMES_STORE);
  return wrap(store.index("by_session").getAll(sessionId));
}

export async function getAllFrames(): Promise<PendingFrame[]> {
  const db = await openDB();
  return wrap(db.transaction(FRAMES_STORE, "readonly").objectStore(FRAMES_STORE).getAll());
}

export async function getPendingCount(): Promise<number> {
  const db    = await openDB();
  const store = db.transaction(FRAMES_STORE, "readonly").objectStore(FRAMES_STORE);
  const idx   = store.index("by_status");
  const [p, u] = await Promise.all([
    wrap(idx.count("pending")),
    wrap(idx.count("uploading")),
  ]);
  return p + u;
}

export async function getSessionSyncCounts(sessionId: string): Promise<Record<FrameStatus, number>> {
  const frames = await getFramesBySession(sessionId);
  const counts: Record<FrameStatus, number> = {
    pending: 0, uploading: 0, done: 0, failed: 0, skipped: 0,
  };
  for (const f of frames) counts[f.status]++;
  return counts;
}

export async function deleteFrame(id: string): Promise<void> {
  const db = await openDB();
  await wrap(db.transaction(FRAMES_STORE, "readwrite").objectStore(FRAMES_STORE).delete(id));
}

export async function pruneUploadedFrames(ageMs = 7 * 24 * 3600_000): Promise<number> {
  const all    = await getAllFrames();
  const cutoff = Date.now() - ageMs;
  let pruned   = 0;
  for (const f of all) {
    if (f.status === "done" && new Date(f.capturedAt).getTime() < cutoff) {
      await deleteFrame(f.id);
      pruned++;
    }
  }
  return pruned;
}

// ═══════════════════════════════════════════════════════════════════════════
// BLOB STORE (v2)
// ═══════════════════════════════════════════════════════════════════════════

export async function addBlobToStore(id: string, data: Blob): Promise<void> {
  const db = await openDB();
  await wrap(db.transaction(BLOBS_STORE, "readwrite").objectStore(BLOBS_STORE).put({ id, data }));
}

export async function getBlobFromStore(id: string): Promise<BlobEntry | undefined> {
  const db = await openDB();
  return wrap(db.transaction(BLOBS_STORE, "readonly").objectStore(BLOBS_STORE).get(id));
}

export async function deleteBlobFromStore(id: string): Promise<void> {
  const db = await openDB();
  await wrap(db.transaction(BLOBS_STORE, "readwrite").objectStore(BLOBS_STORE).delete(id));
}

// ═══════════════════════════════════════════════════════════════════════════
// RECORDING QUEUE STORE (v2)
// ═══════════════════════════════════════════════════════════════════════════

export async function addRecordingQueueEntry(entry: RecordingQueueEntry): Promise<void> {
  const db = await openDB();
  await wrap(db.transaction(RECORDING_STORE, "readwrite").objectStore(RECORDING_STORE).put(entry));
}

export async function updateRecordingEntry(
  id: string,
  patch: Partial<Omit<RecordingQueueEntry, "id">>
): Promise<void> {
  const db    = await openDB();
  const tx    = db.transaction(RECORDING_STORE, "readwrite");
  const store = tx.objectStore(RECORDING_STORE);
  const existing = await wrap<RecordingQueueEntry>(store.get(id));
  if (!existing) return;
  await wrap(store.put({ ...existing, ...patch }));
}

export async function getPendingRecordingEntries(): Promise<RecordingQueueEntry[]> {
  const db    = await openDB();
  const store = db.transaction(RECORDING_STORE, "readonly").objectStore(RECORDING_STORE);
  // Get pending + uploading (interrupted) entries
  const [pending, uploading] = await Promise.all([
    wrap<RecordingQueueEntry[]>(store.index("by_status").getAll("pending")),
    wrap<RecordingQueueEntry[]>(store.index("by_status").getAll("uploading")),
  ]);
  return [...pending, ...uploading];
}

export async function getPendingRecordingCount(): Promise<number> {
  const db    = await openDB();
  const store = db.transaction(RECORDING_STORE, "readonly").objectStore(RECORDING_STORE);
  const idx   = store.index("by_status");
  const [p, u] = await Promise.all([
    wrap(idx.count("pending")),
    wrap(idx.count("uploading")),
  ]);
  return p + u;
}

export async function deleteRecordingEntry(id: string): Promise<void> {
  const db = await openDB();
  await wrap(db.transaction(RECORDING_STORE, "readwrite").objectStore(RECORDING_STORE).delete(id));
}

/**
 * Save a recording blob + queue entry atomically.
 * Returns the queue entry id (used as idempotency key).
 */
export async function saveRecordingToQueue(
  sessionId: string,
  type: "audio" | "video",
  blob: Blob,
  mimeType: string,
  filename: string,
): Promise<string> {
  const blobId   = generateUUID();
  const entryId  = generateUUID();

  await addBlobToStore(blobId, blob);
  await addRecordingQueueEntry({
    id:           entryId,
    sessionId,
    type,
    blobId,
    mimeType,
    filename,
    status:       "pending",
    retryCount:   0,
    nextRetryAt:  Date.now(),   // eligible for upload immediately
    createdAt:    Date.now(),
    errorMessage: null,
  });

  return entryId;
}

// ═══════════════════════════════════════════════════════════════════════════
// READ CACHE — sessions + outputs (v3)
// ═══════════════════════════════════════════════════════════════════════════

const CACHE_TTL_MS = 7 * 24 * 3600_000; // 7 days

export interface CachedSessions {
  key: string;          // teacherId
  sessions: unknown[];
  total: number;
  cachedAt: number;
}

export interface CachedOutputs {
  key: string;          // sessionId
  session_id: string;
  outputs: unknown;
  total_tokens: number;
  cachedAt: number;
}

export async function cacheSessions(teacherId: string, data: { sessions: unknown[]; total: number }): Promise<void> {
  const db = await openDB();
  await wrap(db.transaction(SESSIONS_CACHE_STORE, "readwrite").objectStore(SESSIONS_CACHE_STORE).put({
    key: teacherId,
    sessions: data.sessions,
    total: data.total,
    cachedAt: Date.now(),
  }));
}

export async function getCachedSessions(teacherId: string): Promise<CachedSessions | undefined> {
  const db = await openDB();
  const row = await wrap<CachedSessions | undefined>(
    db.transaction(SESSIONS_CACHE_STORE, "readonly").objectStore(SESSIONS_CACHE_STORE).get(teacherId)
  );
  if (!row) return undefined;
  if (Date.now() - row.cachedAt > CACHE_TTL_MS) return undefined;
  return row;
}

export async function cacheOutputs(sessionId: string, data: { session_id: string; outputs: unknown; total_tokens: number }): Promise<void> {
  const db = await openDB();
  await wrap(db.transaction(OUTPUTS_CACHE_STORE, "readwrite").objectStore(OUTPUTS_CACHE_STORE).put({
    key: sessionId,
    ...data,
    cachedAt: Date.now(),
  }));
}

export async function getCachedOutputs(sessionId: string): Promise<CachedOutputs | undefined> {
  const db = await openDB();
  const row = await wrap<CachedOutputs | undefined>(
    db.transaction(OUTPUTS_CACHE_STORE, "readonly").objectStore(OUTPUTS_CACHE_STORE).get(sessionId)
  );
  if (!row) return undefined;
  if (Date.now() - row.cachedAt > CACHE_TTL_MS) return undefined;
  return row;
}

// ═══════════════════════════════════════════════════════════════════════════
// KEY-VALUE STORE — syncCursor, etc. (v3)
// ═══════════════════════════════════════════════════════════════════════════

export async function kvGet(key: string): Promise<string | undefined> {
  const db = await openDB();
  const row = await wrap<{ key: string; value: string } | undefined>(
    db.transaction(KV_STORE, "readonly").objectStore(KV_STORE).get(key)
  );
  return row?.value;
}

export async function kvSet(key: string, value: string): Promise<void> {
  const db = await openDB();
  await wrap(db.transaction(KV_STORE, "readwrite").objectStore(KV_STORE).put({ key, value }));
}

// ═══════════════════════════════════════════════════════════════════════════
// SESSION CREATE QUEUE (v4)
// ═══════════════════════════════════════════════════════════════════════════

export type SessionQueueStatus = "pending" | "syncing" | "done" | "failed";

export interface PendingSessionPayload {
  teacher_id: string;
  subject: string | null;
  grade: string | null;
  board_type: string;
  capture_mode: string;
  capture_interval_sec: number;
  classroom_id: string | null;
}

export interface PendingSession {
  /** Client-generated UUID — used as both the local and server-side session id. */
  id: string;
  payload: PendingSessionPayload;
  status: SessionQueueStatus;
  retryCount: number;
  nextRetryAt: number;
  createdAt: number;
  errorMessage: string | null;
}

export async function savePendingSession(entry: PendingSession): Promise<void> {
  const db = await openDB();
  await wrap(db.transaction(SESSIONS_QUEUE_STORE, "readwrite").objectStore(SESSIONS_QUEUE_STORE).put(entry));
}

export async function getPendingSessionQueue(): Promise<PendingSession[]> {
  const db = await openDB();
  const store = db.transaction(SESSIONS_QUEUE_STORE, "readonly").objectStore(SESSIONS_QUEUE_STORE);
  const [pending, syncing] = await Promise.all([
    wrap<PendingSession[]>(store.index("by_status").getAll("pending")),
    wrap<PendingSession[]>(store.index("by_status").getAll("syncing")),
  ]);
  return [...pending, ...syncing];
}

export async function getPendingSessionCount(): Promise<number> {
  const db = await openDB();
  const store = db.transaction(SESSIONS_QUEUE_STORE, "readonly").objectStore(SESSIONS_QUEUE_STORE);
  const [p, s] = await Promise.all([
    wrap(store.index("by_status").count("pending")),
    wrap(store.index("by_status").count("syncing")),
  ]);
  return p + s;
}

export async function updatePendingSession(
  id: string,
  patch: Partial<Omit<PendingSession, "id">>
): Promise<void> {
  const db  = await openDB();
  const tx  = db.transaction(SESSIONS_QUEUE_STORE, "readwrite");
  const store = tx.objectStore(SESSIONS_QUEUE_STORE);
  const existing = await wrap<PendingSession>(store.get(id));
  if (!existing) return;
  await wrap(store.put({ ...existing, ...patch }));
}

export async function removePendingSession(id: string): Promise<void> {
  const db = await openDB();
  await wrap(db.transaction(SESSIONS_QUEUE_STORE, "readwrite").objectStore(SESSIONS_QUEUE_STORE).delete(id));
}

export async function getAllPendingSessions(): Promise<PendingSession[]> {
  const db = await openDB();
  return wrap<PendingSession[]>(
    db.transaction(SESSIONS_QUEUE_STORE, "readonly").objectStore(SESSIONS_QUEUE_STORE).getAll()
  );
}
