"use client";

/**
 * The premium redesign of Guided Practice — same brief as
 * GuidedPracticeClassicView (same props, renders only, owns no state not
 * described in GuidedPracticeViewProps), so the classic/premium toggle
 * can never affect grading, capture, or any other behavior — only how it
 * looks, plus the one genuinely new capability (batch scan) that has no
 * classic-view equivalent by design. See useDesignVersion for the toggle
 * this is gated behind.
 */

import { useEffect, useState } from "react";
import useSWR from "swr";
import {
  Brain, Sparkles, Check, X, Loader2, AlertTriangle, ScanLine,
  ChevronDown, ChevronUp, ThumbsUp, ThumbsDown, HelpCircle,
  Folder, Plus, Play, Pause, ExternalLink, Copy, Trash2, MessageSquare, Send, BookOpen, Mic,
  Users,
} from "lucide-react";
import { api, getPracticeAttemptImageUrl, getPracticeAttemptAudioUrl } from "@/lib/api";
import type { PracticeQuestion, PracticeAttempt, PracticeStation, BatchScanResponse, CameraMount, PracticeAttemptSummary } from "@/lib/api";
import { CameraSnapButton } from "@/components/practice/CameraSnapButton";
import { BrainNudge } from "@/components/practice/BrainNudge";
import { ClassRadar } from "@/components/practice/ClassRadar";
import { VoiceDictateButton } from "@/components/practice/VoiceDictateButton";
import { VoiceAnswerButton } from "@/components/practice/VoiceAnswerButton";
import { HandDrawnCircle } from "@/components/practice/HandDrawnCircle";
import { cn, fixInfiniteAudioDuration } from "@/lib/utils";
import {
  PREMIUM_STATE_STYLES, VALIDATION_LABELS, AMBIGUOUS_REASON_LABELS, DOMAIN_LABELS,
  COMMON_SUBJECTS, timeAgo,
} from "@/components/practice/guidedPracticeShared";
import type { GuidedPracticeViewProps } from "@/components/practice/GuidedPracticeViewProps";

const SERIF = { fontFamily: "var(--font-fraunces), Georgia, serif" };
const INDIGO = "#241F49";
const GOLD = "#B97F2C";
const GOLD_DEEP = "#8A5D1E";

const ORDINAL_WORDS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"];

/**
 * Turns a spoken reference like "1st", "the second one", "1st, 2nd and 3rd",
 * "all", or "the last one" into 0-based indices into a list of `total`
 * items — voice commands for approve/reject and question-assignment all
 * point at a question by its position in an on-screen list, never by id
 * (the teacher can't see ids, only order), so this is the one place that
 * position language gets turned into something usable. Returns indices in
 * ascending order, deduped, clamped to the real list length.
 */
function resolveOrdinals(which: string, total: number): number[] {
  const s = which.toLowerCase();
  if (total <= 0) return [];
  if (/\ball\b|\bevery\b/.test(s)) return Array.from({ length: total }, (_, i) => i);
  const found = new Set<number>();
  ORDINAL_WORDS.forEach((w, i) => { if (new RegExp(`\\b${w}\\b`).test(s)) found.add(i); });
  for (const m of s.matchAll(/(\d+)(?:st|nd|rd|th)?/g)) {
    const n = parseInt(m[1], 10);
    if (n >= 1) found.add(n - 1);
  }
  if (/\blast\b/.test(s)) found.add(total - 1);
  return Array.from(found).filter((i) => i >= 0 && i < total).sort((a, b) => a - b);
}

// ─── Shared small pieces ────────────────────────────────────────────────────

export function StatePill({ state, className }: { state: keyof typeof PREMIUM_STATE_STYLES; className?: string }) {
  const s = PREMIUM_STATE_STYLES[state];
  return (
    <span
      className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[0.6875rem] font-bold", className)}
      style={{ background: s.bg, color: s.fg }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: s.dot }} />
      {s.label}
    </span>
  );
}

// ─── Batch scan — the new capability: one photo, many students ─────────────

