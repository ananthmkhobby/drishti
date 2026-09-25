"use client";

/**
 * useEventPoller — polls GET /sync/events every 10 s while the page is visible.
 *
 * On each poll it advances the syncCursor stored in IDB so restarts are incremental.
 * When AI_OUTPUT_READY or AUDIO_TRANSCRIBED events arrive for the current session,
 * it calls `onOutputReady()` so the caller can revalidate SWR caches.
 */

import { useCallback, useEffect, useRef } from "react";
import { kvGet, kvSet } from "@/lib/offline-store";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/v1";
const POLL_INTERVAL_MS = 10_000;
const CURSOR_KEY = "syncCursor";

interface SyncEvent {
  id: string;
  session_id: string | null;
  type: string;
  payload: Record<string, unknown> | null;
  created_at: string;
}

interface PollResult {
  events: SyncEvent[];
  next_cursor: string | null;
}

export function useEventPoller(options: {
  sessionId?: string;
  onOutputReady?: (sessionId: string, outputTypes: string[]) => void;
  onAudioTranscribed?: (sessionId: string) => void;
  onOCRDone?: (sessionId: string) => void;
  onPracticeAttemptDone?: (sessionId: string, attemptId: string, questionId: string) => void;
  enabled?: boolean;
}): void {
  const { sessionId, onOutputReady, onAudioTranscribed, onOCRDone, onPracticeAttemptDone, enabled = true } = options;

  const timerRef    = useRef<ReturnType<typeof setTimeout> | null>(null);
  const runningRef  = useRef(false);

  const poll = useCallback(async () => {
    if (runningRef.current) return;
    if (typeof navigator !== "undefined" && !navigator.onLine) return;

    runningRef.current = true;
    try {
      const cursor = await kvGet(CURSOR_KEY).catch(() => undefined);

      const params = new URLSearchParams();
      if (sessionId) params.set("session_id", sessionId);
      if (cursor)    params.set("since", cursor);
      params.set("limit", "50");

      const res = await fetch(`${BASE_URL}/sync/events?${params}`, { cache: "no-store" });
      if (!res.ok) return;

      const data: PollResult = await res.json();

      if (data.next_cursor) {
        await kvSet(CURSOR_KEY, data.next_cursor).catch(() => {});
      }

      for (const ev of data.events) {
        const evSession = ev.session_id;
        if (!evSession) continue;

        if (ev.type === "AI_OUTPUT_READY" && onOutputReady) {
          const outputTypes = (ev.payload?.output_types as string[]) ?? [];
          onOutputReady(evSession, outputTypes);
        }
        if (ev.type === "AUDIO_TRANSCRIBED" && onAudioTranscribed) {
          onAudioTranscribed(evSession);
        }
        if (ev.type === "OCR_DONE" && onOCRDone) {
          onOCRDone(evSession);
        }
        if (ev.type === "PRACTICE_ATTEMPT_DONE" && onPracticeAttemptDone) {
          const attemptId = (ev.payload?.attempt_id as string) ?? "";
          const questionId = (ev.payload?.question_id as string) ?? "";
          onPracticeAttemptDone(evSession, attemptId, questionId);
        }
      }
    } catch {
      // Network error while polling — silent, next tick will retry
    } finally {
      runningRef.current = false;
    }
  }, [sessionId, onOutputReady, onAudioTranscribed, onOCRDone, onPracticeAttemptDone]);

  useEffect(() => {
    if (!enabled) return;

    // Poll immediately on mount, then on interval
    poll();

    const schedule = () => {
      timerRef.current = setTimeout(() => {
        poll().then(schedule);
      }, POLL_INTERVAL_MS);
    };
    schedule();

    // Pause polling when tab is hidden, resume on visibility
    const onVisible = () => {
      if (document.visibilityState === "visible") poll();
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [enabled, poll]);
}
