"use client";

/**
 * "Hey XP" wake word — holds a WebSocket open to the backend's
 * on-device detector (app/services/wake_word_service.py on the Pi, using
 * openWakeWord against its own microphone) and calls onWake() the instant
 * a detection is pushed through. Detection itself happens entirely on the
 * backend machine, not in this browser tab — this hook only relays it.
 *
 * This replaced two earlier approaches, in order:
 *   1. Chrome's browser-native SpeechRecognition matching a loose substring
 *      of the wake phrase — turned out NOT to be local/on-device despite
 *      appearances (it streams audio to Google's speech service), and that
 *      round trip was the real, unfixable-in-software source of a
 *      multi-second wake-to-open delay (reported 2026-09-11).
 *   2. Picovoice Porcupine (on-device WASM, in-browser) — genuinely local
 *      and fast, but training a custom keyword requires a Picovoice
 *      account and goes through their review queue before the file is
 *      downloadable, which stalled rollout (2026-09-11).
 * openWakeWord avoids both problems: free/open-source, no account, no
 * review queue (a custom keyword is trained locally via its own notebook),
 * and running it backend-side means no browser mic-permission dance just
 * to listen for a wake phrase.
 */

import { useEffect, useRef, useState } from "react";

export type WakeWordStatus =
  | "idle" // not currently trying to connect (disabled, or assistant open)
  | "connecting"
  | "listening" // WebSocket open — backend is actively listening
  | "error"; // couldn't connect / connection dropped repeatedly

interface UseWakeWordOptions {
  enabled: boolean;
  onWake: () => void;
}

interface UseWakeWordResult {
  status: WakeWordStatus;
  error: string | null;
}

const WS_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/v1")
  .replace(/^http/, "ws") + "/wake-word/ws";

// Reconnect on drop (backend restart, Wi-Fi blip) — capped so a backend
// that's simply not running this feature doesn't spin forever in the
// console; the mic-tap fallback always still works regardless.
//
// Exponential, not fixed-2s: confirmed live 2026-09-21 that a connection
// which keeps failing to stay open reconnected every single 2 seconds,
// indefinitely — sustained background churn on a Raspberry Pi, and browsers
// cap concurrent connections per origin, so a wake-word connection stuck
// retrying that fast can starve out unrelated requests (session loads,
// navigation) on the exact same origin. Backing off geometrically after
// repeated failures makes a genuinely broken connection cheap to sit on
// instead of hammering the server forever at the shortest possible interval.
const RECONNECT_BASE_DELAY_MS = 2000;
const RECONNECT_MAX_DELAY_MS = 30_000;
const MAX_RECONNECT_ATTEMPTS = 10;

export function useWakeWord({ enabled, onWake }: UseWakeWordOptions): UseWakeWordResult {
  const [engineStatus, setEngineStatus] = useState<"connecting" | "listening" | "error">("connecting");
  const [engineError, setEngineError] = useState<string | null>(null);
  const onWakeRef = useRef(onWake);
  useEffect(() => { onWakeRef.current = onWake; }, [onWake]);

  const status: WakeWordStatus = enabled ? engineStatus : "idle";
  const error = enabled ? engineError : null;

  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;
    let ws: WebSocket | null = null;
    let attempts = 0;
    let openedAt = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    // A connection only counts as "actually recovered" — resetting the
    // backoff — if it stays open at least this long. Confirmed live
    // 2026-09-21: the connection WAS completing its handshake every single
    // cycle (the backend logged a clean "accepted" / "connection open" each
    // time), just closing again almost immediately after — and because the
    // old code reset the attempt counter on every successful open
    // regardless of how briefly it lasted, the MAX_RECONNECT_ATTEMPTS cap
    // could never actually engage: attempts never climbed past 1 before
    // being zeroed again, producing an unthrottled retry every base-delay
    // interval, indefinitely, rather than backing off or giving up.
    const MIN_STABLE_MS = 5_000;

    const connect = () => {
      if (cancelled) return;
      setEngineStatus("connecting");
      try {
        ws = new WebSocket(WS_URL);
      } catch {
        setEngineStatus("error");
        setEngineError("Couldn't reach the wake-word service.");
        return;
      }

      ws.onopen = () => {
        if (cancelled) return;
        openedAt = Date.now();
        setEngineStatus("listening");
        setEngineError(null);
      };
      ws.onmessage = (event) => {
        if (cancelled) return;
        try {
          const data = JSON.parse(event.data);
          if (data?.type === "wake") onWakeRef.current();
        } catch { /* ignore malformed frame */ }
      };
      ws.onerror = () => { /* onclose follows and handles reconnect */ };
      ws.onclose = () => {
        if (cancelled) return;
        const stayedOpenMs = openedAt ? Date.now() - openedAt : 0;
        attempts = stayedOpenMs >= MIN_STABLE_MS ? 0 : attempts + 1;
        openedAt = 0;
        if (attempts > MAX_RECONNECT_ATTEMPTS) {
          setEngineStatus("error");
          setEngineError("Wake-word service isn't reachable — tap the mic instead.");
          return;
        }
        const delay = Math.min(
          RECONNECT_BASE_DELAY_MS * 2 ** (attempts - 1),
          RECONNECT_MAX_DELAY_MS,
        );
        reconnectTimer = setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws) {
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        ws.close();
      }
    };
  }, [enabled]);

  return { status, error };
}
