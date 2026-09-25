"use client";

/**
 * useSyncQueue — React hook for the offline upload queue.
 *
 * Responsibilities:
 *   • Reads counts from IndexedDB and exposes them to the UI
 *   • Listens for online/offline events and auto-triggers uploads
 *   • Auto-syncs every AUTO_SYNC_INTERVAL_MS (30 minutes) if pending frames exist
 *   • Forwards BACKGROUND_SYNC messages from the service worker
 *   • Exposes `triggerSync()` for manual retry and `secondsUntilAutoSync` for countdown
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getAllFrames,
  getFramesBySession,
  getPendingRecordingCount,
  getPendingSessionCount,
  type PendingFrame,
  type FrameStatus,
} from "@/lib/offline-store";
import { processSyncQueue, processRecordingQueue, processSessionQueue, registerBackgroundSync } from "@/lib/sync-engine";

// Auto-sync fires 30 minutes after the last completed sync (or page load)
const AUTO_SYNC_INTERVAL_MS = 30 * 60 * 1000;

export interface SyncQueueState {
  pending:   number;
  uploading: number;
  done:      number;
  failed:    number;
  skipped:   number;
  total:     number;
  /** Queued audio/video recordings not yet on the server. */
  recordingsPending: number;
  /** Sessions created offline that haven't synced to the server yet. */
  sessionsPending: number;
  isOnline:  boolean;
  isSyncing: boolean;
  /** Seconds remaining until the next scheduled auto-sync. null = no pending frames. */
  secondsUntilAutoSync: number | null;
  /** Timestamp of the last completed sync pass (or null). */
  lastSyncAt: Date | null;
}

const ZERO: SyncQueueState = {
  pending: 0, uploading: 0, done: 0, failed: 0, skipped: 0,
  total: 0, recordingsPending: 0, sessionsPending: 0, isOnline: true, isSyncing: false,
  secondsUntilAutoSync: null, lastSyncAt: null,
};

function tally(frames: PendingFrame[]): Omit<SyncQueueState, "isOnline" | "isSyncing" | "secondsUntilAutoSync" | "lastSyncAt" | "recordingsPending" | "sessionsPending"> {
  const c: Record<FrameStatus, number> = {
    pending: 0, uploading: 0, done: 0, failed: 0, skipped: 0,
  };
  for (const f of frames) c[f.status]++;
  return { ...c, total: frames.length };
}

export function useSyncQueue(sessionId?: string): SyncQueueState & {
  triggerSync: () => Promise<void>;
  refresh: () => Promise<void>;
} {
  const [state, setState] = useState<SyncQueueState>(ZERO);
  const syncingRef   = useRef(false);
  const nextSyncRef  = useRef<Date>(new Date(Date.now() + AUTO_SYNC_INTERVAL_MS));
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Read counts from IDB ──────────────────────────────────────────────────
  const refresh = useCallback(async () => {
    try {
      const [frames, recordingsPending, sessionsPending] = await Promise.all([
        sessionId ? getFramesBySession(sessionId) : getAllFrames(),
        getPendingRecordingCount(),
        getPendingSessionCount(),
      ]);
      setState((prev) => ({ ...prev, ...tally(frames), recordingsPending, sessionsPending }));
    } catch {
      // IDB not available (SSR or private browsing) — leave counts at 0
    }
  }, [sessionId]);

  // ── Upload queue ──────────────────────────────────────────────────────────
  const triggerSync = useCallback(async () => {
    if (syncingRef.current) return;
    if (typeof navigator === "undefined" || !navigator.onLine) return;

    syncingRef.current = true;
    setState((prev) => ({ ...prev, isSyncing: true }));

    try {
      // Run all three queues concurrently — sessions first so frames/recordings
      // have a valid server-side session to attach to on next pass.
      await Promise.all([
        processSessionQueue(),
        processSyncQueue(() => refresh()),
        processRecordingQueue(),
      ]);
      nextSyncRef.current = new Date(Date.now() + AUTO_SYNC_INTERVAL_MS);
      setState((prev) => ({ ...prev, lastSyncAt: new Date() }));
    } finally {
      syncingRef.current = false;
      setState((prev) => ({ ...prev, isSyncing: false }));
      refresh();
    }
  }, [refresh]);

  // ── Countdown ticker ─────────────────────────────────────────────────────
  // Updates secondsUntilAutoSync every second when there are pending frames.
  useEffect(() => {
    if (countdownRef.current) clearInterval(countdownRef.current);

    countdownRef.current = setInterval(() => {
      const hasPending = state.pending > 0 || state.uploading > 0;
      if (!hasPending) {
        // Only update state if value actually changed — avoids re-renders every second
        setState((prev) => prev.secondsUntilAutoSync === null ? prev : { ...prev, secondsUntilAutoSync: null });
        return;
      }
      const secs = Math.max(0, Math.round((nextSyncRef.current.getTime() - Date.now()) / 1000));
      setState((prev) => prev.secondsUntilAutoSync === secs ? prev : { ...prev, secondsUntilAutoSync: secs });
    }, 1000);

    return () => {
      if (countdownRef.current) clearInterval(countdownRef.current);
    };
  }, [state.pending, state.uploading]);

  // ── 30-minute auto-sync timer ─────────────────────────────────────────────
  useEffect(() => {
    const id = setInterval(() => {
      const hasPending = state.pending > 0 || state.uploading > 0;
      if (hasPending && typeof navigator !== "undefined" && navigator.onLine) {
        triggerSync();
      }
    }, AUTO_SYNC_INTERVAL_MS);
    return () => clearInterval(id);
  // We intentionally only re-register on triggerSync reference change, not on
  // state.pending — otherwise the interval resets every second during capture.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [triggerSync]);

  // ── Initialise ────────────────────────────────────────────────────────────
  useEffect(() => {
    setState((prev) => ({
      ...prev,
      isOnline: typeof navigator !== "undefined" ? navigator.onLine : true,
    }));
    refresh();
    if (typeof navigator !== "undefined" && navigator.onLine) {
      triggerSync();
    }
    registerBackgroundSync();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Online/offline events ─────────────────────────────────────────────────
  useEffect(() => {
    const onOnline = () => {
      setState((prev) => ({ ...prev, isOnline: true }));
      triggerSync();
      registerBackgroundSync();
    };
    const onOffline = () => setState((prev) => ({ ...prev, isOnline: false }));
    window.addEventListener("online",  onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("online",  onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, [triggerSync]);

  // ── Service worker: BACKGROUND_SYNC message ───────────────────────────────
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    const handler = (ev: MessageEvent) => {
      if (ev.data?.type === "BACKGROUND_SYNC") triggerSync();
    };
    navigator.serviceWorker.addEventListener("message", handler);
    return () => navigator.serviceWorker.removeEventListener("message", handler);
  }, [triggerSync]);

  // ── Periodic refresh ──────────────────────────────────────────────────────
  useEffect(() => {
    const ms = state.isSyncing ? 5_000 : 30_000;
    const id = setInterval(refresh, ms);
    return () => clearInterval(id);
  }, [refresh, state.isSyncing]);

  return { ...state, triggerSync, refresh };
}
