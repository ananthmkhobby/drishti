"use client";

/**
 * Replaces the always-visible "Who needs help" panel with an ephemeral
 * notification from the Classroom Brain: it pops in only when a station's
 * latest attempt actually changes (a new capture just got graded), stays
 * up to AUTO_DISMISS_MS, can be closed any time, and — since a transient
 * popup can be missed — every moment is also kept in a "Show more" history
 * reachable from the docked avatar for the rest of the session.
 *
 * Portaled to document.body for the same reason as CameraSnapButton: this
 * renders inside `cc-rise`-animated ancestors, and a settled `transform`
 * from `animation-fill-mode: both` creates a new containing block for
 * `position: fixed` descendants, so a non-portaled "fixed" bubble would be
 * confined to the wrong box instead of the real viewport.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Brain, Mic, X } from "lucide-react";
import { getPracticeAttemptImageUrl } from "@/lib/api";
import type { PracticeStation, StudentState } from "@/lib/api";
import { PREMIUM_STATE_STYLES, STATE_PRIORITY, timeAgo } from "@/components/practice/guidedPracticeShared";
import { StatePill } from "@/components/practice/GuidedPracticePremiumView";

const INDIGO = "#241F49";
const GOLD = "#D7A24E";
const SERIF = { fontFamily: "var(--font-fraunces), Georgia, serif" };

const AUTO_DISMISS_MS = 30_000;
const TICK_MS = 200;
const NEUTRAL_META = { label: "Captured", fg: "#57534E", bg: "#F1EFEA", dot: "#9A968A" };
// The popup only ever shows the most recent moments — everything older is
// still there, just in the "Show more" history drawer (history itself is
// never trimmed). Reported 2026-09-22: as more captures came in during a
// scan, the popup kept growing and stayed scrolled at the oldest entry
// instead of showing what just arrived.
const QUEUE_VISIBLE_MAX = 5;

interface Moment {
  id: string;
  stationId: string;
  label: string;
  attemptId: string;
  inputType: "image" | "audio";
  studentState: StudentState | null;
  hintText: string | null;
  hintLevel: number | null;
  capturedAt: string | null;
}

function hintLine(m: Moment, t: (s: string) => string): string {
  if (m.hintText) return `Hint (L${m.hintLevel}): ${t(m.hintText)}`;
  if (m.studentState === "solved") return "Solved — nice work.";
  if (m.studentState === "progressing") return "On the right track — no hint needed.";
  return "No hint yet.";
}

export function BrainNudge({ stations, t }: { stations: PracticeStation[]; t: (s: string) => string }) {
  const [queue, setQueue] = useState<Moment[]>([]);
  const [history, setHistory] = useState<Moment[]>([]);
  const [bubbleOpen, setBubbleOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [seenCount, setSeenCount] = useState(0);
  const [barPct, setBarPct] = useState(100);
  const [canPortal, setCanPortal] = useState(false);

  const seenAttempts = useRef<Map<string, string>>(new Map());
  const everMounted = useRef(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const queueScrollRef = useRef<HTMLDivElement | null>(null);

  // Keep the newest moment in view as more come in during a scan — without
  // this the panel stayed scrolled wherever it was (usually the top/oldest
  // entry) while fresh feedback kept arriving below, out of sight.
  useEffect(() => {
    const el = queueScrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [queue]);

  useEffect(() => { setCanPortal(true); }, []);

  const clearTimer = useCallback(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
  }, []);

  const dismiss = useCallback(() => {
    clearTimer();
    setBubbleOpen(false);
    setQueue([]);
  }, [clearTimer]);

  const startTimer = useCallback(() => {
    clearTimer();
    setBarPct(100);
    timerRef.current = setInterval(() => {
      setBarPct((pct) => Math.max(0, pct - 100 / (AUTO_DISMISS_MS / TICK_MS)));
    }, TICK_MS);
  }, [clearTimer]);

  useEffect(() => {
    if (barPct <= 0 && bubbleOpen) dismiss();
  }, [barPct, bubbleOpen, dismiss]);

  useEffect(() => () => clearTimer(), [clearTimer]);

  // Detect which stations' latest attempt actually changed since last render.
  useEffect(() => {
    const fresh: Moment[] = [];
    for (const s of stations) {
      const a = s.latest_attempt;
      if (!a || a.status !== "complete") continue;
      const prev = seenAttempts.current.get(s.station_id);
      if (prev === a.attempt_id) continue;
      seenAttempts.current.set(s.station_id, a.attempt_id);
      if (!everMounted.current) continue; // baseline on first render — no backlog flood
      fresh.push({
        id: a.attempt_id,
        stationId: s.station_id,
        label: s.label,
        attemptId: a.attempt_id,
        inputType: a.input_type === "audio" ? "audio" : "image",
        studentState: a.student_state,
        hintText: a.hint_text,
        hintLevel: a.hint_level,
        capturedAt: a.captured_at,
      });
    }
    everMounted.current = true;
    if (fresh.length === 0) return;

    fresh.sort((x, y) => {
      const px = x.studentState ? STATE_PRIORITY[x.studentState] : 6;
      const py = y.studentState ? STATE_PRIORITY[y.studentState] : 6;
      return px - py;
    });

    setHistory((h) => [...fresh, ...h]);
    // Cap to the most recent QUEUE_VISIBLE_MAX — anything older falls off
    // here but is never lost, since `history` above keeps the complete,
    // untrimmed record.
    setQueue((q) => [...q, ...fresh].slice(-QUEUE_VISIBLE_MAX));
    setBubbleOpen(true);
    startTimer();
  }, [stations, startTimer]);

  const openHistory = useCallback(() => {
    setHistoryOpen(true);
    setSeenCount(history.length);
  }, [history.length]);
  const closeHistory = useCallback(() => setHistoryOpen(false), []);

  const badgeCount = Math.max(0, history.length - seenCount);
  const hasBadge = badgeCount > 0 && !bubbleOpen;

  if (!canPortal) return null;

  return createPortal(
    <>
      <style>{`
        @keyframes bn-pulse { 0% { transform: scale(1); opacity: .55; } 70% { transform: scale(1.4); opacity: 0; } 100% { opacity: 0; } }
        @keyframes bn-bubble-in { from { opacity: 0; transform: translateY(18px) scale(.96); } to { opacity: 1; transform: translateY(0) scale(1); } }
        @keyframes bn-msg-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes bn-drawer-in { from { opacity: 0; transform: translateX(28px); } to { opacity: 1; transform: translateX(0); } }
        @keyframes bn-fade-in { from { opacity: 0; } to { opacity: 1; } }
        .bn-pulse-ring { animation: bn-pulse 2.6s ease-out infinite; }
        .bn-bubble { animation: bn-bubble-in .32s cubic-bezier(.2,.8,.2,1); }
        .bn-msg { animation: bn-msg-in .25s ease-out; }
        .bn-drawer { animation: bn-drawer-in .28s cubic-bezier(.2,.8,.2,1); }
        .bn-backdrop { animation: bn-fade-in .28s ease-out; }
        @media (prefers-reduced-motion: reduce) {
          .bn-pulse-ring, .bn-bubble, .bn-msg, .bn-drawer, .bn-backdrop { animation: none !important; }
        }
      `}</style>

      {historyOpen && (
        <div className="bn-backdrop fixed inset-0 z-[59]" style={{ background: "rgba(36,31,73,0.35)" }} onClick={closeHistory} />
      )}

      {historyOpen && (
        <div className="bn-drawer fixed inset-y-0 right-0 z-[60] flex w-full max-w-[26.25rem] flex-col bg-white shadow-2xl">
          <div className="flex items-start justify-between gap-3 border-b border-[#F1EEE6] px-6 py-5">
            <div>
              <p className="text-lg font-semibold text-[#241F49]" style={SERIF}>Feedback history</p>
              <p className="mt-0.5 text-xs text-slate-400">
                {history.length} moment{history.length === 1 ? "" : "s"} captured this session
              </p>
            </div>
            <button onClick={closeHistory} aria-label="Close history" className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#F7F5F0] text-slate-500 hover:bg-slate-100">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="flex-1 space-y-2.5 overflow-y-auto px-5 py-4">
            {history.length === 0 ? (
              <p className="px-1 py-6 text-sm italic text-slate-400" style={SERIF}>
                Nothing yet — history fills in as new captures are graded.
              </p>
            ) : (
              history.map((h) => {
                const meta = h.studentState ? PREMIUM_STATE_STYLES[h.studentState] : NEUTRAL_META;
                return (
                  <div key={h.attemptId} className="flex items-start gap-3 rounded-2xl p-3" style={{ background: meta.bg }}>
                    {h.inputType === "audio" ? (
                      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/70">
                        <Mic className="h-4 w-4 text-slate-400" />
                      </div>
                    ) : (
                      <img src={getPracticeAttemptImageUrl(h.attemptId)} alt="capture" className="h-11 w-11 shrink-0 rounded-xl border-2 border-white object-cover" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-bold text-slate-800">{h.label}</span>
                        {h.studentState && <StatePill state={h.studentState} />}
                        <span className="text-[0.6875rem] text-slate-400">{timeAgo(h.capturedAt)}</span>
                      </div>
                      <p className="mt-1 text-xs text-slate-700">{hintLine(h, t)}</p>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}

      {/* Docked launcher — bottom-LEFT, not bottom-right: the global
          Classroom Brain voice assistant (ClassroomBrain.tsx) is always
          docked bottom-right on every page, and its FAB is a lower z-index
          than this one — sharing that corner made it completely unreachable
          on Guided Practice specifically (reported/found 2026-09-22). */}
      <div className="fixed bottom-8 left-8 z-[57]">
        <button
          onClick={openHistory}
          aria-label="Open Classroom Brain feedback history"
          className="relative flex h-14 w-14 items-center justify-center rounded-full shadow-[0_10px_24px_rgba(36,31,73,0.35)] transition-transform hover:scale-105"
          style={{ background: `linear-gradient(135deg, ${INDIGO} 0%, #332B6B 100%)` }}
        >
          {!bubbleOpen && <span className="bn-pulse-ring pointer-events-none absolute -inset-[0.4375rem] rounded-full border-2" style={{ borderColor: GOLD }} />}
          <Brain className="h-6 w-6 text-white" />
          {hasBadge && (
            <span
              className="absolute -right-1 -top-1 flex h-5 min-w-[1.25rem] items-center justify-center rounded-full px-1 text-[0.6875rem] font-bold text-white"
              style={{ background: "#B4432D", boxShadow: "0 0 0 2px #F7F5F0" }}
            >
              {badgeCount}
            </span>
          )}
        </button>
      </div>

      {/* Chat-bubble notification */}
      {bubbleOpen && (
        <div className="bn-bubble fixed bottom-[6.5rem] left-8 z-[58] flex max-h-[29.5rem] w-[23rem] flex-col overflow-hidden rounded-3xl bg-white shadow-[0_20px_46px_rgba(36,31,73,0.28)]">
          <div className="h-1 shrink-0" style={{ background: "#EFE9DC" }}>
            <div className="h-full" style={{ background: GOLD, width: `${barPct}%` }} />
          </div>

          <div className="flex shrink-0 items-center justify-between gap-2 border-b border-[#F1EEE6] px-4 py-3.5">
            <div className="flex min-w-0 items-center gap-2.5">
              <div className="flex h-[1.875rem] w-[1.875rem] shrink-0 items-center justify-center rounded-full" style={{ background: `linear-gradient(135deg, ${INDIGO} 0%, #332B6B 100%)` }}>
                <Brain className="h-3.5 w-3.5 text-white" />
              </div>
              <div className="min-w-0">
                <p className="text-[0.8125rem] font-semibold text-[#241F49]" style={SERIF}>Classroom Brain</p>
                <p className="text-[0.6875rem] text-slate-400">just now</p>
              </div>
            </div>
            <button onClick={dismiss} aria-label="Close" className="flex h-[1.625rem] w-[1.625rem] shrink-0 items-center justify-center rounded-full bg-[#F7F5F0] text-slate-500 hover:bg-slate-100">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>

          <div ref={queueScrollRef} className="flex flex-col gap-2 overflow-y-auto px-3.5 py-3" style={{ maxHeight: "18.5rem" }}>
            {queue.map((m) => {
              const meta = m.studentState ? PREMIUM_STATE_STYLES[m.studentState] : NEUTRAL_META;
              return (
                <div key={m.attemptId} className="bn-msg flex items-start gap-2.5 rounded-2xl p-2.5" style={{ background: meta.bg }}>
                  {m.inputType === "audio" ? (
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white/70">
                      <Mic className="h-3.5 w-3.5 text-slate-400" />
                    </div>
                  ) : (
                    <img src={getPracticeAttemptImageUrl(m.attemptId)} alt="capture" className="h-9 w-9 shrink-0 rounded-xl object-cover" />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-[0.78125rem] font-bold text-slate-800">{m.label}</span>
                      <span className="text-[0.625rem] font-bold uppercase tracking-wide" style={{ color: meta.fg }}>{meta.label}</span>
                    </div>
                    <p className="mt-0.5 text-xs leading-snug text-slate-700">{hintLine(m, t)}</p>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="flex shrink-0 items-center justify-between gap-2 border-t border-[#F1EEE6] px-4 py-2.5">
            <span className="text-[0.6875rem] text-slate-400">Closes on its own, or</span>
            <button onClick={openHistory} className="text-xs font-bold text-[#241F49] underline decoration-1 underline-offset-2">
              Show more
            </button>
          </div>
        </div>
      )}
    </>,
    document.body,
  );
}