function BatchScanPanel({
  sessionId, approved, onScanned,
}: {
  sessionId: string;
  approved: PracticeQuestion[];
  onScanned: () => void;
}) {
  const [questionId, setQuestionId] = useState("");
  const [scanning, setScanning] = useState(false);
  const [result, setResult] = useState<BatchScanResponse | null>(null);
  const [error, setError] = useState("");

  async function handlePhoto(blob: Blob) {
    if (!questionId) {
      setError("Pick which question this photo is answering first.");
      return;
    }
    setScanning(true);
    setError("");
    setResult(null);
    try {
      const res = await api.batchScanStudents(sessionId, questionId, blob);
      setResult(res);
      onScanned();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't scan this photo — try again.");
    } finally {
      setScanning(false);
    }
  }

  return (
    <div
      className="cc-rise relative overflow-hidden rounded-3xl p-6 sm:p-7"
      style={{ background: "linear-gradient(135deg, #241F49 0%, #332B6B 100%)" }}
    >
      <div className="cc-drift pointer-events-none absolute -right-10 -top-16 h-64 w-64 rounded-full opacity-20 blur-[70px]" style={{ background: GOLD }} />
      <div className="relative flex flex-col gap-4 sm:flex-row sm:items-start">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl" style={{ background: "rgba(255,255,255,0.1)" }}>
          <Users className="h-6 w-6 text-white" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[0.6875rem] font-bold uppercase tracking-wide text-white/60">Scan the whole room at once</p>
          <h2 className="mt-1 text-xl font-semibold text-white" style={SERIF}>
            One photo, every student
          </h2>
          <p className="mt-1.5 text-sm text-white/70 max-w-lg">
            Line up 5-10 notebooks with each student&apos;s name written above their work, take one wide photo, and
            each name is read automatically — a station is created (or matched) per student with their work
            already graded, no typing required.
          </p>

          <div className="mt-4 flex flex-wrap items-center gap-2.5">
            <div className="relative min-w-[13.75rem]">
              <select
                value={questionId}
                onChange={(e) => { setQuestionId(e.target.value); setError(""); }}
                className="w-full appearance-none rounded-xl border border-white/20 bg-white/10 px-3 py-2.5 pr-8 text-sm text-white focus:outline-none focus:ring-2 focus:ring-white/40 [&>option]:text-slate-900"
              >
                <option value="" className="text-slate-900">Which question are they answering?</option>
                {approved.map((q) => (
                  <option key={q.question_id} value={q.question_id} className="text-slate-900">{q.text.slice(0, 60)}</option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-white/60" />
            </div>
            <CameraSnapButton onCapture={handlePhoto} label={scanning ? "Scanning…" : "Take the photo"} size="md" disabled={scanning} wide />
          </div>

          {scanning && (
            <p className="mt-3 flex items-center gap-2 text-sm text-white/80">
              <Loader2 className="h-4 w-4 animate-spin" /> Reading names and cropping each student&apos;s work…
            </p>
          )}

          {error && (
            <div className="mt-3 flex items-start gap-2 rounded-xl border border-red-400/30 bg-red-500/10 px-3.5 py-2.5 text-sm text-red-100">
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" /> {error}
            </div>
          )}

          {result && (
            <div className="mt-4 rounded-2xl border border-white/15 bg-white/8 p-4">
              <p className="text-sm font-semibold text-white">
                Detected {result.detected.length} student{result.detected.length !== 1 ? "s" : ""}
                {result.detected.some((d) => d.is_new_station) && (
                  <span className="font-normal text-white/60">
                    {" "}— {result.detected.filter((d) => d.is_new_station).length} new station{result.detected.filter((d) => d.is_new_station).length !== 1 ? "s" : ""} created
                  </span>
                )}
              </p>
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {result.detected.map((d) => (
                  <span key={d.attempt_id} className="rounded-full bg-white/10 px-3 py-1 text-xs font-medium text-white">
                    {d.name}
                  </span>
                ))}
              </div>
              {result.skipped.length > 0 && (
                <p className="mt-2.5 text-xs text-amber-200">
                  Couldn&apos;t crop a usable photo for: {result.skipped.join(", ")} — worth re-photographing that section closer up.
                </p>
              )}
              <p className="mt-2.5 text-xs text-white/50">Grading is running now — results will appear in the stations below as they finish.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Question review card ───────────────────────────────────────────────────

function PremiumReviewCard({ q, t, onDecide }: {
  q: PracticeQuestion;
  t: (s: string) => string;
  onDecide: (id: string, status: "approved" | "rejected") => void;
}) {
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);

  async function decide(status: "approved" | "rejected") {
    setBusy(status === "approved" ? "approve" : "reject");
    try {
      await onDecide(q.question_id, status);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="cc-rise bg-white rounded-2xl p-5 shadow-[0_4px_14px_rgba(23,22,27,0.05)] space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[0.625rem] font-bold px-2 py-0.5 rounded-full" style={{ background: "#EDEAF9", color: "#453B87" }}>
          {DOMAIN_LABELS[q.answer_domain]}
        </span>
        {q.difficulty && <span className="text-[0.625rem] font-bold px-2 py-0.5 rounded-full bg-slate-100 text-slate-500">{q.difficulty}</span>}
        {q.topic && <span className="text-xs text-slate-400">{t(q.topic)}</span>}
      </div>
      <p className="text-sm font-medium text-slate-800" style={SERIF}>{t(q.text)}</p>

      {q.expected_solution_graph && q.expected_solution_graph.length > 0 && (
        <div className="rounded-xl bg-slate-50 px-3 py-2.5 text-xs text-slate-600">
          <p className="font-semibold text-slate-500 mb-1">Accepted approach{q.expected_solution_graph.length > 1 ? "es" : ""}:</p>
          {q.expected_solution_graph.map((a, i) => (
            <div key={i} className="mb-1">
              {a.label && <span className="font-medium">{a.label}: </span>}
              {a.steps.map((s) => s.step).join(" → ")}
            </div>
          ))}
        </div>
      )}
      {q.known_misconceptions && q.known_misconceptions.length > 0 && (
        <p className="text-xs text-slate-500"><span className="font-semibold">Watching for:</span> {q.known_misconceptions.map((m) => m.description).join("; ")}</p>
      )}

      <div className="flex gap-2 pt-1">
        <button
          onClick={() => decide("approved")}
          disabled={busy !== null}
          className="flex items-center gap-1.5 rounded-xl px-4 py-2 text-sm font-bold text-white transition-colors disabled:opacity-60"
          style={{ background: INDIGO }}
        >
          {busy === "approve" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />} Approve
        </button>
        <button
          onClick={() => decide("rejected")}
          disabled={busy !== null}
          className="flex items-center gap-1.5 rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50 disabled:opacity-60"
        >
          {busy === "reject" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <X className="h-3.5 w-3.5" />} Reject
        </button>
      </div>
    </div>
  );
}

// ─── Pruned-history summary (premium) ───────────────────────────────────────
// The raw timeline above only ever shows the most recent 10 attempts per
// question — the backend prunes anything older, folding it into one of
// these summaries first rather than discarding it outright (see
// PracticeAttemptSummary's own docstring).

function PremiumPrunedHistorySummary({ summaries }: { summaries: PracticeAttemptSummary[] | undefined }) {
  if (!summaries || summaries.length === 0) return null;
  const totalPruned = summaries.reduce((sum, s) => sum + s.attempts_summarized, 0);
  const revisionCount = summaries.filter((s) => s.revision_required).length;

  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 space-y-2">
      <p className="text-[0.6875rem] font-semibold text-amber-800">
        {totalPruned} earlier attempt{totalPruned === 1 ? "" : "s"} summarized
        {revisionCount > 0 && ` — ${revisionCount} batch${revisionCount === 1 ? "" : "es"} suggest revision`}
      </p>
      <div className="space-y-1.5">
        {summaries.map((s) => (
          <div key={s.id} className="flex items-center justify-between gap-2 text-[0.6875rem] text-amber-700">
            <span>
              {s.attempts_summarized} attempts · {premiumFormatDuration(s.first_attempt_at, s.last_attempt_at)}
              {s.solved ? " · solved" : " · not solved"}
              {s.misconception_codes && Object.keys(s.misconception_codes).length > 0 && (
                <> · {Object.entries(s.misconception_codes).map(([code, n]) => `${code}×${n}`).join(", ")}</>
              )}
            </span>
            {s.revision_required && (
              <span className="shrink-0 rounded-full bg-amber-200 px-1.5 py-0.5 font-semibold text-amber-900">revise</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function premiumFormatDuration(fromIso: string, toIso: string): string {
  const ms = new Date(toIso).getTime() - new Date(fromIso).getTime();
  const mins = Math.round(ms / 60000);
  if (mins < 1) return "<1m";
  if (mins < 60) return `${mins}m`;
  return `${Math.round(mins / 60)}h ${mins % 60}m`;
}

// ─── One attempt row (premium) ──────────────────────────────────────────────

function PremiumAttemptRow({ attempt, t, onFeedback }: {
  attempt: PracticeAttempt;
  t: (s: string) => string;
  onFeedback: (attemptId: string, fb: "approve" | "reject") => void;
}) {
  const s = attempt.student_state ? PREMIUM_STATE_STYLES[attempt.student_state] : null;
  return (
    <div className="rounded-xl px-3.5 py-3" style={{ background: s ? s.bg : "#F7F5F0" }}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          {attempt.input_type === "audio" ? (
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/70">
              <Mic className="h-4.5 w-4.5 text-slate-400" />
            </div>
          ) : (
            <img src={getPracticeAttemptImageUrl(attempt.attempt_id)} alt="capture" className="h-11 w-11 rounded-xl object-cover shrink-0" />
          )}
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-xs font-bold text-slate-800">{attempt.student_label || `Attempt #${attempt.attempt_no}`}</span>
              {attempt.student_state && <StatePill state={attempt.student_state} />}
            </div>
            {attempt.status === "processing" && (
              <p className="text-[0.6875rem] text-slate-400 flex items-center gap-1 mt-0.5"><Loader2 className="h-3 w-3 animate-spin" /> Processing…</p>
            )}
            {attempt.status === "complete" && attempt.validation_status && (
              <p className="text-[0.6875rem] text-slate-500 mt-0.5">
                {(attempt.validation_status === "ambiguous" && attempt.validation_reason_code
                  ? AMBIGUOUS_REASON_LABELS[attempt.validation_reason_code] : null) ?? VALIDATION_LABELS[attempt.validation_status]}
                {attempt.recognition_confidence != null && <span className="text-slate-400"> · {Math.round(attempt.recognition_confidence * 100)}% legible</span>}
              </p>
            )}
            {attempt.status === "failed" && (
              <p className="text-[0.6875rem] text-red-500 flex items-center gap-1 mt-0.5"><AlertTriangle className="h-3 w-3" /> Couldn&apos;t process this capture</p>
            )}
          </div>
        </div>
        {attempt.status === "complete" && (
          <div className="flex items-center gap-1 shrink-0">
            <button onClick={() => onFeedback(attempt.attempt_id, "approve")} className={cn("rounded-lg p-1.5 hover:bg-white/70", attempt.teacher_feedback === "approve" ? "text-emerald-600 bg-white/70" : "text-slate-400")}>
              <ThumbsUp className="h-3.5 w-3.5" />
            </button>
            <button onClick={() => onFeedback(attempt.attempt_id, "reject")} className={cn("rounded-lg p-1.5 hover:bg-white/70", attempt.teacher_feedback === "reject" ? "text-red-600 bg-white/70" : "text-slate-400")}>
              <ThumbsDown className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>

      {attempt.hint_text && (
        <div className="mt-2 flex items-start gap-1.5 rounded-xl bg-white/70 px-2.5 py-2 text-xs text-slate-700">
          <HelpCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" style={{ color: GOLD_DEEP }} />
          <span><span className="font-bold" style={{ color: GOLD_DEEP }}>Hint (L{attempt.hint_level}):</span> {t(attempt.hint_text)}</span>
        </div>
      )}

      {attempt.input_type === "audio" && (
        <audio controls src={getPracticeAttemptAudioUrl(attempt.attempt_id)} onLoadedMetadata={(e) => fixInfiniteAudioDuration(e.currentTarget)} className="mt-1.5 h-8 w-full" />
      )}

      {attempt.recognized_steps && attempt.recognized_steps.length > 0 && (
        attempt.input_type === "audio" ? (
          <div className="mt-1.5 rounded-xl bg-white/70 px-2.5 py-2 text-xs text-slate-700">
            <p className="mb-1 text-[0.625rem] font-bold uppercase tracking-wide text-slate-400">What you said (transcribed)</p>
            <p className="leading-relaxed">
              {attempt.recognized_steps.map((s2, i) => (
                <span key={i} className={i === attempt.error_step_index ? "rounded bg-red-100 px-0.5 font-medium text-red-700" : undefined}>{s2.text} </span>
              ))}
            </p>
          </div>
        ) : (
          <details className="mt-1.5" open={attempt.error_step_index != null}>
            <summary className="text-[0.6875rem] text-slate-400 cursor-pointer select-none">What the AI read</summary>
            <ul className="mt-1 space-y-0.5 pl-3 text-[0.6875rem] list-disc">
              {attempt.recognized_steps.map((s2, i) => (
                <li key={i} className={cn(i === attempt.error_step_index ? "rounded bg-red-50 px-1 -ml-1 font-medium text-red-700 marker:text-red-400" : "text-slate-500")}>
                  {s2.text}{i === attempt.error_step_index && <span className="ml-1 text-[0.625rem] font-semibold text-red-500">← here</span>}
                </li>
              ))}
            </ul>
            {attempt.error_step_index != null && attempt.recognized_steps[attempt.error_step_index]?.bbox && (
              <div className="relative mt-2 overflow-hidden rounded-xl">
                <img src={getPracticeAttemptImageUrl(attempt.attempt_id)} alt="capture" className="block h-auto w-full" />
                <HandDrawnCircle bbox={attempt.recognized_steps[attempt.error_step_index].bbox} seed={`${attempt.attempt_id}-${attempt.error_step_index}`} />
              </div>
            )}
          </details>
        )
      )}
    </div>
  );
}

// ─── One station card ────────────────────────────────────────────────────────

function PremiumStationCard({
  station, approvedQuestions, t, onChanged,
}: {
  station: PracticeStation;
  approvedQuestions: PracticeQuestion[];
  t: (s: string) => string;
  onChanged: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [noteDraft, setNoteDraft] = useState(station.teacher_note ?? "");
  const [busy, setBusy] = useState(false);

  const { data, mutate: mutateAttempts } = useSWR(
    expanded ? ["station-attempts", station.station_id] : null,
    () => api.getStationAttempts(station.station_id),
    { refreshInterval: (d) => (d as { attempts: PracticeAttempt[] } | undefined)?.attempts.some((a) => a.status === "processing") ? 3000 : 0 },
  );
  // Consolidated record of whatever's already aged out of the raw
  // timeline above — the backend only keeps the most recent 10 attempts
  // per question as full rows/images (see api.getStationAttemptSummaries).
  const { data: summaryData } = useSWR(
    expanded ? ["station-attempt-summaries", station.station_id] : null,
    () => api.getStationAttemptSummaries(station.station_id),
  );

  const style = station.latest_attempt?.student_state ? PREMIUM_STATE_STYLES[station.latest_attempt.student_state] : null;
  const stationUrl = typeof window !== "undefined" ? `${window.location.origin}/practice-station/${station.station_id}` : "";

  async function toggleCapturing() {
    const startingUp = station.status !== "capturing";
    // Open the tab SYNCHRONOUSLY, before any await — most browsers
    // (including the Pi's kiosk Chromium) only let window.open() bypass
    // the popup blocker when it's called directly inside the click
    // handler; once this function had already awaited the status-update
    // call first, the browser no longer credited it as part of the user
    // gesture and silently blocked the new tab. Confirmed 2026-09-22:
    // "Start" visibly flipped the badge to "Capturing" but never actually
    // opened the station's capture window — this is why. Open a blank tab
    // now (always allowed here, still inside the gesture) and point it at
    // the real URL once the status update actually succeeds.
    const pendingWindow = startingUp ? window.open("", "_blank") : null;
    setBusy(true);
    try {
      await api.updateStation(station.station_id, { status: startingUp ? "capturing" : "idle" });
      onChanged();
      if (pendingWindow) pendingWindow.location.href = stationUrl;
    } catch (err) {
      pendingWindow?.close();
      throw err;
    } finally { setBusy(false); }
  }
  async function reassignQuestion(questionId: string) { await api.updateStation(station.station_id, { active_question_id: questionId }); onChanged(); }
  async function changeInterval(sec: number) { if (sec < 5 || sec > 120) return; await api.updateStation(station.station_id, { capture_interval_sec: sec }); onChanged(); }
  async function changeCameraMount(mount: CameraMount) { if (mount === station.camera_mount) return; await api.updateStation(station.station_id, { camera_mount: mount }); onChanged(); }
  async function sendNote() { setBusy(true); try { await api.updateStation(station.station_id, { teacher_note: noteDraft }); onChanged(); } finally { setBusy(false); } }
  async function remove() { if (!confirm(`Remove station "${station.label}"? Its capture history is kept.`)) return; await api.deleteStation(station.station_id); onChanged(); }
  async function feedback(attemptId: string, fb: "approve" | "reject") { await api.submitAttemptFeedback(attemptId, fb); mutateAttempts(); }

  const attempts = data?.attempts ?? [];

  return (
    <div
      className="cc-rise bg-white rounded-2xl p-4 sm:p-5 shadow-[0_4px_14px_rgba(23,22,27,0.05)] space-y-3"
      style={style ? { boxShadow: `inset 3px 0 0 ${style.dot}, 0 4px 14px rgba(23,22,27,0.05)` } : undefined}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl overflow-hidden" style={{ background: "#EDEAF9" }}>
            {station.latest_attempt ? (
              <img src={getPracticeAttemptImageUrl(station.latest_attempt.attempt_id)} alt="latest capture" className="h-full w-full object-cover" />
            ) : (
              <Folder className="h-5 w-5" style={{ color: "#453B87" }} />
            )}
          </div>
          <div className="min-w-0">
            <p className="text-sm font-bold text-slate-800 truncate" style={SERIF}>{station.label}</p>
            <p className="text-[0.6875rem] text-slate-400 truncate">{station.active_question_text ? t(station.active_question_text) : "No question assigned"}</p>
          </div>
        </div>
        <span
          className="inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-[0.625rem] font-bold"
          style={station.status === "capturing" ? { background: "#E7F1EA", color: "#3E7A57" } : { background: "#F1EFEA", color: "#57534E" }}
        >
          <span className={cn("h-1.5 w-1.5 rounded-full", station.status === "capturing" && "animate-pulse")} style={{ background: station.status === "capturing" ? "#3E7A57" : "#9A968A" }} />
          {station.status === "capturing" ? "Capturing" : "Paused"}
        </span>
      </div>

      {style && <StatePill state={station.latest_attempt!.student_state!} />}
      {style && <span className="ml-1.5 text-[0.6875rem] text-slate-400">last capture {timeAgo(station.last_capture_at)}</span>}

      <div className="flex items-center gap-2 flex-wrap">
        <select
          value={station.active_question_id ?? ""}
          onChange={(e) => reassignQuestion(e.target.value)}
          className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-2.5 py-2 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-300"
        >
          <option value="" disabled>Assign a question…</option>
          {approvedQuestions.map((q) => <option key={q.question_id} value={q.question_id}>{q.text.slice(0, 60)}</option>)}
        </select>
        <button
          onClick={toggleCapturing}
          disabled={busy}
          className="flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-xs font-bold text-white transition-colors disabled:opacity-60"
          style={{ background: station.status === "capturing" ? "#57534E" : INDIGO }}
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : station.status === "capturing" ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
          {station.status === "capturing" ? "Pause" : "Start"}
        </button>
      </div>

      <label className="flex items-center gap-1.5 text-xs text-slate-500">
        Capture every
        <input type="number" min={5} max={120} defaultValue={station.capture_interval_sec} onBlur={(e) => changeInterval(Number(e.target.value))} className="w-14 rounded-lg border border-slate-200 bg-white px-1.5 py-1 text-xs text-center text-slate-800" />
        sec
      </label>

      {/* "Desk" corrects for a camera mounted above the desk looking
          straight down at the notebook (e.g. fixed just below/above a
          laptop) — reliably comes out rotated 90° and mirrored left-right
          relative to the page, so this applies a fixed correction
          server-side before every vision call. */}
      <label className="flex items-center gap-1.5 text-xs text-slate-500" title="How this station's camera is physically positioned">
        Camera
        <select
          value={station.camera_mount}
          onChange={(e) => changeCameraMount(e.target.value as CameraMount)}
          className="rounded-lg border border-slate-200 bg-white px-1.5 py-1 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-400"
        >
          <option value="front">Front-facing</option>
          <option value="desk">Desk (overhead)</option>
        </select>
      </label>

      <div className="flex items-center gap-1.5 flex-wrap">
        <button onClick={() => { navigator.clipboard?.writeText(stationUrl); }} className="flex items-center gap-1 rounded-lg bg-slate-50 px-2.5 py-1.5 text-[0.6875rem] text-slate-500 hover:bg-slate-100">
          <Copy className="h-3 w-3" /> Copy link
        </button>
        <a href={`/practice-station/${station.station_id}`} target="_blank" rel="noreferrer" className="flex items-center gap-1 rounded-lg bg-slate-50 px-2.5 py-1.5 text-[0.6875rem] text-slate-500 hover:bg-slate-100">
          <ExternalLink className="h-3 w-3" /> Open
        </a>
        <button onClick={() => setExpanded((v) => !v)} className="ml-auto flex items-center gap-1 rounded-lg bg-slate-50 px-2.5 py-1.5 text-[0.6875rem] text-slate-500 hover:bg-slate-100">
          Timeline {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        </button>
        <button onClick={remove} title="Delete this station" className="flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-[0.6875rem] text-slate-400 hover:text-red-600 hover:bg-red-50">
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      {expanded && (
        <div className="space-y-2.5 pt-2 border-t border-slate-100">
          <div className="flex items-start gap-2 pt-2.5">
            <MessageSquare className="h-3.5 w-3.5 shrink-0 mt-2 text-slate-400" />
            <input
              type="text" value={noteDraft} onChange={(e) => setNoteDraft(e.target.value)}
              placeholder="Send this student an instruction…"
              className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-2.5 py-2 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-300"
            />
            <VoiceDictateButton onTranscript={(text) => setNoteDraft((prev) => (prev ? `${prev} ${text}` : text))} />
            <button onClick={sendNote} disabled={busy} className="flex items-center justify-center rounded-xl px-3 py-2 text-white disabled:opacity-60" style={{ background: INDIGO }}>
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
            </button>
          </div>
          <PremiumPrunedHistorySummary summaries={summaryData?.summaries} />
          {attempts.length === 0 && <p className="text-xs text-slate-400 text-center py-3">No captures yet from this station.</p>}
          {[...attempts].reverse().map((a) => <PremiumAttemptRow key={a.attempt_id} attempt={a} t={t} onFeedback={feedback} />)}
        </div>
      )}
    </div>
  );
}

// ─── Generate from a typed topic ─────────────────────────────────────────────

function PremiumTopicGenerateForm({ sessionId, onCreated }: { sessionId: string; onCreated: () => void }) {
  const [subject, setSubject] = useState("");
  const [topic, setTopic] = useState("");
  const [count, setCount] = useState(3);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function generate() {
    if (!subject.trim() || !topic.trim()) return;
    setBusy(true); setError("");
    try {
      await api.generatePracticeQuestionsFromTopic(sessionId, subject.trim(), topic.trim(), count);
      setTopic(""); onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't generate questions — try again.");
    } finally { setBusy(false); }
  }

  return (
    <div className="cc-rise bg-white rounded-2xl p-4 sm:p-5 shadow-[0_4px_14px_rgba(23,22,27,0.05)] space-y-2.5">
      <p className="text-xs font-bold text-slate-600 flex items-center gap-1.5">
        <BookOpen className="h-3.5 w-3.5" style={{ color: GOLD_DEEP }} /> Generate from a subject + chapter/topic — no board photo needed
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <input list="common-subjects-premium" value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Subject (e.g. Mathematics)" className="min-w-[10rem] rounded-xl border border-slate-200 bg-white px-2.5 py-2 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-300" />
        <datalist id="common-subjects-premium">{COMMON_SUBJECTS.map((s) => <option key={s} value={s} />)}</datalist>
        {/* max-w caps flex-1's growth — at a wide screen (4K+) an
            uncapped flex-1 input stretched to 2400+px, an absurdly
            oversized empty box relative to the text inside it. Confirmed
            2026-09-22. */}
        <input type="text" value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Chapter / topic (e.g. Trigonometric Identities)" className="min-w-[13.75rem] max-w-2xl flex-1 rounded-xl border border-slate-200 bg-white px-2.5 py-2 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-300" />
        <VoiceDictateButton title="Speak the topic" onTranscript={(text) => setTopic((prev) => (prev ? `${prev} ${text}` : text))} />
        <label className="flex items-center gap-1.5 text-xs text-slate-500">
          <input type="number" min={1} max={10} value={count} onChange={(e) => setCount(Number(e.target.value))} className="w-12 rounded-lg border border-slate-200 bg-white px-1.5 py-1 text-xs text-center text-slate-800" /> questions
        </label>
        <button onClick={generate} disabled={busy || !subject.trim() || !topic.trim()} className="flex items-center gap-1.5 rounded-xl px-4 py-2 text-sm font-bold text-white disabled:opacity-50" style={{ background: INDIGO }}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />} Generate
        </button>
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}

function PremiumNewStationForm({ sessionId, approvedQuestions, onCreated }: { sessionId: string; approvedQuestions: PracticeQuestion[]; onCreated: () => void }) {
  const [label, setLabel] = useState("");
  const [questionId, setQuestionId] = useState("");
  const [interval, setInterval] = useState(10);
  const [busy, setBusy] = useState(false);

  async function create() {
    if (!label.trim()) return;
    setBusy(true);
    try { await api.createStation(sessionId, label.trim(), questionId || undefined, interval); setLabel(""); onCreated(); }
    finally { setBusy(false); }
  }

  return (
    <div className="cc-rise flex flex-wrap items-center gap-2 bg-white rounded-2xl p-4 shadow-[0_4px_14px_rgba(23,22,27,0.05)]">
      {/* max-w caps flex-1's growth at wide screens — see the matching
          comment on the topic-generate form's input above. */}
      <input type="text" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Student / desk name (e.g. Row 2 - Priya)" className="min-w-[11.25rem] max-w-2xl flex-1 rounded-xl border border-slate-200 bg-white px-2.5 py-2 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-300" />
      <VoiceDictateButton title="Speak the student/desk name" onTranscript={(text) => setLabel((prev) => (prev ? `${prev} ${text}` : text))} />
      <select value={questionId} onChange={(e) => setQuestionId(e.target.value)} className="rounded-xl border border-slate-200 bg-white px-2.5 py-2 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-300">
        <option value="">Assign question later</option>
        {approvedQuestions.map((q) => <option key={q.question_id} value={q.question_id}>{q.text.slice(0, 50)}</option>)}
      </select>
      <label className="flex items-center gap-1.5 text-xs text-slate-500">
        every <input type="number" min={5} max={120} value={interval} onChange={(e) => setInterval(Number(e.target.value))} className="w-14 rounded-lg border border-slate-200 bg-white px-1.5 py-1 text-xs text-center text-slate-800" /> sec
      </label>
      <button onClick={create} disabled={busy || !label.trim()} className="flex items-center gap-1.5 rounded-xl px-4 py-2 text-sm font-bold text-white disabled:opacity-50" style={{ background: INDIGO }}>
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />} New station
      </button>
    </div>
  );
}

// ─── Manual capture card ─────────────────────────────────────────────────────

function PremiumPracticeCard({ q, t }: { q: PracticeQuestion; t: (s: string) => string }) {
  const [expanded, setExpanded] = useState(false);
  const [studentLabel, setStudentLabel] = useState("");
  const { data, mutate } = useSWR(
    expanded ? ["question-attempts", q.question_id] : null,
    () => api.getQuestionAttempts(q.question_id),
    { refreshInterval: (d) => (d as { attempts: PracticeAttempt[] } | undefined)?.attempts.some((a) => a.status === "processing") ? 3000 : 0 },
  );

  async function handleCapture(blob: Blob) {
    setExpanded(true);
    try {
      const form = new FormData();
      form.append("image", blob, "capture.jpg");
      if (studentLabel.trim()) form.append("student_label", studentLabel.trim());
      await api.createPracticeAttempt(q.question_id, form);
      await mutate();
    } catch (err) { alert(err instanceof Error ? err.message : "Capture failed"); }
  }
  async function handleVoiceCapture(blob: Blob) {
    setExpanded(true);
    try {
      const form = new FormData();
      form.append("audio", blob, "answer.webm");
      if (studentLabel.trim()) form.append("student_label", studentLabel.trim());
      await api.createPracticeAttempt(q.question_id, form);
      await mutate();
    } catch (err) { alert(err instanceof Error ? err.message : "Capture failed"); }
  }
  async function feedback(attemptId: string, fb: "approve" | "reject") { await api.submitAttemptFeedback(attemptId, fb); mutate(); }

  const attempts = data?.attempts ?? [];

  return (
    <div className="cc-rise bg-white rounded-2xl p-4 sm:p-5 shadow-[0_4px_14px_rgba(23,22,27,0.05)] space-y-3">
      <div>
        <span className="text-[0.625rem] font-bold px-2 py-0.5 rounded-full" style={{ background: "#EDEAF9", color: "#453B87" }}>{DOMAIN_LABELS[q.answer_domain]}</span>
        {q.topic && <span className="ml-2 text-xs text-slate-400">{t(q.topic)}</span>}
        <p className="mt-1.5 text-sm font-medium text-slate-800" style={SERIF}>{t(q.text)}</p>
      </div>
      <div className="flex items-center gap-2">
        <input type="text" value={studentLabel} onChange={(e) => setStudentLabel(e.target.value)} placeholder="Student / desk (optional)" className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-2.5 py-2 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-300" />
        <CameraSnapButton onCapture={handleCapture} />
        <VoiceAnswerButton onCapture={handleVoiceCapture} label="Speak" />
        <button onClick={() => setExpanded((v) => !v)} className="flex items-center gap-1 rounded-xl bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-500 hover:bg-slate-100">
          {attempts.length > 0 ? `${attempts.length} attempt${attempts.length === 1 ? "" : "s"}` : "History"}
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>
      </div>
      {expanded && (
        <div className="space-y-2 pt-1">
          {attempts.length === 0 && <p className="text-xs text-slate-400 text-center py-3">No captures yet for this question.</p>}
          {[...attempts].reverse().map((a) => <PremiumAttemptRow key={a.attempt_id} attempt={a} t={t} onFeedback={feedback} />)}
        </div>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export function GuidedPracticePremiumView(p: GuidedPracticeViewProps) {
  const {
    sessionId, t, generating, genError, handleGenerate, questions, pending, approved,
    decide, stations, mutateStations, showManualCapture, setShowManualCapture, designToggle,
  } = p;

  const needsHelpCount = stations.filter((s) => ["teacher_required", "misconception", "stuck"].includes(s.latest_attempt?.student_state ?? "")).length;
  const solvedCount = stations.filter((s) => s.latest_attempt?.student_state === "solved").length;

  // Voice-triggered station capture start/stop ("start capturing for Aisha" /
  // "stop capturing for station 2") — ClassroomBrain only knows a student
  // name was spoken, not which PracticeStation that maps to, so it dispatches
  // the raw name and this page (which actually has the live station list)
  // resolves it, same DOM-event bridge already used for capture_frame/
  // start_recording on the capture page. Silent no-op when nothing matches
  // (no name said and more than one station, or a name that matches none) —
  // same acceptable-risk tradeoff as reprocess_ocr's page-level handler,
  // since there's no channel back to ClassroomBrain to report a miss.
  useEffect(() => {
    function normalize(s: string) { return s.toLowerCase().replace(/[^a-z0-9 ]/g, "").trim(); }
    async function resolveAndToggle(e: Event, desiredStatus: "capturing" | "idle") {
      const spoken = (e as CustomEvent<{ station?: string }>).detail?.station ?? "";
      const needle = normalize(spoken);
      let match = needle ? stations.find((s) => normalize(s.label).includes(needle)) : undefined;
      if (!match && !needle && stations.length === 1) match = stations[0];
      if (!match) return;
      await api.updateStation(match.station_id, { status: desiredStatus });
      mutateStations();
    }
    const onStart = (e: Event) => resolveAndToggle(e, "capturing");
    const onStop = (e: Event) => resolveAndToggle(e, "idle");
    window.addEventListener("classroom-brain:start_station_capture", onStart);
    window.addEventListener("classroom-brain:stop_station_capture", onStop);
    return () => {
      window.removeEventListener("classroom-brain:start_station_capture", onStart);
      window.removeEventListener("classroom-brain:stop_station_capture", onStop);
    };
  }, [stations, mutateStations]);

  // Voice-triggered "create a station for Ananth" — distinct from the
  // batch-scan "one photo, every student" flow (that's a manual on-screen
  // action for photographing several notebooks at once; this creates ONE
  // named station the normal way, same as the New Station form).
  useEffect(() => {
    async function onCreateStation(e: Event) {
      const station = (e as CustomEvent<{ station?: string }>).detail?.station?.trim();
      if (!station) return;
      await api.createStation(sessionId, station);
      mutateStations();
    }
    window.addEventListener("classroom-brain:create_station", onCreateStation);
    return () => window.removeEventListener("classroom-brain:create_station", onCreateStation);
  }, [sessionId, mutateStations]);

  // Voice-triggered "assign the second question to Aisha" — resolves the
  // station the same way start/stop_station_capture does, and the question
  // by its position in the APPROVED list (the only list a teacher would be
  // pointing at by position — pending questions aren't assignable yet).
  useEffect(() => {
    function normalize(s: string) { return s.toLowerCase().replace(/[^a-z0-9 ]/g, "").trim(); }
    async function onAssign(e: Event) {
      const detail = (e as CustomEvent<{ station?: string; which?: string }>).detail;
      const needle = normalize(detail?.station ?? "");
      const match = needle ? stations.find((s) => normalize(s.label).includes(needle)) : undefined;
      if (!match) return;
      const indices = resolveOrdinals(detail?.which ?? "", approved.length);
      const question = indices.length > 0 ? approved[indices[0]] : undefined;
      if (!question) return;
      await api.updateStation(match.station_id, { active_question_id: question.question_id });
      mutateStations();
    }
    window.addEventListener("classroom-brain:assign_question_to_station", onAssign);
    return () => window.removeEventListener("classroom-brain:assign_question_to_station", onAssign);
  }, [stations, approved, mutateStations]);

  // Voice-triggered "approve the first question" / "approve 1st, 2nd and
  // 3rd" / "approve all" (and reject, same shape) — position is resolved
  // against `pending`, in the exact order the review cards render below,
  // since that's the only ordering a teacher watching the screen can see.
  useEffect(() => {
    async function onDecide(e: Event, status: "approved" | "rejected") {
      const which = (e as CustomEvent<{ which?: string }>).detail?.which ?? "";
      const indices = resolveOrdinals(which, pending.length);
      for (const i of indices) {
        const q = pending[i];
        if (q) await decide(q.question_id, status);
      }
    }
    const onApprove = (e: Event) => onDecide(e, "approved");
    const onReject = (e: Event) => onDecide(e, "rejected");
    window.addEventListener("classroom-brain:approve_question", onApprove);
    window.addEventListener("classroom-brain:reject_question", onReject);
    return () => {
      window.removeEventListener("classroom-brain:approve_question", onApprove);
      window.removeEventListener("classroom-brain:reject_question", onReject);
    };
  }, [pending, decide]);

  return (
    <div className="space-y-7 pb-4">
      <style>{`
        @keyframes cc-rise-kf { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes cc-drift-kf { 0%,100% { transform: scale(1); } 50% { transform: scale(1.15); } }
        .cc-rise { animation: cc-rise-kf 560ms cubic-bezier(0.16,1,0.3,1) both; }
        .cc-drift { animation: cc-drift-kf 8s ease-in-out infinite; }
        @media (prefers-reduced-motion: reduce) { .cc-rise, .cc-drift { animation: none !important; } }
      `}</style>

      {/* Hero */}
      <div className="cc-rise flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl text-white" style={{ background: INDIGO }}>
            <Brain className="h-6 w-6" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold text-slate-900" style={SERIF}>Guided Practice</h1>
            <p className="text-sm text-slate-500 mt-0.5">ThinkStep — a nudge, not the answer, exactly when a student needs one.</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {designToggle}
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-bold text-white transition-all hover:scale-[1.02] disabled:opacity-60"
            style={{ background: `linear-gradient(135deg, ${GOLD}, ${GOLD_DEEP})` }}
          >
            {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {questions.length ? "Generate more" : "Generate questions"}
          </button>
        </div>
      </div>

      {/* At-a-glance stat chips */}
      {stations.length > 0 && (
        <div className="cc-rise grid grid-cols-3 gap-3" style={{ animationDelay: "60ms" }}>
          <div className="bg-white rounded-2xl p-4 shadow-[0_4px_14px_rgba(23,22,27,0.05)]">
            <p className="text-[0.6875rem] font-bold uppercase tracking-wide text-slate-400">Stations</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums" style={{ ...SERIF, color: INDIGO }}>{stations.length}</p>
          </div>
          <div className="bg-white rounded-2xl p-4 shadow-[0_4px_14px_rgba(23,22,27,0.05)]">
            <p className="text-[0.6875rem] font-bold uppercase tracking-wide text-slate-400">Need help now</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums" style={{ ...SERIF, color: needsHelpCount > 0 ? "#B4432D" : INDIGO }}>{needsHelpCount}</p>
          </div>
          <div className="bg-white rounded-2xl p-4 shadow-[0_4px_14px_rgba(23,22,27,0.05)]">
            <p className="text-[0.6875rem] font-bold uppercase tracking-wide text-slate-400">Solved</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums" style={{ ...SERIF, color: "#3E7A57" }}>{solvedCount}</p>
          </div>
        </div>
      )}

      {genError && (
        <div className="cc-rise flex items-center gap-2 rounded-2xl px-4 py-3 text-sm" style={{ background: "#FBEAE6", color: "#B4432D" }}>
          <AlertTriangle className="h-4 w-4 shrink-0" /> {genError}
        </div>
      )}

      <PremiumTopicGenerateForm sessionId={sessionId} onCreated={() => p.mutate()} />

      {questions.length === 0 && (
        <div className="cc-rise bg-white rounded-3xl px-6 py-14 flex flex-col items-center text-center gap-4 shadow-[0_4px_14px_rgba(23,22,27,0.05)]">
          <div className="w-16 h-16 rounded-full flex items-center justify-center" style={{ background: "#EDEAF9" }}>
            <Brain className="h-7 w-7" style={{ color: "#453B87" }} />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-slate-900" style={SERIF}>No guided-practice questions yet</h3>
            <p className="mt-1 text-sm text-slate-500 max-w-sm">
              Generate questions from today&apos;s board content — review and approve them, then students capture their
              notebook work whenever they need help.
            </p>
          </div>
          <button onClick={handleGenerate} disabled={generating} className="inline-flex items-center gap-2 rounded-xl text-white px-5 py-2.5 text-sm font-bold hover:opacity-90 disabled:opacity-60" style={{ background: INDIGO }}>
            {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} Generate questions
          </button>
        </div>
      )}

      {pending.length > 0 && (
        <div className="space-y-2.5">
          <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500 flex items-center gap-1.5">
            <ScanLine className="h-3.5 w-3.5" /> Needs your review ({pending.length})
          </h2>
          <div className="space-y-3">
            {pending.map((q) => <PremiumReviewCard key={q.question_id} q={q} t={t} onDecide={decide} />)}
          </div>
        </div>
      )}

      {approved.length > 0 && <BatchScanPanel sessionId={sessionId} approved={approved} onScanned={() => mutateStations()} />}

      {stations.length > 0 && <ClassRadar sessionId={sessionId} />}

      {stations.length > 0 && <BrainNudge stations={stations} t={t} />}

      {approved.length > 0 && (
        <div className="space-y-2.5">
          <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500 flex items-center gap-1.5">
            <Folder className="h-3.5 w-3.5" /> Student stations ({stations.length})
          </h2>
          <p className="text-xs text-slate-400 -mt-1.5">
            One folder per student or desk — open a station&apos;s link on their device to auto-capture on its own
            interval, or scan the whole room at once above.
          </p>
          <PremiumNewStationForm sessionId={sessionId} approvedQuestions={approved} onCreated={() => mutateStations()} />
          {stations.length > 0 && (
            // A capped-at-2 grid meant each card grew to fill whatever
            // space was left over instead of the grid adding more columns
            // — confirmed 2026-09-22 that each card stretched to 1650+px
            // wide at 4K, a near-empty box. More columns as the screen
            // widens keeps each card a sane, compact size instead.
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
              {stations.map((s) => (
                <PremiumStationCard key={s.station_id} station={s} approvedQuestions={approved} t={t} onChanged={() => mutateStations()} />
              ))}
            </div>
          )}
        </div>
      )}

      {approved.length > 0 && (
        <div className="space-y-2.5">
          <button onClick={() => setShowManualCapture((v) => !v)} className="flex items-center gap-1.5 text-sm font-semibold text-slate-500 hover:text-slate-700">
            {showManualCapture ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            Manual capture (spot-check a single photo without a station)
          </button>
          {showManualCapture && (
            <div className="space-y-3">{approved.map((q) => <PremiumPracticeCard key={q.question_id} q={q} t={t} />)}</div>
          )}
        </div>
      )}
    </div>
  );
}
