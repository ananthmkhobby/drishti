"use client";

// The original Guided Practice page, extracted verbatim (same classNames,
// same structure, zero logic changes) into a props-driven component — the
// guaranteed-safe fallback behind the classic/premium toggle. All
// data-fetching, state and handlers live in the parent page component;
// this file only renders. See useDesignVersion for the toggle this is
// gated behind.

import { useEffect, useState } from "react";
import useSWR from "swr";
import {
  Brain, Sparkles, Check, X, Loader2, AlertTriangle,
  ChevronDown, ChevronUp, ThumbsUp, ThumbsDown, RefreshCw, HelpCircle,
  Folder, Plus, Play, Pause, ExternalLink, Copy, Trash2, MessageSquare, Send, BookOpen, Mic,
} from "lucide-react";
import { api, getPracticeAttemptImageUrl, getPracticeAttemptAudioUrl } from "@/lib/api";
import type { PracticeQuestion, PracticeAttempt, PracticeStation, CameraMount, PracticeAttemptSummary } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { CameraSnapButton } from "@/components/practice/CameraSnapButton";
import { VoiceDictateButton } from "@/components/practice/VoiceDictateButton";
import { VoiceAnswerButton } from "@/components/practice/VoiceAnswerButton";
import { HandDrawnCircle } from "@/components/practice/HandDrawnCircle";
import { cn, fixInfiniteAudioDuration } from "@/lib/utils";
import {
  STATE_STYLES, VALIDATION_LABELS, AMBIGUOUS_REASON_LABELS, DOMAIN_LABELS,
  STATE_PRIORITY, COMMON_SUBJECTS, timeAgo,
} from "@/components/practice/guidedPracticeShared";
import type { GuidedPracticeViewProps } from "@/components/practice/GuidedPracticeViewProps";

const ORDINAL_WORDS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"];

