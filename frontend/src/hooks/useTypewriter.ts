"use client";

import { useEffect, useRef, useState } from "react";

const DEFAULT_CHARS_PER_TICK = 1;
const DEFAULT_INTERVAL_MS = 40;

/**
 * Paces the reveal of `fullText` at a steady, readable rate instead of
 * dumping it on screen the instant each network chunk arrives — streamed
 * teaching content came in bursty (however fast/slow OpenAI happened to
 * emit tokens that moment), which read as jerky, not "live typing".
 *
 * Grows toward `fullText` as it changes (streaming continues); if
 * `fullText` is replaced with something that ISN'T an extension of what
 * was already shown (a genuinely new segment, not more of the same one),
 * the reveal restarts from empty rather than trying to diff the jump.
 */
export function useTypewriter(
  fullText: string,
  opts?: { charsPerTick?: number; intervalMs?: number; enabled?: boolean },
): string {
  const charsPerTick = opts?.charsPerTick ?? DEFAULT_CHARS_PER_TICK;
  const intervalMs = opts?.intervalMs ?? DEFAULT_INTERVAL_MS;
  const enabled = opts?.enabled ?? true;

  const [shown, setShown] = useState("");
  const prevFullRef = useRef("");

  useEffect(() => {
    if (!fullText.startsWith(prevFullRef.current)) {
      setShown("");
    }
    prevFullRef.current = fullText;
  }, [fullText]);

  useEffect(() => {
    if (!enabled) {
      setShown(fullText);
      return;
    }
    const id = setInterval(() => {
      setShown((s) => (s.length >= fullText.length ? s : fullText.slice(0, s.length + charsPerTick)));
    }, intervalMs);
    return () => clearInterval(id);
  }, [fullText, enabled, charsPerTick, intervalMs]);

  return shown;
}
