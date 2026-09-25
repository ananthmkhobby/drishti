"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { CheckCircle2, Loader2, Camera, Pause, Play, AlertTriangle, MessageSquare, Sparkles, Minimize2, Maximize2, ArrowLeft, Brain, X, Mic, Image as ImageIcon, Trash2, Send, GraduationCap, Volume2 } from "lucide-react";
import { api, getPracticeAttemptAudioUrl, getPracticeAttemptImageUrl } from "@/lib/api";
import type { PracticeStation, PracticeAttempt, StudentState, AttemptStatus } from "@/lib/api";
import { cn, fixInfiniteAudioDuration } from "@/lib/utils";
import { captureSharpestFrame } from "@/lib/imageQuality";
import { VoiceAnswerButton, type VoiceAnswerButtonHandle } from "@/components/practice/VoiceAnswerButton";
import { VoiceDictateButton } from "@/components/practice/VoiceDictateButton";
import { HandDrawnCircle } from "@/components/practice/HandDrawnCircle";
import { useVoiceConversation } from "@/hooks/useVoiceConversation";

const JPEG_QUALITY = 0.85;
const BUBBLE_AUTO_DISMISS_MS = 30_000;
const BUBBLE_TICK_MS = 200;

// REVERTED (2026-09-25): a digital center-crop was added here to fight a
// hypothesized "background gets captured" cause, but real testing showed
// it was actively harmful — trimming a fixed 18% off every edge means a
// large textbook page can no longer fit in frame at all ("not able to
// cover even half of the page"), which is a much worse problem than the
// one it was meant to solve. Capturing the FULL frame (no crop) and
// leaving framing entirely to the student, guided by the grid overlay
// below, is the safer default — a wrong guess about camera field-of-view
// behavior shouldn't cost the student page coverage. Kept as a plain
// pass-through so both capture call sites (snapAndUpload,
// captureTutorFrame) don't need their own inline drawImage call.
function cropAndDrawFrame(targetCanvas: HTMLCanvasElement, sourceVideo: HTMLVideoElement) {
  targetCanvas.getContext("2d")!.drawImage(sourceVideo, 0, 0);
}

// focusMode is part of the Image Capture API extensions to
// MediaStreamTrack — not in TS's bundled DOM lib typings, so read/written
// through this local shape rather than fighting the built-in
// MediaTrackCapabilities/MediaTrackConstraints types with `as any` at
// every call site.
type FocusCapabilities = { focusMode?: string[] };
type FocusConstraintSet = { focusMode?: string };

// Requesting focusMode in the initial getUserMedia call (see startCamera)
// isn't honored by every browser — applyConstraints() on the already-
// acquired track is the more reliable path, and letting getCapabilities()
// confirm support first means we never fight a camera that can't do this
// at all. A fixed-focus webcam (common, cheap classroom hardware) simply
// has no lens motor to drive — no constraint can add that capability, so
// this is a best-effort improvement, not a guarantee, and fails silently.
function applyContinuousAutofocus(stream: MediaStream) {
  const track = stream.getVideoTracks()[0];
  if (!track) return;
  try {
    const capabilities = track.getCapabilities?.() as (MediaTrackCapabilities & FocusCapabilities) | undefined;
    if (capabilities?.focusMode?.includes("continuous")) {
      track.applyConstraints({ advanced: [{ focusMode: "continuous" } as FocusConstraintSet] } as MediaTrackConstraints).catch(() => {});
    }
  } catch {
    // getCapabilities isn't implemented in every browser — fine, the
    // `focusMode: { ideal: "continuous" }` request already made in the
    // initial getUserMedia call is the fallback for those.
  }
}

// Resolves once `video` has actually decoded a real frame (readyState >=
// HAVE_CURRENT_DATA with real dimensions), not just once playback has
// started — see captureTutorFrame for why this distinction matters.
// Bounded wait: a camera that genuinely never produces a frame (hardware
// fault, permission revoked mid-stream) shouldn't hang a capture forever.
function waitForVideoFrame(video: HTMLVideoElement, timeoutMs = 1500): Promise<boolean> {
  const isReady = () => video.readyState >= 2 && video.videoWidth > 0;
  if (isReady()) return Promise.resolve(true);
  return new Promise((resolve) => {
    let settled = false;
    const finish = (ok: boolean) => {
      if (settled) return;
      settled = true;
      video.removeEventListener("loadeddata", onLoadedData);
      clearTimeout(timer);
      resolve(ok);
    };
    const onLoadedData = () => finish(isReady());
    video.addEventListener("loadeddata", onLoadedData);
    const timer = setTimeout(() => finish(isReady()), timeoutMs);
  });
}

// Student-facing copy — deliberately friendlier/less technical than the
// teacher dashboard's VALIDATION_LABELS (e.g. no raw "conceptual_misconception"
// jargon shown to the student themselves).
const STATE_COPY: Record<StudentState, { message: string; color: string; bg: string; border: string }> = {
  solved:           { message: "🎉 You solved it — great work!", color: "text-emerald-800", bg: "bg-emerald-100", border: "border-emerald-300" },
  progressing:      { message: "You're on the right track — keep going!", color: "text-emerald-700", bg: "bg-emerald-50", border: "border-emerald-200" },
  uncertain:        { message: "Keep going — double-check this step.",     color: "text-amber-700",   bg: "bg-amber-50",   border: "border-amber-200" },
  stuck:            { message: "Here's a hint to help you continue:",      color: "text-amber-800",   bg: "bg-amber-50",   border: "border-amber-300" },
  misconception:    { message: "Here's a hint to help you continue:",      color: "text-orange-800",  bg: "bg-orange-50",  border: "border-orange-300" },
  ambiguous:        { message: "Couldn't read that clearly — try another photo with better lighting.", color: "text-slate-600", bg: "bg-slate-50", border: "border-slate-200" },
  teacher_required:  { message: "Let's get your teacher to take a look at this one.", color: "text-red-700", bg: "bg-red-50", border: "border-red-300" },
};

// The "ambiguous" bucket covers several distinct reasons — a blurry photo
// and a clearly-legible photo of the WRONG page both land there, but need
// completely different messages (bug caught 2026-09-10: both were shown as
// "couldn't read that clearly", which is actively misleading for the
// off-topic case — the photo was perfectly readable, it just wasn't the
// assigned question).
const AMBIGUOUS_REASON_COPY: Record<string, string> = {
  off_topic_content: "That doesn't look like this question — make sure your notebook is open to the right page.",
  blank_page: "This page looks blank — write your attempt first, then capture.",
  capture_illegible: "Couldn't read that clearly — try another photo with better lighting or hold the camera steadier.",
  recognition_unavailable: "Couldn't check this photo right now — try capturing again in a moment.",
};

// Same reason codes, worded for a spoken answer instead of a photograph —
// "make sure your notebook is open to the right page" makes no sense when
// nothing was photographed.
const AMBIGUOUS_REASON_COPY_AUDIO: Record<string, string> = {
  off_topic_content: "That doesn't sound like an answer to this question — try again, answering what's actually asked.",
  blank_page: "Didn't catch an answer in that — say your answer out loud, then record.",
  capture_illegible: "Couldn't make that out clearly — try recording again somewhere quieter.",
  recognition_unavailable: "Couldn't check this recording right now — try again in a moment.",
};

type CamState = "idle" | "requesting" | "active" | "error";
// "photo": the original flow — camera + auto-capture loop, for handwritten/
// drawn work. "voice": speak the answer instead — for theory/conceptual
// questions with nothing to photograph. "tutor": a live voice+vision
// conversation with the AI Tutor (Learning mode) — unlike the other two,
// runs the camera AND a voice conversation at once rather than one action
// at a time; see switchMode. A station only ever runs one mode at a time;
// switching stops whichever loop was running.
type CaptureMode = "photo" | "voice" | "tutor";

// One turn in a Learning-mode AI Tutor conversation — kept separately from
// ChatEvent below (the existing "ask the Brain a text question" chat) since
// this is a genuinely different feature (voice, vision-grounded, its own
// backend endpoint) that happens to share a similar transcript-list look.
type TutorEvent = { seq: number; role: "student" | "tutor"; text: string };

// One running conversation with the Classroom Brain: a graded result
// arriving is one turn, a question the student types (or speaks) is
// another, its reply a third — all in one chronological chat, not a
// results feed with a bolted-on Q&A box.
type ChatEvent =
  | { seq: number; kind: "attempt"; attempt: PracticeAttempt }
  | { seq: number; kind: "user"; text: string }
  | { seq: number; kind: "brain"; text: string; declined: boolean }
  | { seq: number; kind: "typing" };

function resultCopyFor(attempt: PracticeAttempt) {
  const copy = attempt.student_state ? STATE_COPY[attempt.student_state] : null;
  if (!copy) return null;
  const reasonCopy = attempt.input_type === "audio" ? AMBIGUOUS_REASON_COPY_AUDIO : AMBIGUOUS_REASON_COPY;
  const message = attempt.validation_reason_code
    ? reasonCopy[attempt.validation_reason_code] ?? copy.message
    : copy.message;
  return { ...copy, message };
}