/**
 * Turns a spoken reference like "1st", "the second one", "1st, 2nd and 3rd",
 * "all", or "the last one" into 0-based indices into a list of `total`
 * items — voice commands for approve/reject and question-assignment all
 * point at a question by its position in an on-screen list, never by id
 * (the teacher can't see ids, only order), so this is the one place that
 * position language gets turned into something usable. Returns indices in
 * ascending order, deduped, clamped to the real list length. Mirrors the
 * same helper in GuidedPracticePremiumView.tsx — kept in sync there.
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

// ─── Question review card (pending_review) ──────────────────────────────────

function ReviewCard({ q, t, onDecide }: {
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
    <Card>
      <CardContent className="space-y-3 py-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <Badge className="bg-indigo-50 text-indigo-700 border border-indigo-200">
                {DOMAIN_LABELS[q.answer_domain]}
              </Badge>
              {q.difficulty && (
                <Badge className="bg-slate-100 text-slate-600">{q.difficulty}</Badge>
              )}
              {q.topic && <span className="text-xs text-slate-400">{t(q.topic)}</span>}
            </div>
            <p className="mt-1.5 text-sm font-medium text-slate-800">{t(q.text)}</p>
          </div>
        </div>

        {q.expected_solution_graph && q.expected_solution_graph.length > 0 && (
          <div className="rounded-lg bg-slate-50 border border-slate-200 px-3 py-2 text-xs text-slate-600">
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
          <div className="text-xs text-slate-500">
            <span className="font-semibold">Watching for:</span>{" "}
            {q.known_misconceptions.map((m) => m.description).join("; ")}
          </div>
        )}

        <div className="flex gap-2 pt-1">
          <Button size="sm" loading={busy === "approve"} onClick={() => decide("approved")}>
            <Check className="h-3.5 w-3.5" /> Approve
          </Button>
          <Button size="sm" variant="secondary" loading={busy === "reject"} onClick={() => decide("rejected")}>
            <X className="h-3.5 w-3.5" /> Reject
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ─── One attempt row ─────────────────────────────────────────────────────────

// The raw timeline above only ever shows the most recent 10 attempts per
// question — the backend prunes anything older, folding it into one of
// these summaries first rather than discarding it outright (see
// PracticeAttemptSummary's own docstring). This is the "what happened
// before that" view: how many captures, whether it was ever solved in
// that batch, which misconceptions came up, and whether the batch as a
// whole suggests the student needs another pass at the concept.
function PrunedHistorySummary({ summaries }: { summaries: PracticeAttemptSummary[] | undefined }) {
  if (!summaries || summaries.length === 0) return null;
  const totalPruned = summaries.reduce((sum, s) => sum + s.attempts_summarized, 0);
  const revisionCount = summaries.filter((s) => s.revision_required).length;

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 space-y-2">
      <p className="text-[0.6875rem] font-semibold text-amber-800">
        {totalPruned} earlier attempt{totalPruned === 1 ? "" : "s"} summarized
        {revisionCount > 0 && ` — ${revisionCount} batch${revisionCount === 1 ? "" : "es"} suggest revision`}
      </p>
      <div className="space-y-1.5">
        {summaries.map((s) => (
          <div key={s.id} className="flex items-center justify-between gap-2 text-[0.6875rem] text-amber-700">
            <span>
              {s.attempts_summarized} attempts · {formatDuration(s.first_attempt_at, s.last_attempt_at)}
              {s.solved ? " · solved" : " · not solved"}
              {s.misconception_codes && Object.keys(s.misconception_codes).length > 0 && (
                <> · {Object.entries(s.misconception_codes).map(([code, n]) => `${code}×${n}`).join(", ")}</>
              )}
            </span>
            {s.revision_required && (
              <span className="shrink-0 rounded-full bg-amber-200 px-1.5 py-0.5 font-semibold text-amber-900">
                revise
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function formatDuration(fromIso: string, toIso: string): string {
  const ms = new Date(toIso).getTime() - new Date(fromIso).getTime();
  const mins = Math.round(ms / 60000);
  if (mins < 1) return "<1m";
  if (mins < 60) return `${mins}m`;
  return `${Math.round(mins / 60)}h ${mins % 60}m`;
}

function AttemptRow({ attempt, t, onFeedback }: {
  attempt: PracticeAttempt;
  t: (s: string) => string;
  onFeedback: (attemptId: string, fb: "approve" | "reject") => void;
}) {
  const state = attempt.student_state ? STATE_STYLES[attempt.student_state] : null;

  return (
    <div className={cn("rounded-lg border px-3 py-2.5", state ? state.bg : "bg-white border-slate-200")}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          {attempt.input_type === "audio" ? (
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-md border border-slate-200 bg-slate-50">
              <Mic className="h-5 w-5 text-slate-400" />
            </div>
          ) : (
            <img
              src={getPracticeAttemptImageUrl(attempt.attempt_id)}
              alt="capture"
              className="h-12 w-12 rounded-md object-cover border border-slate-200 shrink-0"
            />
          )}
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-xs font-semibold text-slate-700">
                {attempt.student_label || `Attempt #${attempt.attempt_no}`}
              </span>
              {state && (
                <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[0.625rem] font-semibold", state.text)}>
                  <span className={cn("h-1.5 w-1.5 rounded-full", state.dot)} />
                  {state.label}
                </span>
              )}
            </div>
            {attempt.status === "processing" && (
              <p className="text-[0.6875rem] text-slate-400 flex items-center gap-1 mt-0.5">
                <Loader2 className="h-3 w-3 animate-spin" /> Processing…
              </p>
            )}
            {attempt.status === "complete" && attempt.validation_status && (
              <p className="text-[0.6875rem] text-slate-500 mt-0.5">
                {(attempt.validation_status === "ambiguous" && attempt.validation_reason_code
                  ? AMBIGUOUS_REASON_LABELS[attempt.validation_reason_code]
                  : null) ?? VALIDATION_LABELS[attempt.validation_status]}
                {attempt.recognition_confidence != null && (
                  <span className="text-slate-400"> · {Math.round(attempt.recognition_confidence * 100)}% legible</span>
                )}
              </p>
            )}
            {attempt.status === "failed" && (
              <p className="text-[0.6875rem] text-red-500 flex items-center gap-1 mt-0.5">
                <AlertTriangle className="h-3 w-3" /> Couldn&apos;t process this capture
              </p>
            )}
          </div>
        </div>

        {attempt.status === "complete" && (
          <div className="flex items-center gap-1 shrink-0">
            <button
              title="Mark AI call correct"
              onClick={() => onFeedback(attempt.attempt_id, "approve")}
              className={cn(
                "rounded-md p-1 hover:bg-white/70",
                attempt.teacher_feedback === "approve" ? "text-emerald-600 bg-white/70" : "text-slate-400"
              )}
            >
              <ThumbsUp className="h-3.5 w-3.5" />
            </button>
            <button
              title="Mark AI call wrong"
              onClick={() => onFeedback(attempt.attempt_id, "reject")}
              className={cn(
                "rounded-md p-1 hover:bg-white/70",
                attempt.teacher_feedback === "reject" ? "text-red-600 bg-white/70" : "text-slate-400"
              )}
            >
              <ThumbsDown className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>

      {attempt.hint_text && (
        <div className="mt-2 flex items-start gap-1.5 rounded-md bg-white/70 border border-white px-2.5 py-1.5 text-xs text-slate-700">
          <HelpCircle className="h-3.5 w-3.5 shrink-0 mt-0.5 text-indigo-500" />
          <span>
            <span className="font-semibold text-indigo-700">Hint (L{attempt.hint_level}):</span> {t(attempt.hint_text)}
          </span>
        </div>
      )}

      {attempt.input_type === "audio" && (
        <audio
          controls
          src={getPracticeAttemptAudioUrl(attempt.attempt_id)}
          onLoadedMetadata={(e) => fixInfiniteAudioDuration(e.currentTarget)}
          className="mt-1.5 h-8 w-full"
        />
      )}

      {attempt.recognized_steps && attempt.recognized_steps.length > 0 && (
        attempt.input_type === "audio" ? (
          // Flowing text, not a bulleted list — a transcribed answer reads
          // as prose, same visual register as the hint box above it. The
          // problem portion (if any) highlights inline instead of getting
          // its own bullet, so this still pinpoints the error without
          // breaking up the sentence.
          <div className="mt-1.5 rounded-md bg-white/70 border border-white px-2.5 py-1.5 text-xs text-slate-700">
            <p className="mb-1 text-[0.625rem] font-semibold uppercase tracking-wide text-slate-400">What you said (transcribed)</p>
            <p className="leading-relaxed">
              {attempt.recognized_steps.map((s, i) => (
                <span
                  key={i}
                  className={i === attempt.error_step_index ? "rounded bg-red-100 px-0.5 font-medium text-red-700" : undefined}
                >
                  {s.text}{" "}
                </span>
              ))}
            </p>
          </div>
        ) : (
          <details className="mt-1.5" open={attempt.error_step_index != null}>
            <summary className="text-[0.6875rem] text-slate-400 cursor-pointer select-none">What the AI read</summary>
            <ul className="mt-1 space-y-0.5 pl-3 text-[0.6875rem] list-disc">
              {attempt.recognized_steps.map((s, i) => (
                <li
                  key={i}
                  className={cn(
                    i === attempt.error_step_index
                      ? "rounded bg-red-50 px-1 -ml-1 font-medium text-red-700 marker:text-red-400"
                      : "text-slate-500"
                  )}
                >
                  {s.text}
                  {i === attempt.error_step_index && (
                    <span className="ml-1 text-[0.625rem] font-semibold text-red-500">← here</span>
                  )}
                </li>
              ))}
            </ul>
            {attempt.error_step_index != null && attempt.recognized_steps[attempt.error_step_index]?.bbox && (
              <div className="relative mt-2 overflow-hidden rounded-lg border border-slate-200">
                <img src={getPracticeAttemptImageUrl(attempt.attempt_id)} alt="capture" className="block h-auto w-full" />
                <HandDrawnCircle
                  bbox={attempt.recognized_steps[attempt.error_step_index].bbox}
                  seed={`${attempt.attempt_id}-${attempt.error_step_index}`}
                />
              </div>
            )}
          </details>
        )
      )}
    </div>
  );
}

// ─── Triage summary: every station's current state + hint, most urgent first ─

function TriageSummary({ stations, t }: { stations: PracticeStation[]; t: (s: string) => string }) {
  const withAttempts = stations.filter((s) => s.latest_attempt);
  if (withAttempts.length === 0) return null;

  const sorted = [...withAttempts].sort((a, b) => {
    const stateA = a.latest_attempt!.student_state;
    const stateB = b.latest_attempt!.student_state;
    const pa = stateA ? STATE_PRIORITY[stateA] : 6;
    const pb = stateB ? STATE_PRIORITY[stateB] : 6;
    if (pa !== pb) return pa - pb;
    // Tie-break: most recently captured first within the same urgency level.
    return new Date(b.last_capture_at ?? 0).getTime() - new Date(a.last_capture_at ?? 0).getTime();
  });

  const needsHelpCount = sorted.filter((s) => {
    const st = s.latest_attempt!.student_state;
    return st === "teacher_required" || st === "misconception" || st === "stuck";
  }).length;

  return (
    <Card>
      <CardContent className="space-y-3 py-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="flex items-center gap-1.5 text-sm font-semibold text-slate-600">
            <AlertTriangle className="h-3.5 w-3.5" /> Who needs help — sorted by urgency
          </h2>
          {needsHelpCount > 0 && (
            <span className="shrink-0 rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-700">
              {needsHelpCount} need{needsHelpCount === 1 ? "s" : ""} attention
            </span>
          )}
        </div>
        <div className="space-y-2">
          {sorted.map((s) => {
            const attempt = s.latest_attempt!;
            const state = attempt.student_state ? STATE_STYLES[attempt.student_state] : null;
            return (
              <div
                key={s.station_id}
                className={cn("flex items-start gap-3 rounded-lg border p-2.5", state ? state.bg : "border-slate-200")}
              >
                <img
                  src={getPracticeAttemptImageUrl(attempt.attempt_id)}
                  alt="latest capture"
                  className="h-10 w-10 shrink-0 rounded-lg border border-white object-cover"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-slate-800">{s.label}</span>
                    {state && (
                      <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[0.625rem] font-semibold", state.text, state.bg)}>
                        <span className={cn("h-1.5 w-1.5 rounded-full", state.dot)} />
                        {state.label}
                      </span>
                    )}
                    <span className="text-[0.6875rem] text-slate-400">last capture {timeAgo(s.last_capture_at)}</span>
                  </div>
                  {attempt.hint_text ? (
                    <p className="mt-1 text-xs text-slate-700">
                      <span className="font-semibold text-indigo-700">Hint (L{attempt.hint_level}):</span> {t(attempt.hint_text)}
                    </p>
                  ) : attempt.student_state === "progressing" ? (
                    <p className="mt-1 text-xs text-slate-400">On the right track — no hint needed.</p>
                  ) : (
                    <p className="mt-1 text-xs text-slate-400">No hint yet.</p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

function StationCard({
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
    {
      refreshInterval: (d) => {
        const list = d as { attempts: PracticeAttempt[] } | undefined;
        return list?.attempts.some((a) => a.status === "processing") ? 3000 : 0;
      },
    }
  );
  // Consolidated record of whatever's already aged out of the raw
  // timeline above — the backend only keeps the most recent 10 attempts
  // per question as full rows/images (see api.getStationAttemptSummaries).
  const { data: summaryData } = useSWR(
    expanded ? ["station-attempt-summaries", station.station_id] : null,
    () => api.getStationAttemptSummaries(station.station_id),
  );

  const state = station.latest_attempt?.student_state ? STATE_STYLES[station.latest_attempt.student_state] : null;
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
    //
    // Starting (not pausing) opens the station's own device page — the
    // capture page itself still needs one more tap ("Start camera": a real
    // getUserMedia permission prompt can't fire without that user gesture
    // on whichever device is actually doing the capturing) — but it
    // arrives already primed to start the auto-capture loop the instant
    // that permission is granted.
    const pendingWindow = startingUp ? window.open("", "_blank") : null;
    setBusy(true);
    try {
      await api.updateStation(station.station_id, { status: startingUp ? "capturing" : "idle" });
      onChanged();
      if (pendingWindow) pendingWindow.location.href = stationUrl;
    } catch (err) {
      pendingWindow?.close();
      throw err;
    } finally {
      setBusy(false);
    }
  }

  async function reassignQuestion(questionId: string) {
    await api.updateStation(station.station_id, { active_question_id: questionId });
    onChanged();
  }

  async function changeInterval(sec: number) {
    if (sec < 5 || sec > 120) return;
    await api.updateStation(station.station_id, { capture_interval_sec: sec });
    onChanged();
  }

  async function changeCameraMount(mount: CameraMount) {
    if (mount === station.camera_mount) return;
    await api.updateStation(station.station_id, { camera_mount: mount });
    onChanged();
  }

  async function sendNote() {
    setBusy(true);
    try {
      await api.updateStation(station.station_id, { teacher_note: noteDraft });
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!confirm(`Remove station "${station.label}"? Its capture history is kept.`)) return;
    await api.deleteStation(station.station_id);
    onChanged();
  }

  async function feedback(attemptId: string, fb: "approve" | "reject") {
    await api.submitAttemptFeedback(attemptId, fb);
    mutateAttempts();
  }

  const attempts = data?.attempts ?? [];

  return (
    <Card>
      <CardContent className="space-y-3 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-slate-100 overflow-hidden">
              {station.latest_attempt ? (
                <img
                  src={getPracticeAttemptImageUrl(station.latest_attempt.attempt_id)}
                  alt="latest capture"
                  className="h-full w-full object-cover"
                />
              ) : (
                <Folder className="h-5 w-5 text-slate-400" />
              )}
            </div>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-slate-800 truncate">{station.label}</p>
              <p className="text-xs text-slate-400 truncate">{station.active_question_text ? t(station.active_question_text) : "No question assigned"}</p>
            </div>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            <span className={cn(
              "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[0.625rem] font-semibold",
              station.status === "capturing" ? "bg-emerald-50 text-emerald-700 border border-emerald-200" : "bg-slate-100 text-slate-500"
            )}>
              <span className={cn("h-1.5 w-1.5 rounded-full", station.status === "capturing" ? "bg-emerald-500 animate-pulse" : "bg-slate-400")} />
              {station.status === "capturing" ? "Capturing" : "Paused"}
            </span>
          </div>
        </div>

        {state && (
          <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[0.625rem] font-semibold border", state.text, state.bg)}>
            <span className={cn("h-1.5 w-1.5 rounded-full", state.dot)} />
            {state.label} · last capture {timeAgo(station.last_capture_at)}
          </span>
        )}

        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={station.active_question_id ?? ""}
            onChange={(e) => reassignQuestion(e.target.value)}
            className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-400"
          >
            <option value="" disabled>Assign a question…</option>
            {approvedQuestions.map((q) => (
              <option key={q.question_id} value={q.question_id}>{q.text.slice(0, 60)}</option>
            ))}
          </select>
          <Button size="sm" loading={busy} variant={station.status === "capturing" ? "secondary" : "primary"} onClick={toggleCapturing}>
            {station.status === "capturing" ? <><Pause className="h-3.5 w-3.5" /> Pause</> : <><Play className="h-3.5 w-3.5" /> Start</>}
          </Button>
        </div>

        <label className="flex items-center gap-1.5 text-xs text-slate-500">
          Capture every
          <input
            type="number" min={5} max={120}
            defaultValue={station.capture_interval_sec}
            onBlur={(e) => changeInterval(Number(e.target.value))}
            className="w-14 rounded-lg border border-slate-200 bg-white px-1.5 py-1 text-xs text-center text-slate-800"
          />
          sec
        </label>

        {/* "Desk" corrects for a camera mounted above the desk looking
            straight down at the notebook (e.g. fixed just below/above a
            laptop) — that framing reliably comes out rotated 90° and
            mirrored left-right relative to the page, so this applies a
            fixed correction server-side before every vision call rather
            than the student fighting a physically fixed mount each time. */}
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

        <div className="flex items-center gap-2">
          <button
            onClick={() => { navigator.clipboard?.writeText(stationUrl); }}
            className="flex items-center gap-1 rounded-md bg-slate-50 border border-slate-200 px-2 py-1 text-[0.6875rem] text-slate-500 hover:bg-slate-100"
          >
            <Copy className="h-3 w-3" /> Copy device link
          </button>
          <a
            href={`/practice-station/${station.station_id}`}
            target="_blank" rel="noreferrer"
            className="flex items-center gap-1 rounded-md bg-slate-50 border border-slate-200 px-2 py-1 text-[0.6875rem] text-slate-500 hover:bg-slate-100"
          >
            <ExternalLink className="h-3 w-3" /> Open
          </a>
          <button
            onClick={() => setExpanded((v) => !v)}
            className="ml-auto flex items-center gap-1 rounded-md bg-slate-50 border border-slate-200 px-2 py-1 text-[0.6875rem] text-slate-500 hover:bg-slate-100"
          >
            Timeline {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </button>
          <button
            onClick={remove}
            title="Delete this station"
            className="flex items-center gap-1 rounded-md px-2 py-1 text-[0.6875rem] text-slate-400 hover:text-red-600 hover:bg-red-50"
          >
            <Trash2 className="h-3.5 w-3.5" /> Delete
          </button>
        </div>

        {expanded && (
          <div className="space-y-3 pt-1 border-t border-slate-100">
            <div className="flex items-start gap-2 pt-3">
              <MessageSquare className="h-3.5 w-3.5 shrink-0 mt-1.5 text-slate-400" />
              <input
                type="text"
                value={noteDraft}
                onChange={(e) => setNoteDraft(e.target.value)}
                placeholder="Send this student an instruction…"
                className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-400"
              />
              <VoiceDictateButton onTranscript={(text) => setNoteDraft((prev) => (prev ? `${prev} ${text}` : text))} />
              <Button size="sm" variant="secondary" loading={busy} onClick={sendNote}>
                <Send className="h-3 w-3" />
              </Button>
            </div>

            <PrunedHistorySummary summaries={summaryData?.summaries} />

            {attempts.length === 0 && (
              <p className="text-xs text-slate-400 text-center py-3">No captures yet from this station.</p>
            )}
            {[...attempts].reverse().map((a) => (
              <AttemptRow key={a.attempt_id} attempt={a} t={t} onFeedback={feedback} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ─── Generate from a typed subject + chapter/topic (no board photo needed) ──

function TopicGenerateForm({ sessionId, onCreated }: { sessionId: string; onCreated: () => void }) {
  const [subject, setSubject] = useState("");
  const [topic, setTopic] = useState("");
  const [count, setCount] = useState(3);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function generate() {
    if (!subject.trim() || !topic.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api.generatePracticeQuestionsFromTopic(sessionId, subject.trim(), topic.trim(), count);
      setTopic("");
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't generate questions — try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardContent className="space-y-2 py-4">
        <p className="text-xs font-semibold text-slate-600 flex items-center gap-1.5">
          <BookOpen className="h-3.5 w-3.5" /> Generate from a subject + chapter/topic — no board photo needed
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <input
            list="common-subjects"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="Subject (e.g. Mathematics)"
            className="min-w-[10rem] rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-400"
          />
          <datalist id="common-subjects">
            {COMMON_SUBJECTS.map((s) => <option key={s} value={s} />)}
          </datalist>
          <input
            type="text"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="Chapter / topic (e.g. Trigonometric Identities)"
            // max-w caps flex-1's growth — at a wide screen (4K+) an
            // uncapped flex-1 input stretched to 2400+px, an absurdly
            // oversized empty box relative to the text inside it.
            className="min-w-[13.75rem] max-w-2xl flex-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-400"
          />
          <VoiceDictateButton title="Speak the topic" onTranscript={(text) => setTopic((prev) => (prev ? `${prev} ${text}` : text))} />
          <label className="flex items-center gap-1.5 text-xs text-slate-500">
            <input
              type="number" min={1} max={10} value={count}
              onChange={(e) => setCount(Number(e.target.value))}
              className="w-12 rounded-lg border border-slate-200 bg-white px-1.5 py-1 text-xs text-center text-slate-800"
            />
            questions
          </label>
          <Button size="sm" loading={busy} onClick={generate} disabled={!subject.trim() || !topic.trim()}>
            <Sparkles className="h-3.5 w-3.5" /> Generate
          </Button>
        </div>
        {error && <p className="text-xs text-red-600">{error}</p>}
      </CardContent>
    </Card>
  );
}

function NewStationForm({ sessionId, approvedQuestions, onCreated }: {
  sessionId: string;
  approvedQuestions: PracticeQuestion[];
  onCreated: () => void;
}) {
  const [label, setLabel] = useState("");
  const [questionId, setQuestionId] = useState("");
  const [interval, setInterval] = useState(10);
  const [busy, setBusy] = useState(false);

  async function create() {
    if (!label.trim()) return;
    setBusy(true);
    try {
      await api.createStation(sessionId, label.trim(), questionId || undefined, interval);
      setLabel("");
      onCreated();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-2 py-3">
        <input
          type="text"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="Student / desk name (e.g. Row 2 - Priya)"
          // max-w caps flex-1's growth at wide screens — see the matching
          // comment on the topic-generate form's input above.
          className="min-w-[11.25rem] max-w-2xl flex-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />
        <VoiceDictateButton title="Speak the student/desk name" onTranscript={(text) => setLabel((prev) => (prev ? `${prev} ${text}` : text))} />
        <select
          value={questionId}
          onChange={(e) => setQuestionId(e.target.value)}
          className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-400"
        >
          <option value="">Assign question later</option>
          {approvedQuestions.map((q) => (
            <option key={q.question_id} value={q.question_id}>{q.text.slice(0, 50)}</option>
          ))}
        </select>
        <label className="flex items-center gap-1.5 text-xs text-slate-500">
          every
          <input
            type="number" min={5} max={120} value={interval}
            onChange={(e) => setInterval(Number(e.target.value))}
            className="w-14 rounded-lg border border-slate-200 bg-white px-1.5 py-1 text-xs text-center text-slate-800"
          />
          sec
        </label>
        <Button size="sm" loading={busy} onClick={create} disabled={!label.trim()}>
          <Plus className="h-3.5 w-3.5" /> New station
        </Button>
      </CardContent>
    </Card>
  );
}

// ─── Approved question card: capture + attempt history ─────────────────────

function PracticeCard({ q, t }: { q: PracticeQuestion; t: (s: string) => string }) {
  const [expanded, setExpanded] = useState(false);
  const [studentLabel, setStudentLabel] = useState("");

  const { data, mutate } = useSWR(
    expanded ? ["question-attempts", q.question_id] : null,
    () => api.getQuestionAttempts(q.question_id),
    {
      refreshInterval: (d) => {
        const list = d as { attempts: PracticeAttempt[] } | undefined;
        return list?.attempts.some((a) => a.status === "processing") ? 3000 : 0;
      },
    }
  );

  async function handleCapture(blob: Blob) {
    setExpanded(true);
    try {
      const form = new FormData();
      form.append("image", blob, "capture.jpg");
      if (studentLabel.trim()) form.append("student_label", studentLabel.trim());
      await api.createPracticeAttempt(q.question_id, form);
      await mutate();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Capture failed");
    }
  }

  async function handleVoiceCapture(blob: Blob) {
    setExpanded(true);
    try {
      console.log("[VoiceAnswer] uploading blob: %d bytes, type=%s", blob.size, blob.type);
      const form = new FormData();
      form.append("audio", blob, "answer.webm");
      if (studentLabel.trim()) form.append("student_label", studentLabel.trim());
      const created = await api.createPracticeAttempt(q.question_id, form);
      console.log("[VoiceAnswer] server accepted attempt:", created);
      await mutate();
    } catch (err) {
      console.error("[VoiceAnswer] upload failed:", err);
      alert(err instanceof Error ? err.message : "Capture failed");
    }
  }

  async function feedback(attemptId: string, fb: "approve" | "reject") {
    await api.submitAttemptFeedback(attemptId, fb);
    mutate();
  }

  const attempts = data?.attempts ?? [];

  return (
    <Card>
      <CardContent className="space-y-3 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <Badge className="bg-indigo-50 text-indigo-700 border border-indigo-200">
                {DOMAIN_LABELS[q.answer_domain]}
              </Badge>
              {q.topic && <span className="text-xs text-slate-400">{t(q.topic)}</span>}
            </div>
            <p className="text-sm font-medium text-slate-800">{t(q.text)}</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <input
            type="text"
            value={studentLabel}
            onChange={(e) => setStudentLabel(e.target.value)}
            placeholder="Student / desk (optional)"
            className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-400"
          />
          <CameraSnapButton onCapture={handleCapture} />
          <VoiceAnswerButton onCapture={handleVoiceCapture} label="Speak" />
          <Button
            size="sm" variant="ghost"
            onClick={() => setExpanded((v) => !v)}
          >
            {attempts.length > 0 ? `${attempts.length} attempt${attempts.length === 1 ? "" : "s"}` : "History"}
            {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </Button>
        </div>

        {expanded && (
          <div className="space-y-2 pt-1">
            {attempts.length === 0 && (
              <p className="text-xs text-slate-400 text-center py-3">No captures yet for this question.</p>
            )}
            {[...attempts].reverse().map((a) => (
              <AttemptRow key={a.attempt_id} attempt={a} t={t} onFeedback={feedback} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export function GuidedPracticeClassicView(p: GuidedPracticeViewProps) {
  const {
    sessionId, t, generating, genError, handleGenerate, questions, pending, approved,
    decide, stations, mutateStations, showManualCapture, setShowManualCapture, designToggle,
  } = p;

  // Voice-triggered station capture start/stop ("start capturing for Aisha" /
  // "stop capturing for station 2") — mirrors GuidedPracticePremiumView's
  // identical listener; kept in sync there. ClassroomBrain only knows a
  // student name was spoken, not which PracticeStation that maps to, so it
  // dispatches the raw name and this page (which actually has the live
  // station list) resolves it.
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

  // Voice-triggered "create a station for Ananth".
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

  // Voice-triggered "assign the second question to Aisha".
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
  // 3rd" / "approve all" (and reject, same shape).
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
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 text-white">
            <Brain className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-900">Guided Practice</h1>
            <p className="text-xs text-slate-500 mt-0.5">
              ThinkStep — students solve in their notebook, capture when they need help, get a nudge not the answer.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {designToggle}
          <Button size="sm" loading={generating} onClick={handleGenerate}>
            <Sparkles className="h-4 w-4" /> {questions.length ? "Generate more" : "Generate questions"}
          </Button>
        </div>
      </div>

      {genError && (
        <div className="rounded-lg bg-red-50 border border-red-100 px-4 py-3 text-sm text-red-700">{genError}</div>
      )}

      <TopicGenerateForm sessionId={sessionId} onCreated={() => p.mutate()} />

      {questions.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center gap-4 py-16 text-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-indigo-50">
              <Brain className="h-8 w-8 text-indigo-400" />
            </div>
            <div>
              <p className="font-semibold text-slate-700">No guided-practice questions yet</p>
              <p className="text-sm text-slate-400 mt-1 max-w-sm">
                Generate questions from today&apos;s board content — review and approve them, then students capture
                their notebook work whenever they need help.
              </p>
            </div>
            <Button size="sm" loading={generating} onClick={handleGenerate}>
              <Sparkles className="h-4 w-4" /> Generate questions
            </Button>
          </CardContent>
        </Card>
      )}

      {pending.length > 0 && (
        <div className="space-y-2">
          <h2 className="text-sm font-semibold text-slate-600 flex items-center gap-1.5">
            <RefreshCw className="h-3.5 w-3.5" /> Needs your review ({pending.length})
          </h2>
          <div className="space-y-3">
            {pending.map((q) => <ReviewCard key={q.question_id} q={q} t={t} onDecide={decide} />)}
          </div>
        </div>
      )}

      {stations.length > 0 && <TriageSummary stations={stations} t={t} />}

      {approved.length > 0 && (
        <div className="space-y-2">
          <h2 className="text-sm font-semibold text-slate-600 flex items-center gap-1.5">
            <Folder className="h-3.5 w-3.5" /> Student stations ({stations.length})
          </h2>
          <p className="text-xs text-slate-400 -mt-1">
            One folder per student or desk. Open a station&apos;s link on their device — it auto-captures on its own
            interval, no manual per-student tap needed. Click a folder to see their progress or send an instruction.
          </p>
          <NewStationForm sessionId={sessionId} approvedQuestions={approved} onCreated={() => mutateStations()} />
          {stations.length > 0 && (
            // More columns as the screen widens, same fix as the premium
            // view — see its matching comment.
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
              {stations.map((s) => (
                <StationCard
                  key={s.station_id} station={s} approvedQuestions={approved} t={t}
                  onChanged={() => mutateStations()}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {approved.length > 0 && (
        <div className="space-y-2">
          <button
            onClick={() => setShowManualCapture((v) => !v)}
            className="flex items-center gap-1.5 text-sm font-semibold text-slate-500 hover:text-slate-700"
          >
            {showManualCapture ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            Manual capture (spot-check a single photo without a station)
          </button>
          {showManualCapture && (
            <div className="space-y-3">
              {approved.map((q) => <PracticeCard key={q.question_id} q={q} t={t} />)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