// One result card — the AI's read on a single capture (state message, hint,
// what it recognized, the photo/audio itself). Shared by the ephemeral
// Brain bubble (a fresh result, just in) and the full history drawer (every
// kept result) so the same rich rendering — pinpointed error step, audio
// player, recognized-steps transcript — doesn't have to be written twice.
function AttemptResultCard({
  attempt, onDelete, deleting,
}: {
  attempt: PracticeAttempt;
  onDelete?: (attemptId: string) => void;
  deleting?: boolean;
}) {
  const copy = resultCopyFor(attempt);
  if (!copy) return null;
  // See STATE_COPY/hint_level comment history: the pinpoint circle/highlight
  // only appears from hint_level 2 onward — the first miss gets the gentle
  // nudge, not a diagram of exactly where they went wrong.
  const showPinpoint = attempt.hint_level != null && attempt.hint_level >= 2;
  const errorStep = attempt.error_step_index != null ? attempt.recognized_steps?.[attempt.error_step_index] : null;

  // A confirmed pinpoint (hint_level 2+, a real bbox) is the whole point of
  // this card — leads with the marked-up photo itself, the way a teacher
  // hands work back with the mistake already circled, rather than making
  // the student read a state message and a recognized-text list first and
  // find a small thumbnail at the very end. Reported 2026-09-24 as reading
  // "not intuitive" — this was exactly why: the one thing that answers
  // "where did I go wrong" was the least prominent thing on the card.
  const hasPinpointPhoto = showPinpoint && attempt.input_type !== "audio" && !!errorStep?.bbox;

  return (
    <div className={cn("rounded-xl border px-3 py-2.5", copy.bg, copy.border)}>
      <div className="flex items-center justify-between gap-2 mb-1">
        <p className={cn("text-xs font-semibold flex items-center gap-1.5", copy.color)}>
          {attempt.student_state === "progressing" ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}
          Attempt #{attempt.attempt_no}
        </p>
        <div className="flex items-center gap-1.5 shrink-0">
          {attempt.captured_at && (
            <p className="text-[0.625rem] text-slate-500">
              {new Date(attempt.captured_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </p>
          )}
          {onDelete && (
            <button
              onClick={() => onDelete(attempt.attempt_id)}
              disabled={deleting}
              title="Delete this attempt permanently"
              className="text-slate-400 hover:text-red-600 disabled:opacity-40"
            >
              <Trash2 className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>

      {hasPinpointPhoto && (
        <div className="mb-2">
          <p className="mb-1 flex items-center gap-1 text-[0.6875rem] font-bold uppercase tracking-wide text-red-600">
            <span className="flex h-3.5 w-3.5 items-center justify-center rounded-full bg-red-100 text-[0.5625rem]">●</span>
            Here&apos;s where to look
          </p>
          <div className="relative overflow-hidden rounded-lg border-2 border-red-200 shadow-sm">
            <img src={getPracticeAttemptImageUrl(attempt.attempt_id)} alt="your capture, with the mistake marked" className="block h-auto w-full" />
            <HandDrawnCircle bbox={errorStep!.bbox} seed={`${attempt.attempt_id}-${attempt.error_step_index}`} />
          </div>
        </div>
      )}

      <p className={cn("text-sm font-medium", copy.color)}>{copy.message}</p>
      {attempt.hint_text && <p className="text-sm text-slate-700 mt-1">{attempt.hint_text}</p>}
      {attempt.recognized_steps && attempt.recognized_steps.length > 0 && (
        <div className="mt-2 rounded-lg bg-white/70 border border-white px-2.5 py-2">
          <p className="text-[0.625rem] font-semibold uppercase tracking-wide text-slate-400 mb-1">
            {attempt.input_type === "audio" ? "What you said" : "What you wrote"}
          </p>
          {attempt.input_type === "audio" ? (
            <p className="text-xs leading-relaxed text-slate-600">
              {attempt.recognized_steps.map((s, i) => (
                <span
                  key={i}
                  className={showPinpoint && i === attempt.error_step_index ? "rounded bg-red-100 px-1 font-medium text-red-700" : undefined}
                >
                  {s.text}{" "}
                </span>
              ))}
            </p>
          ) : (
            <ul className="space-y-0.5 text-xs">
              {attempt.recognized_steps.map((s, i) => (
                <li
                  key={i}
                  className={cn(
                    showPinpoint && i === attempt.error_step_index
                      ? "rounded bg-red-100 px-1.5 py-0.5 font-medium text-red-700"
                      : "text-slate-500 px-1.5"
                  )}
                >
                  {showPinpoint && i === attempt.error_step_index && "→ "}{s.text}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {attempt.input_type === "audio" ? (
        <audio
          controls
          src={getPracticeAttemptAudioUrl(attempt.attempt_id)}
          onLoadedMetadata={(e) => fixInfiniteAudioDuration(e.currentTarget)}
          className="mt-2 h-7 w-full"
        />
      ) : !hasPinpointPhoto ? (
        // Plain capture, no confirmed pinpoint yet (first miss, or nothing
        // wrong to circle) — still shown, just without the callout treatment
        // above since there's nothing specific to point at.
        <div className="relative mt-2 overflow-hidden rounded-lg border border-white">
          <img src={getPracticeAttemptImageUrl(attempt.attempt_id)} alt="your capture" className="block h-auto w-full" />
        </div>
      ) : null}
    </div>
  );
}

export default function StationCapturePage({ params }: { params: Promise<{ stationId: string }> }) {
  const { stationId } = use(params);

  const [station, setStation] = useState<PracticeStation | null>(null);
  const [attempts, setAttempts] = useState<PracticeAttempt[]>([]);
  const [mode, setMode] = useState<CaptureMode>("photo");
  const [voiceError, setVoiceError] = useState("");
  const [camState, setCamState] = useState<CamState>("idle");
  const [errorMsg, setErrorMsg] = useState("");
  const [countdown, setCountdown] = useState<number | null>(null);
  const [capturing, setCapturing] = useState(false); // local intent, synced with station.status
  const [uploading, setUploading] = useState(false);
  // Result panel for the "generate notes"/"generate quiz" voice commands
  // (station-scoped analogs of a session's generate_notes/generate_quiz —
  // see ClassroomBrain.tsx's onPracticeStationPage branch). null when
  // nothing's been generated yet or the panel's been dismissed.
  const [stationGen, setStationGen] = useState<
    { kind: "notes"; loading: boolean; notes?: string }
    | { kind: "quiz"; loading: boolean; questions?: string[] }
    | null
  >(null);
  // Shrinks the camera preview to a small corner thumbnail so the question
  // and latest recommendation stay visible/readable — the camera stream and
  // auto-capture loop keep running unaffected either way, this only changes
  // layout. Added because once the camera was active there was no way to
  // see the question/hint without it, and closing the tab/window (the only
  // other escape) killed the whole capture session.
  const [cameraMinimized, setCameraMinimized] = useState(false);
  // A single overlay showing only the LATEST result turned out too easy to
  // miss (reported 2026-09-11) — first fixed with an always-docked side
  // panel, which then ate real width next to the camera the whole lesson.
  // Redesigned (2026-09-21) into a Brain-branded bubble, then redesigned
  // again (2026-09-22) into one real chat: a fresh result still pops the
  // panel open and auto-closes after BUBBLE_AUTO_DISMISS_MS if untouched,
  // but the panel is now the SAME place the student can type a question —
  // interacting with it (typing, sending, or opening it manually) cancels
  // the auto-close, since a real chat window doesn't vanish mid-conversation.
  // `events` is the whole running transcript for this browser tab (results
  // + Q&A, oldest to newest) — nothing is deleted from it except by the
  // explicit delete controls, which also apply to the underlying attempt.
  const [panelOpen, setPanelOpen] = useState(false);
  const [autoDismissActive, setAutoDismissActive] = useState(false);
  const [lastSeenCount, setLastSeenCount] = useState(0);
  const [barPct, setBarPct] = useState(100);
  const [events, setEvents] = useState<ChatEvent[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [sending, setSending] = useState(false);
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);
  // Learning-mode AI Tutor conversation — separate from `events`/panelOpen
  // above (the results chat); this is its own always-visible panel while
  // mode === "tutor", not a popover.
  const [tutorEvents, setTutorEvents] = useState<TutorEvent[]>([]);
  const [tutorSpeaking, setTutorSpeaking] = useState(false);
  // Set once auto-relisten has been stopped after repeated "didn't catch
  // that" turns in a row (background noise repeatedly tripping the VAD,
  // not the student actually talking) — reported 2026-09-24 as becoming
  // annoying. Requires an explicit tap to resume rather than nagging
  // forever; see tutorConsecutiveMissesRef below.
  const [tutorAwaitingResume, setTutorAwaitingResume] = useState(false);
  // A visible "yes, this is what I'm seeing" thumbnail of the last captured
  // frame — reported 2026-09-24 that students couldn't tell whether their
  // notebook/textbook was actually being captured at all. Object URL, kept
  // in sync with tutorFrameRef (the actual Blob sent on the next turn).
  const [tutorThumbUrl, setTutorThumbUrl] = useState<string | null>(null);
  const [tutorLastCapturedAt, setTutorLastCapturedAt] = useState<number | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const captureTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const countdownTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const capturingRef = useRef(false);
  const seenAttemptIds = useRef<Set<string>>(new Set());
  const everMounted = useRef(false);
  const bubbleTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const seqRef = useRef(0);
  const nextSeq = useCallback(() => ++seqRef.current, []);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Latest client-captured frame for the tutor — refreshed every ~6s while
  // tutor mode is open (local canvas capture, no upload), only actually
  // sent to the backend when a real conversational turn happens. See
  // captureTutorFrame/switchMode below.
  const tutorFrameRef = useRef<Blob | null>(null);
  const tutorCaptureTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const tutorConsecutiveMissesRef = useRef(0);
  const tutorSeqRef = useRef(0);
  const nextTutorSeq = useCallback(() => ++tutorSeqRef.current, []);
  const tutorAudioRef = useRef<HTMLAudioElement | null>(null);
  // Lets a voice command ("record my answer") trigger the one VoiceAnswerButton
  // this page renders (voice mode only) — see its own file for why this is
  // an imperative ref rather than the button listening for the event itself.
  const voiceAnswerButtonRef = useRef<VoiceAnswerButtonHandle>(null);
  // Closes a real race in speakTutorReply's "stop any existing audio first"
  // guard: that check runs BEFORE the `await api.streamSpeechToAudio(text)`
  // call, so two calls that both start while tutorAudioRef is still null
  // (nothing playing YET) can both pass it, then both later set
  // tutorAudioRef and both call .play() — two genuinely overlapping Audio
  // elements, which is exactly what "dual voice" sounds like. A monotonic
  // generation counter closes this regardless of what triggers the second
  // call: whichever call's generation is stale by the time its network
  // request resolves discards itself instead of playing.
  const tutorSpeakGenerationRef = useRef(0);
  // Mirrors `mode` for the async playback/listening callbacks below, which
  // resolve well after a render and need to know if the student has since
  // switched away from tutor mode (a stale closure over `mode` would keep
  // relistening/auto-advancing after they've left).
  const modeRef = useRef<CaptureMode>(mode);
  modeRef.current = mode;

  // Mirrors whether the MOST RECENT attempt is still being graded — read by
  // snapAndUpload (below) to hold off on the next auto-capture until Gates
  // B/C's vision call actually finishes, rather than firing on a fixed
  // interval regardless of how far behind processing has fallen. A ref
  // (not state) because it's read from inside an already-running
  // setInterval closure, which would otherwise see a stale value; a plain
  // object (not just a boolean) so the guard can self-heal from a
  // genuinely stuck "processing" row instead of blocking captures forever
  // (see snapAndUpload — reported 2026-09-24: a short interval outrunning
  // vision-call latency was producing wildly inconsistent grading on
  // back-to-back captures of the same page, exactly as a teacher
  // hypothesized from real classroom use).
  const pendingAttemptRef = useRef<{ status: AttemptStatus; capturedAtMs: number } | null>(null);

  // ── Poll station + its attempt timeline ──────────────────────────────────
  const refresh = useCallback(async () => {
    try {
      const [s, a] = await Promise.all([
        api.getStation(stationId),
        api.getStationAttempts(stationId),
      ]);
      setStation(s);
      setAttempts(a.attempts);
      const last = a.attempts.length > 0 ? a.attempts[a.attempts.length - 1] : null;
      pendingAttemptRef.current = last
        ? { status: last.status, capturedAtMs: last.captured_at ? new Date(last.captured_at).getTime() : Date.now() }
        : null;
    } catch {
      // transient network error — next poll retries
    }
  }, [stationId]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh]);

  // The Back link's onClick (below) only fires on an in-app navigation —
  // a back-swipe, a killed tab, a crashed browser, or the device just
  // losing wifi all skip it entirely, leaving the station stuck showing
  // "Capturing"/"Pause" on the teacher dashboard forever (reported
  // 2026-09-22) even though nothing is actually capturing anymore.
  // `pagehide` is the reliable "this page is going away" signal (fires on
  // all of the above except a hard process kill, and — unlike
  // `beforeunload` — is dependable on mobile Safari/Chrome too); `fetch`
  // with `keepalive: true` lets the request outlive the page teardown,
  // which a normal fetch can't. This is a best-effort client-side signal,
  // not the only fix — see the backend's own staleness check for what
  // catches an outright device power-loss.
  useEffect(() => {
    function markIdleOnExit() {
      if (!capturingRef.current) return;
      const base = process.env.NEXT_PUBLIC_API_URL ??
        (process.env.NEXT_PUBLIC_USE_PROXY === "true" ? "/api/backend" : "http://localhost:8000/v1");
      fetch(`${base}/practice-stations/${stationId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "idle" }),
        keepalive: true,
      }).catch(() => {});
    }
    window.addEventListener("pagehide", markIdleOnExit);
    return () => window.removeEventListener("pagehide", markIdleOnExit);
  }, [stationId]);

  // ── Camera lifecycle ──────────────────────────────────────────────────────
  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  const startCamera = useCallback(async () => {
    setCamState("requesting");
    setErrorMsg("");
    try {
      // frameRate: same fix as CameraCapture.tsx — an unconstrained live
      // preview decodes at the camera's max fps (often 30) continuously,
      // real sustained CPU load on the Pi that a still-photo capture never
      // benefits from. `ideal` so a camera that can't hit 15 just falls
      // back to its own default instead of failing to start.
      // focusMode "continuous": keeps refocusing as the notebook/textbook
      // gets repositioned or tilted under the camera — a soft/out-of-focus
      // capture is one of the more common reasons the vision call
      // misreads or outright rejects a photo. `ideal` (not a bare/required
      // value) so a camera without autofocus hardware just ignores it
      // instead of getUserMedia throwing OverconstrainedError.
      //
      // width/height ideal bumped from 1920x1080 (reported 2026-09-24: a
      // notebook/textbook held at a normal ~30cm reading distance wasn't
      // being read reliably, only right up close against the lens). The
      // reason: backend encode_for_vision only upscales below 1024px and
      // only downscales above 2048px on the longer side — a 1920x1080
      // capture already sits inside that window, so it reaches the vision
      // model basically as-is. Whatever fraction of that frame the page
      // actually occupies (most of it, once the camera's own field of
      // view and typical working distance are accounted for) is ALL the
      // resolution the text ever gets — there's no headroom to lose. A
      // higher native capture gives encode_for_vision genuine extra detail
      // to downscale FROM instead of just passing through unchanged, which
      // matters most exactly when the page doesn't fill the whole frame.
      // Still `ideal`, not `exact` — a camera that can't do 4K just falls
      // back to its own next-best resolution instead of failing to start.
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: "environment", width: { ideal: 3840 }, height: { ideal: 2160 }, frameRate: { ideal: 15 },
          ...({ focusMode: { ideal: "continuous" } } as MediaTrackConstraints),
        },
        audio: false,
      });
      streamRef.current = stream;
      applyContinuousAutofocus(stream);
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => {});
      }
      setCamState("active");
    } catch (err) {
      setCamState("error");
      setErrorMsg(err instanceof Error ? err.message : "Couldn't access the camera.");
    }
  }, []);

  useEffect(() => () => { stopStream(); }, [stopStream]);

  // ── Snap + upload one frame ───────────────────────────────────────────────
  // `fromAutoLoop`: only the periodic timer (startLoop, below) passes this —
  // a manual shutter tap always fires immediately, since that's a
  // deliberate "grade this now" action, not a fixed cadence outrunning
  // Gates B/C's own latency the way the auto-loop can.
  const snapAndUpload = useCallback(async (fromAutoLoop = false) => {
    const video = videoRef.current;
    if (!video || camState !== "active") return;

    // Wait for the PREVIOUS auto-capture to finish being graded before
    // starting the next one — a short capture_interval_sec (e.g. 5s) can
    // easily be shorter than a real gpt-4o vision call, and letting
    // several captures' grading run concurrently on the Pi's single
    // process was reported (2026-09-24) to produce wildly inconsistent
    // results on back-to-back photos of the very same page — exactly what
    // a teacher hypothesized from watching it happen live. Self-healing:
    // only holds off while the pending attempt is BOTH "processing" and
    // recent, so one genuinely stuck row can't block captures forever.
    if (fromAutoLoop) {
      const pending = pendingAttemptRef.current;
      if (pending && pending.status === "processing" && Date.now() - pending.capturedAtMs < 45_000) {
        return;
      }
    }

    // Auto-capture has no human in the loop to notice and retake a blurry
    // shot — the timer can fire mid-motion (a notebook being repositioned,
    // a hand still moving). Burst a few frames a beat apart and keep the
    // sharpest instead of blindly grabbing whatever's on screen (see
    // src/lib/imageQuality.ts — this pipeline's OCR was found returning
    // "not legible" on genuinely motion-blurred auto-captures, 2026-09-15).
    let bestCanvas: HTMLCanvasElement;
    try {
      bestCanvas = await captureSharpestFrame(video, cropAndDrawFrame);
    } catch {
      return; // transient burst-capture failure — next interval tick retries
    }

    bestCanvas.toBlob(async (blob) => {
      if (!blob) return;
      setUploading(true);
      try {
        const form = new FormData();
        form.append("image", blob, "capture.jpg");
        await api.createStationAttempt(stationId, form);
        await refresh();
      } catch {
        // one failed capture shouldn't stop the loop — next interval retries
      } finally {
        setUploading(false);
      }
    }, "image/jpeg", JPEG_QUALITY);
  }, [camState, stationId, refresh]);

  // ── Start / stop the periodic auto-capture loop ──────────────────────────
  const stopLoop = useCallback(() => {
    if (captureTimerRef.current) { clearInterval(captureTimerRef.current); captureTimerRef.current = null; }
    if (countdownTimerRef.current) { clearInterval(countdownTimerRef.current); countdownTimerRef.current = null; }
    setCountdown(null);
  }, []);

  const startLoop = useCallback((intervalSec: number) => {
    stopLoop();
    let secsLeft = intervalSec;
    setCountdown(secsLeft);
    countdownTimerRef.current = setInterval(() => {
      secsLeft -= 1;
      if (secsLeft <= 0) secsLeft = intervalSec;
      setCountdown(secsLeft);
    }, 1000);
    captureTimerRef.current = setInterval(() => {
      snapAndUpload(true);
    }, intervalSec * 1000);
  }, [stopLoop, snapAndUpload]);

  async function handleToggleCapturing() {
    if (!station) return;
    if (!capturing) {
      if (camState !== "active") await startCamera();
      setCapturing(true);
      capturingRef.current = true;
      await api.updateStation(stationId, { status: "capturing" });
      startLoop(station.capture_interval_sec);
    } else {
      setCapturing(false);
      capturingRef.current = false;
      stopLoop();
      await api.updateStation(stationId, { status: "idle" });
    }
  }

  // ── AI Tutor (Learning mode) — live voice+vision conversation ────────────
  // Lightweight, local-only capture: keeps tutorFrameRef fresh on a timer
  // (see switchMode) but never uploads on its own — only a real turn (see
  // handleTutorRecording) actually sends a frame to the backend. Same
  // burst-for-sharpness technique as snapAndUpload, just without the
  // upload half.
  const captureTutorFrame = useCallback(async () => {
    const video = videoRef.current;
    // Checked against the STREAM ref, not the `camState` React state — this
    // is called once immediately after `await startCamera()` in switchMode,
    // before that render (and its fresh `camState`) has landed, so a state
    // check here would stale-read "idle" and silently no-op the very first
    // capture even though the stream is already live.
    if (!video || !streamRef.current) return;
    // `video.play()` resolving only means playback STARTED, not that the
    // element has actually decoded a real frame yet — capturing before
    // then draws whatever the canvas's default/cleared state is instead
    // of real camera content. Confirmed via a real captured frame
    // (reported 2026-09-24 as "the tutor says the image is blank" with a
    // notebook genuinely in view): 640x480, every single pixel identically
    // the same value — a blank canvas, not a photo. Most likely to bite
    // the very first capture right after entering tutor mode (see
    // switchMode), before the camera has had time to produce anything.
    const ready = await waitForVideoFrame(video);
    if (!ready) return; // camera never produced a real frame in time — next periodic tick retries
    try {
      const canvas = await captureSharpestFrame(video, cropAndDrawFrame);
      canvas.toBlob((blob) => {
        if (!blob) return;
        tutorFrameRef.current = blob;
        setTutorThumbUrl((prev) => { if (prev) URL.revokeObjectURL(prev); return URL.createObjectURL(blob); });
        setTutorLastCapturedAt(Date.now());
      }, "image/jpeg", JPEG_QUALITY);
    } catch {
      // transient burst-capture failure — next periodic tick retries
    }
  }, []);

  // Speaks the tutor's reply, then relistens once playback ends — same
  // "stream TTS, play, react to onended" shape as the Teaching page's
  // speak() function. Forward-references `voiceConvo` (declared further
  // below, right after handleTutorRecording) — safe because this function's
  // BODY only ever runs after a real reply comes back, well after that
  // declaration has executed for this render; only the dependency array
  // can't mention it before it exists.
  const speakTutorReply = useCallback(async (text: string) => {
    // Never let two replies play at once. Under most circumstances only
    // one is ever in flight, but this is a cheap, always-correct guard
    // against the exact symptom reported as "dual voice" (2026-09-24) —
    // whatever unusual timing caused two Audio elements to exist
    // simultaneously, stopping the old one before starting a new one makes
    // that structurally impossible rather than trying to prove it can't happen.
    const myGeneration = ++tutorSpeakGenerationRef.current;
    if (tutorAudioRef.current) {
      tutorAudioRef.current.pause();
      tutorAudioRef.current = null;
    }
    setTutorSpeaking(true);
    try {
      const audio = await api.streamSpeechToAudio(text);
      // A NEWER call started (and possibly already started playing) while
      // this one was still fetching/decoding — the guard above only
      // catches a second call that arrives AFTER this one has already set
      // tutorAudioRef, not one that starts concurrently while it's still
      // null. Discard this one rather than play it on top of the newer one.
      if (tutorSpeakGenerationRef.current !== myGeneration) {
        audio.pause();
        URL.revokeObjectURL(audio.src);
        return;
      }
      const url = audio.src;
      tutorAudioRef.current = audio;
      // Guards against `finish` running twice for the same playback —
      // `onended` and `onerror` are both wired to it, and some browsers do
      // fire a late/trailing MSE error even after a stream has already
      // reached "ended". A double-fire would schedule two separate
      // relisten timeouts, which useVoiceConversation's own re-entrancy
      // guard now protects against structurally, but there's no reason to
      // even attempt it twice.
      let alreadyFinished = false;
      const finish = () => {
        if (alreadyFinished) return;
        alreadyFinished = true;
        URL.revokeObjectURL(url);
        setTutorSpeaking(false);
        // A short grace pause before listening again — on classroom
        // hardware where the speaker and mic sit close together, the tail
        // of the tutor's own voice can still be audible/reverberating for
        // a beat right after playback ends. Picking that echo up as the
        // student's own speech (then replying to it, then hearing THAT
        // reply overlap with lingering reverb) was a real contributor to
        // both the "dual voice" and the "keeps saying I didn't catch
        // that" reports — this doesn't eliminate acoustic echo, but it
        // gives the room a beat to go quiet before the mic starts trusting
        // what it hears again. Raised 400ms -> 900ms (2026-09-25): still
        // reported happening after 400ms, which on real classroom
        // speaker/mic placement (not a headset — echoCancellation alone
        // isn't reliably enough) is plausibly too short a margin for the
        // reverb tail to fully decay. This can't fully rule out acoustic
        // echo on hardware with especially bad speaker/mic isolation — a
        // genuine physical constraint no client-side delay eliminates —
        // but it widens the margin meaningfully without adding a
        // noticeable pause to the conversation's pacing.
        if (modeRef.current === "tutor") {
          setTimeout(() => {
            if (modeRef.current === "tutor") voiceConvo.startListening().catch(() => {});
          }, 900);
        }
      };
      audio.onended = finish;
      audio.onerror = finish;
      await audio.play();
    } catch {
      setTutorSpeaking(false);
      // Same grace pause as the normal finish() path (previously 0ms here
      // — an inconsistency, not a deliberate choice) — a play() rejection
      // doesn't guarantee no audio is/was audible (e.g. a late decode
      // error after partial playback), so relistening instantly risked
      // the exact same echo-pickup this function's normal path guards
      // against.
      if (modeRef.current === "tutor") {
        setTimeout(() => {
          if (modeRef.current === "tutor") voiceConvo.startListening().catch(() => {});
        }, 900);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The onRecording handler for useVoiceConversation below: grabs the
  // freshest frame, sends it + the audio + the running transcript to the
  // tutor endpoint, appends both sides of the exchange, then speaks the
  // reply (which relistens once it finishes — see speakTutorReply).
  const handleTutorRecording = useCallback(async (audioBlob: Blob) => {
    await captureTutorFrame();
    const history = tutorEvents.map((e) => ({ role: e.role, text: e.text }));
    try {
      const res = await api.tutorTurn(stationId, audioBlob, tutorFrameRef.current, history);
      const studentSeq = nextTutorSeq();
      const tutorSeq = nextTutorSeq();
      setTutorEvents((evs) => [
        ...evs,
        { seq: studentSeq, role: "student", text: res.transcript || "(didn't catch that)" },
        { seq: tutorSeq, role: "tutor", text: res.reply },
      ]);

      const caughtNothing = !res.transcript?.trim();
      tutorConsecutiveMissesRef.current = caughtNothing ? tutorConsecutiveMissesRef.current + 1 : 0;
      // Two "didn't catch that" turns in a row is almost always background
      // noise repeatedly tripping the VAD, not the student actually
      // talking — stop auto-relistening (and stop speaking another reply
      // on top of it) rather than looping indefinitely, which is what was
      // reported as annoying (2026-09-24). The miss is still shown in the
      // transcript above; it's only the spoken nag + auto-relisten that stop.
      if (tutorConsecutiveMissesRef.current >= 2) {
        setTutorAwaitingResume(true);
        return;
      }
      await speakTutorReply(res.reply);
    } catch {
      setTutorEvents((evs) => [...evs, { seq: nextTutorSeq(), role: "tutor", text: "Couldn't reach the tutor just now — try again in a moment." }]);
      if (modeRef.current === "tutor") voiceConvo.startListening().catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [captureTutorFrame, tutorEvents, stationId, nextTutorSeq, speakTutorReply]);

  const voiceConvo = useVoiceConversation({ onRecording: handleTutorRecording });

  // Switching to voice mode stops the photo auto-capture loop (and camera)
  // entirely — the two input types are mutually exclusive per attempt, and
  // there's nothing for the camera to usefully do while recording audio.
  // Switching back to photo leaves the camera off; the student taps Start
  // camera again, same as a fresh page load. Tutor mode instead needs the
  // camera running the whole time it's open (see below).
  async function switchMode(next: CaptureMode) {
    if (next === mode) return;
    setVoiceError("");
    if ((next === "voice" || next === "tutor") && capturing) {
      setCapturing(false);
      capturingRef.current = false;
      stopLoop();
      await api.updateStation(stationId, { status: "idle" });
    }
    if (next === "voice") stopStream();

    // Leaving tutor mode (to either sibling) tears the live conversation
    // down — no auto-relisten should fire once the student has clicked
    // away, and nothing needs the periodic capture timer running anymore.
    if (mode === "tutor") {
      voiceConvo.teardown();
      if (tutorCaptureTimerRef.current) { clearInterval(tutorCaptureTimerRef.current); tutorCaptureTimerRef.current = null; }
      if (tutorAudioRef.current) { tutorAudioRef.current.pause(); tutorAudioRef.current = null; }
      setTutorSpeaking(false);
      setTutorThumbUrl((prev) => { if (prev) URL.revokeObjectURL(prev); return null; });
      setTutorLastCapturedAt(null);
      tutorFrameRef.current = null;
      tutorConsecutiveMissesRef.current = 0;
      setTutorAwaitingResume(false);
    }

    setMode(next);

    if (next === "tutor") {
      if (camState !== "active") await startCamera();
      // Capture once immediately (don't make the student wait up to 6s for
      // the first visible confirmation that the camera is actually seeing
      // their notebook) then keep it fresh on the usual periodic cadence.
      captureTutorFrame();
      tutorCaptureTimerRef.current = setInterval(captureTutorFrame, 6000);
      setTutorEvents([{ seq: nextTutorSeq(), role: "tutor", text: "What are you working on? Show me your notebook and tell me where you're stuck." }]);
      voiceConvo.startListening().catch(() => setVoiceError("Couldn't start listening — check microphone access."));
    }
  }

  // Manual re-engagement after the circuit breaker above stops
  // auto-relistening — a deliberate tap, so a burst of noise can't
  // immediately re-trip it the same way.
  function resumeTutorListening() {
    tutorConsecutiveMissesRef.current = 0;
    setTutorAwaitingResume(false);
    voiceConvo.startListening().catch(() => setVoiceError("Couldn't start listening — check microphone access."));
  }

  // Belt-and-suspenders cleanup for the periodic capture timer specifically
  // (it's owned by this page component, not by useVoiceConversation, which
  // only knows about the mic/recording side) — covers an unmount while
  // still in tutor mode, which switchMode's own teardown wouldn't see.
  useEffect(() => () => {
    if (tutorCaptureTimerRef.current) clearInterval(tutorCaptureTimerRef.current);
  }, []);

  // Voice commands dispatched by ClassroomBrain.tsx (globally mounted, see
  // app/layout.tsx) when a student says "start the camera", "pause", or
  // "record my answer" while on THIS page — previously none of this
  // existed at all (reported 2026-09-25: "again go to ai tutor tab, say it
  // out loud or write it down tab commands are not working"). Re-subscribes
  // every render rather than chasing a memoized dependency list — switchMode/
  // handleToggleCapturing/startCamera below aren't wrapped in useCallback
  // (matching this file's existing convention), and after the
  // executeIntent stale-closure bug found the same day in ClassroomBrain.tsx
  // (a missing dependency silently freezing a boolean), a slightly wasteful
  // but always-fresh listener beats a cheap one that can go stale.
  useEffect(() => {
    async function onStartCamera() {
      if (mode !== "photo") await switchMode("photo");
      if (camState !== "active") await startCamera();
    }
    function onToggleCapture() {
      if (mode === "photo" && camState === "active") handleToggleCapturing();
    }
    async function onRecordAnswer() {
      if (mode !== "voice") { await switchMode("voice"); }
      voiceAnswerButtonRef.current?.startRecording();
    }
    async function onGenerateNotes() {
      setStationGen({ kind: "notes", loading: true });
      try {
        const res = await api.generateStationNotes(stationId);
        setStationGen({ kind: "notes", loading: false, notes: res.notes });
      } catch {
        setStationGen({ kind: "notes", loading: false, notes: "Couldn't generate notes right now — try again in a moment." });
      }
    }
    async function onGenerateQuiz() {
      setStationGen({ kind: "quiz", loading: true });
      try {
        const res = await api.generateStationQuiz(stationId);
        setStationGen({ kind: "quiz", loading: false, questions: res.questions });
      } catch {
        setStationGen({ kind: "quiz", loading: false, questions: [] });
      }
    }
    window.addEventListener("classroom-brain:station_start_camera", onStartCamera);
    window.addEventListener("classroom-brain:station_toggle_capture", onToggleCapture);
    window.addEventListener("classroom-brain:station_record_answer", onRecordAnswer);
    window.addEventListener("classroom-brain:station_generate_notes", onGenerateNotes);
    window.addEventListener("classroom-brain:station_generate_quiz", onGenerateQuiz);
    return () => {
      window.removeEventListener("classroom-brain:station_start_camera", onStartCamera);
      window.removeEventListener("classroom-brain:station_toggle_capture", onToggleCapture);
      window.removeEventListener("classroom-brain:station_record_answer", onRecordAnswer);
      window.removeEventListener("classroom-brain:station_generate_notes", onGenerateNotes);
      window.removeEventListener("classroom-brain:station_generate_quiz", onGenerateQuiz);
    };
  });

  async function submitVoiceAnswer(blob: Blob) {
    setUploading(true);
    setVoiceError("");
    try {
      console.log("[VoiceAnswer] uploading blob: %d bytes, type=%s", blob.size, blob.type);
      const form = new FormData();
      form.append("audio", blob, "answer.webm");
      const created = await api.createStationAttempt(stationId, form);
      // TEMPORARY diagnostic: confirms the server accepted the upload and
      // what it stored — status is "processing" here since the real
      // pipeline (transcribe/validate/hint) runs async after this returns.
      console.log("[VoiceAnswer] server accepted attempt:", created);
      await refresh();
    } catch (err) {
      console.error("[VoiceAnswer] upload failed:", err);
      setVoiceError(err instanceof Error ? err.message : "Couldn't submit that recording — try again.");
    } finally {
      setUploading(false);
    }
  }

  // Teacher can remotely pause/resume or reassign a question — reflect it
  // on the device without the student having to do anything.
  useEffect(() => {
    if (!station) return;
    if (station.status === "capturing" && !capturingRef.current && camState === "active") {
      setCapturing(true);
      capturingRef.current = true;
      startLoop(station.capture_interval_sec);
    }
    if (station.status === "idle" && capturingRef.current) {
      setCapturing(false);
      capturingRef.current = false;
      stopLoop();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [station?.status, station?.capture_interval_sec, camState]);

  const latest = attempts.length > 0 ? attempts[attempts.length - 1] : null;
  // Newest first — a new result should be visible the instant the panel is
  // looked at, not require scrolling down past everything already seen.
  const allCompletedAttempts = [...attempts].filter((a) => a.status === "complete").reverse();

  // Auto-capped view: the panel used to accumulate every capture forever,
  // and the earlier "Clear" button only hid them client-side (nothing
  // deleted server-side), so they all reappeared on the next page load —
  // reported 2026-09-19. Now the visible list is naturally capped to the
  // most recent KEEP_RECENT results, PLUS every solved attempt regardless
  // of age (a correct answer is worth keeping visible as a record, not
  // just pruned away once 10 more captures happen). Explicit delete below
  // is the only thing that's actually permanent.
  const KEEP_RECENT = 10;
  const recentIds = new Set(allCompletedAttempts.slice(0, KEEP_RECENT).map((a) => a.attempt_id));
  const completedAttempts = allCompletedAttempts.filter(
    (a) => recentIds.has(a.attempt_id) || a.validation_status === "solved"
  );
  // Older, non-solved attempts that the cap is already hiding from view —
  // exactly what "Delete old attempts" actually removes, so the count on
  // that button matches what pressing it will do.
  const prunableAttempts = allCompletedAttempts.filter(
    (a) => !recentIds.has(a.attempt_id) && a.validation_status !== "solved"
  );

  const clearBubbleTimer = useCallback(() => {
    if (bubbleTimerRef.current) { clearInterval(bubbleTimerRef.current); bubbleTimerRef.current = null; }
  }, []);

  const closePanel = useCallback(() => {
    clearBubbleTimer();
    setAutoDismissActive(false);
    setPanelOpen(false);
  }, [clearBubbleTimer]);

  const startAutoDismissTimer = useCallback(() => {
    clearBubbleTimer();
    setBarPct(100);
    bubbleTimerRef.current = setInterval(() => {
      setBarPct((pct) => Math.max(0, pct - 100 / (BUBBLE_AUTO_DISMISS_MS / BUBBLE_TICK_MS)));
    }, BUBBLE_TICK_MS);
  }, [clearBubbleTimer]);

  useEffect(() => {
    if (barPct <= 0 && autoDismissActive) closePanel();
  }, [barPct, autoDismissActive, closePanel]);

  useEffect(() => () => clearBubbleTimer(), [clearBubbleTimer]);

  // Any real interaction — opening the panel on purpose, typing, sending —
  // cancels the auto-close (a real chat window doesn't vanish mid-use) and
  // counts everything shown so far as seen, clearing the badge.
  const cancelAutoDismiss = useCallback(() => {
    clearBubbleTimer();
    setAutoDismissActive(false);
    setLastSeenCount(completedAttempts.length);
  }, [clearBubbleTimer, completedAttempts.length]);

  const openPanel = useCallback(() => {
    setPanelOpen(true);
    cancelAutoDismiss();
  }, [cancelAutoDismiss]);

  // Pop the panel open for whichever results are genuinely new since the
  // last render — a fresh capture just finished grading — never for the
  // backlog already sitting there on first load. Gated on `station` (not
  // just `attempts`) because `attempts` starts as `[]` before the first
  // fetch resolves — diffing against that empty starting state would
  // otherwise treat the very first real fetch's whole history as "new".
  useEffect(() => {
    if (!station) return;
    const fresh = completedAttempts.filter((a) => !seenAttemptIds.current.has(a.attempt_id));
    completedAttempts.forEach((a) => seenAttemptIds.current.add(a.attempt_id));
    if (fresh.length === 0) return;
    const chronological = [...fresh].reverse(); // completedAttempts is newest-first
    const newEvents = chronological.map((attempt) => ({ seq: nextSeq(), kind: "attempt" as const, attempt }));
    setEvents((evs) => [...evs, ...newEvents]);
    // The baseline pass (whatever was already graded before this page even
    // loaded) fills the transcript so it's there when opened, but shouldn't
    // pop the panel open or start a countdown — only a result that arrives
    // while the student is actually here does that.
    if (!everMounted.current) { everMounted.current = true; return; }
    setPanelOpen(true);
    setAutoDismissActive(true);
    startAutoDismissTimer();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [station, attempts, startAutoDismissTimer]);

  useEffect(() => {
    if (panelOpen && scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [events, panelOpen]);

  async function sendMessage() {
    const text = chatInput.trim();
    if (!text || sending || !station) return;
    cancelAutoDismiss();
    setChatInput("");
    setSending(true);
    const userSeq = nextSeq();
    const typingSeq = nextSeq();
    setEvents((evs) => [...evs, { seq: userSeq, kind: "user", text }, { seq: typingSeq, kind: "typing" }]);
    try {
      const res = await api.askBrain(stationId, text);
      setEvents((evs) => evs.map((e) => (e.seq === typingSeq ? { seq: typingSeq, kind: "brain", text: res.reply, declined: res.declined } : e)));
    } catch {
      setEvents((evs) => evs.map((e) => (e.seq === typingSeq ? { seq: typingSeq, kind: "brain", text: "Couldn't reach the Brain just now — try asking again.", declined: false } : e)));
    } finally {
      setSending(false);
    }
  }

  const unreadCount = panelOpen ? 0 : Math.max(0, completedAttempts.length - lastSeenCount);
  const hasBadge = unreadCount > 0;

  async function deleteAttempt(attemptId: string) {
    setDeletingIds((prev) => new Set(prev).add(attemptId));
    try {
      await api.deleteAttempt(attemptId);
      setAttempts((prev) => prev.filter((a) => a.attempt_id !== attemptId));
      setEvents((evs) => evs.filter((e) => !(e.kind === "attempt" && e.attempt.attempt_id === attemptId)));
    } catch {
      // leave it in place — the next poll will reconcile either way
    } finally {
      setDeletingIds((prev) => { const next = new Set(prev); next.delete(attemptId); return next; });
    }
  }

  async function deleteOldAttempts() {
    if (prunableAttempts.length === 0) return;
    if (!confirm(`Permanently delete ${prunableAttempts.length} older attempt${prunableAttempts.length === 1 ? "" : "s"}? Solved answers and your last ${KEEP_RECENT} are kept. This can't be undone.`)) return;
    const idsToRemove = new Set(prunableAttempts.map((a) => a.attempt_id));
    setBulkDeleting(true);
    try {
      await Promise.all(prunableAttempts.map((a) => api.deleteAttempt(a.attempt_id).catch(() => {})));
      await refresh();
      setEvents((evs) => evs.filter((e) => !(e.kind === "attempt" && idsToRemove.has(e.attempt.attempt_id))));
    } finally {
      setBulkDeleting(false);
    }
  }

  if (!station) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-900">
        <Loader2 className="h-8 w-8 animate-spin text-white/60" />
      </div>
    );
  }

  return (
    // h-screen + overflow-hidden (not min-h-screen) is deliberate: the
    // camera's flex-1 needs a DEFINITE height to resolve against — this
    // broke on real devices the moment a second flex sibling (the old
    // docked feedback column) entered the picture. Now that feedback is an
    // overlay instead of a layout sibling, the camera column is the only
    // child and always gets the full screen.
    <div className="h-screen overflow-hidden bg-slate-900 text-white flex flex-col">
      <style>{`
        @keyframes ps-bubble-in { from { opacity: 0; transform: translateY(14px) scale(.97); } to { opacity: 1; transform: translateY(0) scale(1); } }
        @keyframes ps-msg-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes ps-dot { 0%, 60%, 100% { transform: translateY(0); opacity: .4; } 30% { transform: translateY(-3px); opacity: 1; } }
        @keyframes ps-capture-flash { 0% { opacity: 1; } 70% { opacity: 1; } 100% { opacity: .6; } }
        .ps-bubble { animation: ps-bubble-in .28s cubic-bezier(.2,.8,.2,1); }
        .ps-msg { animation: ps-msg-in .22s ease-out; }
        .ps-dot { animation: ps-dot 1.1s ease-in-out infinite; }
        .ps-capture-flash { animation: ps-capture-flash 1.4s ease-out; }
        @media (prefers-reduced-motion: reduce) { .ps-bubble, .ps-msg, .ps-dot, .ps-capture-flash { animation: none !important; } }
      `}</style>
      {/* Main column: header, camera, controls */}
      <div className="flex flex-1 min-w-0 min-h-0 flex-col">
        {/* Header */}
        <div className="px-4 py-3 border-b border-white/10 flex items-center gap-3">
          <Link
            href={`/sessions/${station.session_id}/guided-practice`}
            title="Back to Guided Practice"
            onClick={() => {
              // Leaving this page stops the camera (a browser can't keep a
              // getUserMedia stream alive once the tab navigates away) — tell
              // the backend now so the teacher dashboard shows "Paused"
              // instead of a stale "Capturing" badge for a station nobody's
              // actually looking at. Fire-and-forget: shouldn't block leaving.
              if (capturing) api.updateStation(stationId, { status: "idle" }).catch(() => {});
            }}
            className="shrink-0 flex h-9 w-9 items-center justify-center rounded-full bg-white/10 hover:bg-white/20 text-white transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div className="min-w-0 flex-1">
            <p className="text-xs text-white/50">{station.label}</p>
            <p className="text-sm font-medium truncate">
              {station.active_question_text ?? "Waiting for a question to be assigned…"}
            </p>
          </div>
          {latest?.attempt_no && (
            <span className="shrink-0 rounded-full bg-white/10 px-2.5 py-1 text-[0.6875rem] text-white/60">
              Attempt #{latest.attempt_no}
            </span>
          )}
          {/* Opens the Brain chat — always here, not just while it's popped
              up on its own, so there's still a way to open it (and ask a
              question) once it's auto-closed. Badge is how a missed result
              stays noticeable. */}
          <button
            onClick={openPanel}
            title="Chat with the Classroom Brain"
            className="relative shrink-0 flex h-9 w-9 items-center justify-center rounded-full bg-white/10 hover:bg-white/20 text-white transition-colors"
          >
            <Brain className="h-4 w-4" />
            {hasBadge && (
              <span className="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[0.625rem] font-bold">
                {unreadCount}
              </span>
            )}
          </button>
        </div>

        {/* Teacher note banner */}
        {station.teacher_note && (
          <div className="mx-4 mt-3 flex items-start gap-2 rounded-lg bg-indigo-500/20 border border-indigo-400/30 px-3 py-2 text-sm">
            <MessageSquare className="h-4 w-4 shrink-0 mt-0.5 text-indigo-300" />
            <span>{station.teacher_note}</span>
          </div>
        )}

        {/* Mode toggle — "Write it down" (photo, the original flow),
            "Say it out loud" (voice), and "Ask AI Tutor" (a live voice+vision
            conversation for when they're stuck, not a graded attempt at
            all). Always visible, not tied to the question's domain, so the
            student decides per attempt. */}
        <div className="mx-4 mt-3 flex gap-2">
          <button
            onClick={() => switchMode("photo")}
            className={cn(
              "flex flex-1 items-center justify-center gap-1.5 rounded-xl border py-2 text-xs font-semibold transition-colors",
              mode === "photo" ? "bg-indigo-600 border-indigo-500 text-white" : "border-white/15 text-white/60 hover:bg-white/5"
            )}
          >
            <ImageIcon className="h-3.5 w-3.5" /> Write it down
          </button>
          <button
            onClick={() => switchMode("voice")}
            className={cn(
              "flex flex-1 items-center justify-center gap-1.5 rounded-xl border py-2 text-xs font-semibold transition-colors",
              mode === "voice" ? "bg-indigo-600 border-indigo-500 text-white" : "border-white/15 text-white/60 hover:bg-white/5"
            )}
          >
            <Mic className="h-3.5 w-3.5" /> Say it out loud
          </button>
          <button
            onClick={() => switchMode("tutor")}
            className={cn(
              "flex flex-1 items-center justify-center gap-1.5 rounded-xl border py-2 text-xs font-semibold transition-colors",
              mode === "tutor" ? "bg-indigo-600 border-indigo-500 text-white" : "border-white/15 text-white/60 hover:bg-white/5"
            )}
          >
            <GraduationCap className="h-3.5 w-3.5" /> Ask AI Tutor
          </button>
        </div>

        {/* Camera / preview area — full-size in normal flow, or a small fixed
            corner thumbnail when minimized. The <video> element itself is
            never unmounted between the two, so the live stream and the
            auto-capture timers (which don't touch this DOM node) are
            completely unaffected by toggling this. Shared by photo AND
            tutor mode (both need the camera live) — switchMode already
            stopped the stream when leaving to voice mode. */}
        {(mode === "photo" || mode === "tutor") && (
        <>
        <div
          className={cn(
            "bg-black overflow-hidden transition-all",
            cameraMinimized
              ? "fixed bottom-4 right-4 z-30 h-28 w-20 rounded-xl border-2 border-white/20 shadow-xl"
              : "relative flex-1 mx-4 mt-3 rounded-2xl"
          )}
        >
          <video ref={videoRef} playsInline muted className="h-full w-full object-cover" />

          {/* Framing grid — rule-of-thirds guides plus a thin edge margin,
              purely advisory (reverted 2026-09-25 from a tighter rect that
              matched a digital crop — that crop got removed for cutting
              into legitimate page content on a large textbook, so this no
              longer claims to show an exact "capture boundary", just a
              light reminder to keep the page off the very edge). The
              capture is the FULL video frame; nothing is cropped out. */}
          {camState === "active" && !cameraMinimized && (
            <svg
              viewBox="0 0 100 100"
              preserveAspectRatio="none"
              className="pointer-events-none absolute inset-0 h-full w-full"
              aria-hidden="true"
            >
              <rect x="2" y="2" width="96" height="96" rx="2" fill="none" stroke="white" strokeOpacity="0.4" strokeWidth="0.5" />
              <line x1="34.7" y1="2" x2="34.7" y2="98" stroke="white" strokeOpacity="0.25" strokeWidth="0.3" />
              <line x1="65.3" y1="2" x2="65.3" y2="98" stroke="white" strokeOpacity="0.25" strokeWidth="0.3" />
              <line x1="2" y1="34.7" x2="98" y2="34.7" stroke="white" strokeOpacity="0.25" strokeWidth="0.3" />
              <line x1="2" y1="65.3" x2="98" y2="65.3" stroke="white" strokeOpacity="0.25" strokeWidth="0.3" />
            </svg>
          )}

          {camState !== "active" && !cameraMinimized && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/60 text-center px-6">
              {camState === "error" ? (
                <>
                  <AlertTriangle className="h-8 w-8 text-red-400" />
                  <p className="text-sm text-white/80">{errorMsg || "Camera unavailable."}</p>
                </>
              ) : (
                <>
                  <Camera className="h-8 w-8 text-white/60" />
                  <p className="text-sm text-white/70">Tap Start to turn on the camera over your notebook.</p>
                </>
              )}
            </div>
          )}

          {mode === "photo" && capturing && countdown != null && !cameraMinimized && (
            <div className="absolute top-3 left-3 flex items-center gap-1.5 rounded-full bg-black/50 px-3 py-1 text-xs">
              <span className="h-1.5 w-1.5 rounded-full bg-red-500 animate-pulse" />
              Next photo in {countdown}s
            </div>
          )}

          {mode === "photo" && uploading && !cameraMinimized && (
            <div className="absolute top-3 left-1/2 -translate-x-1/2 flex items-center gap-1.5 rounded-full bg-black/60 px-3 py-1 text-xs">
              <Loader2 className="h-3 w-3 animate-spin" /> Checking your work…
            </div>
          )}

          {mode === "tutor" && !cameraMinimized && tutorAwaitingResume && (
            // The circuit breaker below stopped auto-relistening after a
            // couple of consecutive "didn't catch that" turns (almost
            // always background noise, not the student) — an explicit tap
            // re-engages rather than a burst of the same noise immediately
            // re-tripping it.
            <button
              onClick={resumeTutorListening}
              className="absolute top-3 left-1/2 -translate-x-1/2 flex items-center gap-1.5 rounded-full bg-amber-600/90 hover:bg-amber-500 px-3 py-1 text-xs font-medium"
            >
              <Mic className="h-3 w-3" /> Tap to keep talking
            </button>
          )}

          {mode === "tutor" && !cameraMinimized && !tutorAwaitingResume && (
            <div
              className={cn(
                "absolute top-3 left-1/2 -translate-x-1/2 flex items-center gap-1.5 rounded-full px-3 py-1 text-xs",
                tutorSpeaking ? "bg-indigo-600/80" : voiceConvo.state === "listening" ? "bg-emerald-600/80" : "bg-black/60"
              )}
            >
              {tutorSpeaking ? (
                <><Volume2 className="h-3 w-3" /> Tutor speaking…</>
              ) : voiceConvo.state === "listening" ? (
                <><Mic className="h-3 w-3 animate-pulse" /> Listening…</>
              ) : voiceConvo.state === "processing" ? (
                <><Loader2 className="h-3 w-3 animate-spin" /> Thinking…</>
              ) : (
                <>Show me your notebook</>
              )}
            </div>
          )}

          {/* Live mic-level meter — the only way to actually SEE whether
              the microphone is picking up anything at all while listening,
              as opposed to guessing from "I didn't catch that" after the
              fact (reported 2026-09-24: that message firing on nearly
              every turn, with server logs showing every recording running
              the full 9s to its safety ceiling and Whisper hallucinating
              silence-only filler phrases — strong signs of a capture
              problem, not a vision one, but unconfirmable without seeing
              the actual level). The red line marks VAD_SPEECH_THRESHOLD
              (0.12) — the level needs to cross it for the recording to
              ever be recognized as "the student is talking" at all. */}
          {mode === "tutor" && !cameraMinimized && voiceConvo.state === "listening" && (
            <div className="absolute top-11 left-1/2 -translate-x-1/2 w-40">
              <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-black/50">
                <div
                  className={cn("h-full rounded-full transition-[width]", voiceConvo.level > 0.12 ? "bg-emerald-400" : "bg-white/50")}
                  style={{ width: `${Math.min(100, voiceConvo.level * 100)}%` }}
                />
                <div className="absolute inset-y-0 w-px bg-red-400" style={{ left: "12%" }} />
              </div>
            </div>
          )}

          {/* Visible proof the notebook/textbook is actually being seen —
              reported 2026-09-24 that students couldn't tell whether
              anything was being captured at all. Flashes brighter for a
              beat right after each fresh capture (keyed by the timestamp
              so the CSS animation restarts every time), settling to a
              steady, still-visible thumbnail in between. */}
          {mode === "tutor" && !cameraMinimized && tutorThumbUrl && (
            <div className="absolute bottom-3 left-3 flex items-center gap-1.5 rounded-lg bg-black/60 p-1 pr-2">
              <img src={tutorThumbUrl} alt="what the tutor last saw" className="h-10 w-10 rounded object-cover border border-white/25" />
              <span key={tutorLastCapturedAt ?? 0} className="ps-capture-flash text-[0.625rem] font-medium text-emerald-300">
                Captured
              </span>
            </div>
          )}

          {camState === "active" && (
            <button
              onClick={() => setCameraMinimized((v) => !v)}
              title={cameraMinimized ? "Show full camera view" : "Minimize camera — keeps capturing in the background"}
              className={cn(
                "absolute rounded-lg bg-black/50 hover:bg-black/70 text-white transition-colors",
                cameraMinimized ? "inset-0 flex items-center justify-center" : "top-3 right-3 p-1.5"
              )}
            >
              {cameraMinimized ? <Maximize2 className="h-4 w-4" /> : <Minimize2 className="h-4 w-4" />}
            </button>
          )}

          {cameraMinimized && capturing && (
            <span className="absolute top-1.5 left-1.5 h-1.5 w-1.5 rounded-full bg-red-500 animate-pulse" />
          )}
        </div>

        {/* Controls — photo mode only; tutor mode has no manual shutter,
            it's a running conversation instead (panel below). */}
        {mode === "photo" && (
        <div className="p-4 flex items-center gap-3">
          {camState !== "active" ? (
            <button
              onClick={startCamera}
              className="flex-1 rounded-xl bg-indigo-600 py-3 text-sm font-semibold hover:bg-indigo-500 transition-colors"
            >
              Start camera
            </button>
          ) : (
            <>
              <button
                onClick={handleToggleCapturing}
                className={cn(
                  "flex-1 flex items-center justify-center gap-2 rounded-xl py-3 text-sm font-semibold transition-colors",
                  capturing ? "bg-amber-600 hover:bg-amber-500" : "bg-emerald-600 hover:bg-emerald-500"
                )}
              >
                {capturing ? <><Pause className="h-4 w-4" /> Pause</> : <><Play className="h-4 w-4" /> Start auto-capture</>}
              </button>
              <button
                onClick={() => snapAndUpload()}
                disabled={uploading}
                className="rounded-xl bg-white/10 px-4 py-3 text-sm font-semibold hover:bg-white/20 transition-colors disabled:opacity-50"
              >
                <Camera className="h-4 w-4" />
              </button>
            </>
          )}
        </div>
        )}

        {/* Tutor mode — a running voice+vision conversation instead of a
            graded attempt. Shares the camera block above; this is just the
            transcript + mic-state strip beneath it. */}
        {mode === "tutor" && (
        // max-h reduced from 52 (208px) to 28 (112px) — reported
        // 2026-09-25 that the camera itself was getting too little screen
        // space in tutor mode to show enough of a full textbook page. The
        // camera div above is `flex-1` (takes whatever's left), so this
        // panel's height directly trades off against it; the inner
        // transcript already scrolls (overflow-y-auto below), so nothing
        // is lost — just shows less at once before scrolling.
        <div className="mx-4 mb-4 mt-3 flex max-h-28 flex-col overflow-hidden rounded-2xl bg-black/30 border border-white/10">
          <div className="flex items-center gap-2 border-b border-white/10 px-3 py-2">
            <GraduationCap className="h-3.5 w-3.5 text-indigo-300" />
            <p className="text-xs font-semibold text-white/70">AI Tutor</p>
          </div>
          <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
            {tutorEvents.map((e) => (
              <div
                key={e.seq}
                className={cn("ps-msg flex", e.role === "student" ? "justify-end" : "justify-start")}
              >
                <p
                  className={cn(
                    "max-w-[85%] rounded-xl px-3 py-1.5 text-xs leading-snug",
                    e.role === "student" ? "bg-indigo-600 text-white" : "bg-white/10 text-white/85"
                  )}
                >
                  {e.text}
                </p>
              </div>
            ))}
          </div>
          {voiceError && <p className="px-3 pb-2 text-[0.6875rem] text-red-400">{voiceError}</p>}
        </div>
        )}
        </>
        )}

        {/* Voice mode — one answer at a time. VoiceAnswerButton auto-stops
            on silence and submits immediately (no separate confirm tap) —
            see its own file for the VAD approach. No auto-loop here (unlike
            photo mode) — each answer is its own deliberate recording,
            started by a tap. */}
        {mode === "voice" && (
          <div className="flex-1 mx-4 mt-3 flex flex-col items-center justify-center gap-4 rounded-2xl bg-black/30 border border-white/10 px-6 text-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-indigo-600/20">
              <Mic className="h-7 w-7 text-indigo-300" />
            </div>
            <p className="text-sm text-white/70 max-w-xs">
              Say your answer out loud — it'll check itself once you go quiet.
            </p>
            <VoiceAnswerButton ref={voiceAnswerButtonRef} onCapture={submitVoiceAnswer} label="Record my answer" size="md" />
            {voiceError && <p className="text-xs text-red-400">{voiceError}</p>}
            {uploading && (
              <p className="flex items-center gap-1.5 text-xs text-white/50">
                <Loader2 className="h-3 w-3 animate-spin" /> Checking your answer…
              </p>
            )}
          </div>
        )}
      </div>

      {/* Result panel for the "generate notes"/"generate quiz" voice
          commands (see the classroom-brain:station_generate_notes/quiz
          listeners above) — a small dismissible card, not a full document
          viewer, matching the scope of a single station's attempt history
          rather than a whole session's generated output. */}
      {stationGen && (
        <div className="fixed top-16 right-4 left-4 sm:left-auto sm:w-[24rem] z-40 rounded-2xl bg-slate-950 border border-white/10 shadow-2xl p-4">
          <div className="flex items-center justify-between gap-2 mb-2">
            <p className="text-xs font-semibold text-white/70 flex items-center gap-1.5">
              <Sparkles className="h-3.5 w-3.5 text-indigo-300" />
              {stationGen.kind === "notes" ? "Notes for this station" : "Quiz for this station"}
            </p>
            <button
              type="button"
              onClick={() => setStationGen(null)}
              className="rounded-full p-1 text-white/40 hover:bg-white/10 hover:text-white/80"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          {stationGen.loading ? (
            <p className="flex items-center gap-1.5 text-xs text-white/50">
              <Loader2 className="h-3 w-3 animate-spin" /> Generating…
            </p>
          ) : stationGen.kind === "notes" ? (
            <p className="text-xs leading-relaxed text-white/85 whitespace-pre-line">{stationGen.notes}</p>
          ) : stationGen.questions && stationGen.questions.length > 0 ? (
            <ol className="list-decimal list-inside space-y-1.5 text-xs text-white/85">
              {stationGen.questions.map((q, i) => <li key={i}>{q}</li>)}
            </ol>
          ) : (
            <p className="text-xs text-white/50">No attempt history yet to build a quiz from.</p>
          )}
        </div>
      )}

      {/* The Classroom Brain — one real chat, not a results feed. Pops open
          on a fresh result (auto-closing after BUBBLE_AUTO_DISMISS_MS if
          left untouched) or opens on demand from the header icon and then
          stays open. Anchored top-right, clear of both the minimized-camera
          thumbnail and the bottom controls bar (both bottom-anchored). */}
      {panelOpen && (
        <div className="ps-bubble fixed top-16 right-4 left-4 sm:left-auto sm:w-[26rem] z-40 flex max-h-[78vh] flex-col overflow-hidden rounded-3xl bg-slate-950 border border-white/10 shadow-2xl">
          {autoDismissActive && (
            <div className="h-1 shrink-0 bg-white/10">
              <div className="h-full bg-[#D7A24E]" style={{ width: `${barPct}%` }} />
            </div>
          )}
          <div className="flex shrink-0 items-center justify-between gap-2 border-b border-white/10 px-4 py-3">
            <div className="flex min-w-0 items-center gap-2.5">
              <div className="flex h-[1.875rem] w-[1.875rem] shrink-0 items-center justify-center rounded-full bg-indigo-600">
                <Brain className="h-3.5 w-3.5 text-white" />
              </div>
              <p className="text-[0.8125rem] font-semibold text-white">Classroom Brain</p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {prunableAttempts.length > 0 && (
                <button
                  onClick={deleteOldAttempts}
                  disabled={bulkDeleting}
                  title={`Permanently delete the ${prunableAttempts.length} older attempt${prunableAttempts.length === 1 ? "" : "s"} not shown below — solved answers and your last ${KEEP_RECENT} are always kept`}
                  className="text-[0.6875rem] text-white/40 hover:text-red-400 disabled:opacity-50"
                >
                  {bulkDeleting ? "Deleting…" : `Delete old (${prunableAttempts.length})`}
                </button>
              )}
              <button onClick={closePanel} aria-label="Close" className="flex h-[1.625rem] w-[1.625rem] shrink-0 items-center justify-center rounded-full bg-white/10 text-white/70 hover:bg-white/20">
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto p-3 flex flex-col gap-3">
            {events.length === 0 && (
              <p className="text-sm text-white/40 text-center py-8">
                Results will show up here as they&apos;re graded — or ask a question about this question any time.
              </p>
            )}
            {events.map((e) => {
              if (e.kind === "attempt") {
                return (
                  <div key={e.seq} className="ps-msg flex items-start gap-2">
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-indigo-600 mt-0.5">
                      <Brain className="h-3.5 w-3.5 text-white" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <AttemptResultCard attempt={e.attempt} onDelete={deleteAttempt} deleting={deletingIds.has(e.attempt.attempt_id)} />
                    </div>
                  </div>
                );
              }
              if (e.kind === "brain") {
                return (
                  <div key={e.seq} className="ps-msg flex items-start gap-2">
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-indigo-600 mt-0.5">
                      <Brain className="h-3.5 w-3.5 text-white" />
                    </div>
                    <div className={cn(
                      "min-w-0 rounded-2xl rounded-tl-md px-3.5 py-2.5 text-sm leading-snug",
                      e.declined ? "bg-white/5 text-white/70 italic" : "bg-white/10 text-white/90"
                    )}>
                      {e.text}
                    </div>
                  </div>
                );
              }
              if (e.kind === "typing") {
                return (
                  <div key={e.seq} className="ps-msg flex items-start gap-2">
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-indigo-600 mt-0.5">
                      <Brain className="h-3.5 w-3.5 text-white" />
                    </div>
                    <div className="flex items-center gap-1 rounded-2xl rounded-tl-md bg-white/10 px-3.5 py-3">
                      <span className="ps-dot h-1.5 w-1.5 rounded-full bg-white/60" style={{ animationDelay: "0ms" }} />
                      <span className="ps-dot h-1.5 w-1.5 rounded-full bg-white/60" style={{ animationDelay: "150ms" }} />
                      <span className="ps-dot h-1.5 w-1.5 rounded-full bg-white/60" style={{ animationDelay: "300ms" }} />
                    </div>
                  </div>
                );
              }
              // kind === "user"
              return (
                <div key={e.seq} className="ps-msg flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-md bg-indigo-600 px-3.5 py-2.5 text-sm text-white">
                    {e.text}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="shrink-0 border-t border-white/10 p-3">
            {autoDismissActive && (
              <p className="mb-2 text-[0.6875rem] text-white/40">Closes on its own — ask a question to keep it open.</p>
            )}
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={chatInput}
                onChange={(e) => { setChatInput(e.target.value); if (autoDismissActive) cancelAutoDismiss(); }}
                onFocus={() => { if (autoDismissActive) cancelAutoDismiss(); }}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
                placeholder="Ask about this question…"
                className="min-w-0 flex-1 rounded-full bg-white/10 px-3.5 py-2 text-sm text-white placeholder:text-white/40 focus:outline-none focus:ring-2 focus:ring-indigo-400"
              />
              <VoiceDictateButton
                title="Ask by voice"
                onTranscript={(text) => { setChatInput((prev) => (prev ? `${prev} ${text}` : text)); cancelAutoDismiss(); }}
              />
              <button
                onClick={sendMessage}
                disabled={!chatInput.trim() || sending}
                aria-label="Send"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-white transition-colors hover:bg-indigo-500 disabled:opacity-40"
              >
                {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
