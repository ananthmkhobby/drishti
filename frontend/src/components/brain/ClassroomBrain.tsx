"use client";

/**
 * Classroom Brain — floating voice-assistant icon + full-screen listening
 * overlay. Tap to open, speaks immediately, auto-stops after silence/timeout,
 * shows the transcript as soon as it's available (verification before the
 * answer arrives), answers via /voice/command (local Qwen first, OpenAI
 * fallback), and speaks the answer back — via OpenAI TTS when online (far
 * more natural than the browser's built-in voice), falling back to the
 * browser's speechSynthesis when offline or if that call fails.
 *
 * Executed intents: create_session, start_teaching, generate_notes/quiz/summary/experiments
 * (also covers "regenerate" — same call, the backend always re-pulls the
 * session's current OCR text, so it's never stale), end_session — simple API
 * calls, safe to wire from anywhere in the app. capture_frame / start_camera /
 * start_recording work from ANYWHERE inside a session (not just its /capture
 * tab): if the teacher isn't already there, we router.push to
 * `/sessions/[id]/capture` with the same `?autostart=camera|audio|video`
 * query params the dashboard's own "Quick capture" shortcuts use (see
 * CommandCenter.tsx) — reusing that existing mechanism rather than adding a
 * second one — then, for capture_frame specifically, wait for the capture
 * page to report the camera is actually live (see the
 * "classroom-brain:camera_ready" listener below) before firing the photo,
 * since getUserMedia is async and the shutter would otherwise no-op against
 * a camera that isn't open yet. start_camera/start_recording don't need that
 * handshake — autostart already IS the requested action, nothing further to
 * fire once the page lands. stop_camera/stop_recording, by contrast, only
 * ever have something to stop if we're already on /capture (that's the only
 * place a camera/recorder can be running), so off that page they just report
 * there's nothing active rather than navigating anywhere. download_pdf only
 * works on a page with a PDF export (notes, quiz, homework, class-analysis,
 * lesson-plan) — all bridged to their page components via plain DOM
 * CustomEvents ("classroom-brain:capture_frame", "classroom-brain:download_pdf",
 * etc.), since this assistant is mounted globally and has no direct access to
 * those components' state.
 *
 * The mic does NOT auto-reopen after an answer (it used to — but with no
 * silence detection, a silent reopen just records ambient noise for up to
 * MAX_RECORDING_MS, which Whisper can hallucinate into a bogus new question
 * the teacher never asked). Follow-ups require an explicit tap — OR the wake
 * word below.
 *
 * Wake word ("Hey XP", toggleable in the help panel, on by default):
 * runs via useWakeWord (see src/hooks/useWakeWord.ts), which holds a
 * WebSocket open to the BACKEND's own on-device detector (openWakeWord,
 * against the backend machine's — the Pi's — own microphone, not this
 * browser tab's) and calls handleOpen() the instant a detection is pushed
 * through. Two earlier approaches were tried and dropped, in order:
 *   1. Chrome's SpeechRecognition matching a loose substring of the wake
 *      phrase — not actually local despite appearances (streams to
 *      Google's speech service), and that round trip was the real source
 *      of a multi-second wake-to-open delay (reported 2026-09-11).
 *   2. Picovoice Porcupine, genuinely on-device but in-browser (WASM) —
 *      fast, but training a custom keyword needed a Picovoice account and
 *      their review queue, which stalled rollout (2026-09-11).
 * Running detection backend-side with openWakeWord avoids both: free/
 * open-source, no account/review, and no browser mic-permission dance just
 * to listen for a wake phrase. handleOpen() then starts a fresh recording +
 * SpeechRecognition-based stop-word listener (see STOP_WORD_PATTERN below),
 * same as a manual tap — there's no live session to hand off across the
 * wake-word/stop-word boundary since the wake word never touches this
 * tab's own mic at all.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Brain, HelpCircle, Maximize2, Mic, X } from "lucide-react";
import { api, APIError, DEV_TEACHER_ID, type VoiceCommandResponse } from "@/lib/api";
import { generateUUID } from "@/lib/uuid";
import { useWakeWord } from "@/hooks/useWakeWord";
import { findHeroChapter } from "@/components/session/CommandCenter";

// Shown in the "?" panel so teachers can see, in one place, exactly what
// phrasing works — voice commands are only easy to use if it's obvious what
// to say. Grouped by what each command needs to be available.
const SAMPLE_COMMANDS: { group: string; examples: string[] }[] = [
  {
    group: "Anywhere",
    examples: [
      "“Start a new physics class for grade 8”",
      "“Where did we stop yesterday?”",
      "“Explain photosynthesis simply”",
      "“Open the quiz from my physics class”",
      "“Open the grade 5 session from 10 days ago”",
      "“Delete my physics class”",
    ],
  },
  {
    group: "While viewing a session",
    examples: [
      "“Take me to the experiments page”",
      "“Go to the quiz tab” / “Show me the notes”",
      "“Regenerate the quiz” / “Regenerate my notes”",
      "“Let's start the light chapter” (needs a textbook uploaded first)",
      "“Take a photo of the board” (opens Capture and snaps it)",
      "“Start the camera” / “Start recording audio” / “Start recording video”",
    ],
  },
  {
    group: "On a report page (notes, quiz, homework, class analysis, lesson plan)",
    examples: [
      "“Download this as a PDF” / “Export the quiz”",
    ],
  },
  {
    group: "On a session's capture screen",
    examples: [
      "“Stop the camera” / “Stop recording”",
      "“Reprocess that photo”",
      "“Generate my notes” / “Make a quiz” / “Suggest experiments”",
      "“Generate practice questions” / “Go to guided practice”",
      "“Start capturing for [student name]” / “Stop capturing for [student name]”",
      "“Generate homework” / “Make the lesson plan” / “Analyze the classroom”",
      "“Generate the session report” / “Make the absorption map”",
      "“End the session”",
    ],
  },
  {
    group: "While teaching a chapter",
    examples: [
      "“Continue” (resumes wherever you left off, or advances to the next part)",
      "“Check my understanding”",
      "“Mute the audio” / “Turn the audio back on”",
    ],
  },
];

// Every tab in a session's view (see [sessionId]/layout.tsx's TABS array) —
// kept in one place since both view_tab (same session) and open_session
// (a different session) navigate to these same routes. "overview" maps to
// the session's base path, not a route segment of its own.
const SESSION_TABS = [
  "overview", "capture", "ocr", "notes", "quiz", "experiments",
  "missing-concepts", "homework", "class-analysis", "lesson-plan",
  "session-report", "tiqer", "textbook", "guided-practice", "absorption-map",
];

// Spoken/display label for a tab's route value — several of these read
// nothing like what's on screen or what a teacher actually said ("summary"
// -> "overview", "classroom snapshot" -> "class-analysis", "opportunities"
// -> "missing-concepts", "thinkstep" -> "guided-practice" — see view_tab's
// own params.output mapping in voice_intent_service.py for the reverse
// direction). The view_tab/open_session handlers used to speak the raw
// route value back verbatim ("Going to overview." instead of "Going to the
// summary.", or "Going to class-analysis." — an internal slug, not even a
// real word) — confirmed 2026-09-22 while checking the Overview->Summary
// rename actually reached every audio-command surface. Matches the English
// on-screen labels in i18n.ts; this component's other spoken messages are
// all English-hardcoded too; kept in sync with i18n.ts by hand.
const TAB_LABEL: Record<string, string> = {
  overview: "the summary",
  capture: "capture",
  ocr: "the OCR page",
  notes: "the notes",
  quiz: "the quiz",
  experiments: "the experiments",
  "missing-concepts": "opportunities",
  homework: "the homework",
  "class-analysis": "the classroom snapshot",
  "lesson-plan": "the lesson plan",
  "session-report": "the session report",
  tiqer: "TiQer",
  textbook: "the textbook",
  "guided-practice": "guided practice",
  "absorption-map": "the absorption map",
};

function speakableTabLabel(output: string): string {
  return TAB_LABEL[output] ?? output;
}

function sessionTabPath(sessionId: string, output: string | undefined): string {
  if (output && output !== "overview" && SESSION_TABS.includes(output)) {
    return `/sessions/${sessionId}/${output}`;
  }
  return `/sessions/${sessionId}`;
}

// intent -> the exact output_type key api.triggerGeneration expects (matches
// each page's own "Generate" button call 1:1 — see homework/lesson-plan/
// class-analysis/session-report/absorption-map pages).
const GENERATE_OUTPUT_BY_INTENT: Record<string, string> = {
  generate_notes: "notes",
  generate_quiz: "quiz",
  generate_summary: "summary",
  generate_experiments: "experiments",
  generate_homework: "homework",
  generate_lesson_plan: "lesson_plan_coverage",
  generate_class_analysis: "combined_analysis",
  generate_session_report: "session_report",
  generate_absorption_map: "absorption_map",
};

// Spoken/shown label for the outcomes above — only needed where the raw
// output_type key (e.g. "lesson_plan_coverage") isn't something a teacher
// would recognize as their own words.
const GENERATE_LABEL_BY_INTENT: Record<string, string> = {
  generate_lesson_plan: "the lesson plan",
  generate_class_analysis: "the class analysis",
  generate_session_report: "the session report",
  generate_absorption_map: "the absorption map",
};

type Phase = "idle" | "listening" | "processing" | "answered" | "error";

// True safety ceiling only — real commands normally stop via VAD (~1.4s
// after the teacher finishes speaking, see VAD_SILENCE_MS below), so this
// is rarely hit in the working case. Lowered from 15000: on hardware where
// the mic ends up capturing near-silence (e.g. contention with the Pi's
// own wake-word listener for the one physical microphone — see
// backend/app/services/wake_word_service.py), VAD's speech threshold never
// trips even once, so its silence countdown never starts either, and every
// failed attempt rode the full old ceiling before Whisper came back with
// "[BLANK_AUDIO]" — confirmed 2026-09-23 via two real Pi voice-command
// attempts that each took ~15.3-16.3s and transcribed to nothing. This
// doesn't fix that underlying mic contention, but it does make a failed
// capture fail fast instead of leaving the assistant looking stuck for 15s.
const MAX_RECORDING_MS = 9000;

// VAD (voice-activity detection) auto-stop thresholds — see startVisualizer.
// Empirical starting points, not measured against real classroom noise
// floors yet. VAD_SPEECH_THRESHOLD uses the same 0-1 `level` the orb's own
// animation is already driven by, so whatever makes the orb visibly pulse
// is roughly "speaking." VAD_SILENCE_MS is long enough to survive a
// natural mid-sentence pause without cutting the teacher off, short enough
// to feel faster than the old "say over" habit. Tune both after real
// on-device testing, same as other thresholds introduced this session
// (e.g. the wake-word cooldown).
const VAD_SPEECH_THRESHOLD = 0.12;
const VAD_SILENCE_MS = 1400;

// Minimal shape for the (non-standard, vendor-prefixed) Web Speech
// Recognition API — used ONLY to detect a spoken "over"/"done" stop-word
// alongside the recording; it never supplies the actual transcript (Whisper
// still does that, on the recorded audio). Note this is NOT on-device in
// Chrome — it streams audio to Google's speech recognition service over the
// network, a third cloud dependency distinct from both Qwen and OpenAI, and
// a real source of latency/reliability variance on a constrained connection.
interface SpeechRecognitionResultLike { isFinal: boolean; 0: { transcript: string } }
interface SpeechRecognitionEventLike { resultIndex: number; results: ArrayLike<SpeechRecognitionResultLike> }
interface SpeechRecognitionLike {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

// Matches "over" or "done" as the LAST word of an utterance (with optional
// trailing punctuation) — e.g. "create a physics session, over" matches,
// but "let's move it over to page five" does not (over isn't the last word).
// Only ever checked against FINALIZED recognizer segments (see startListening) —
// interim/live-updating text is never matched, specifically to avoid cutting
// a sentence off the instant it happens to contain "over" or "done" before
// the teacher has finished speaking.
const STOP_WORD_PATTERN = /\b(over|done)\s*[.,!]?\s*$/i;

function getSpeechRecognition(): SpeechRecognitionLike | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  return Ctor ? new Ctor() : null;
}

let voicesPromise: Promise<SpeechSynthesisVoice[]> | null = null;

function loadVoices(): Promise<SpeechSynthesisVoice[]> {
  if (typeof window === "undefined" || !window.speechSynthesis) return Promise.resolve([]);
  if (voicesPromise) return voicesPromise;
  voicesPromise = new Promise((resolve) => {
    const existing = window.speechSynthesis.getVoices();
    if (existing.length) { resolve(existing); return; }
    window.speechSynthesis.onvoiceschanged = () => resolve(window.speechSynthesis.getVoices());
    // Some browsers never fire onvoiceschanged if voices load synchronously later —
    // don't hang the first utterance waiting for it forever.
    setTimeout(() => resolve(window.speechSynthesis.getVoices()), 500);
  });
  return voicesPromise;
}

async function speakWithBrowser(text: string) {
  if (typeof window === "undefined" || !window.speechSynthesis) return;
  const utter = new SpeechSynthesisUtterance(text);
  const voices = await loadVoices();
  const indian = voices.find((v) => v.lang === "en-IN") ?? voices.find((v) => v.lang?.startsWith("en-IN"));
  const enFallback = voices.find((v) => v.lang?.startsWith("en"));
  const chosen = indian ?? enFallback;
  if (chosen) utter.voice = chosen;
  utter.rate = 0.95;
  utter.pitch = 1.0;
  window.speechSynthesis.speak(utter);
}

let currentAudio: HTMLAudioElement | null = null;

function stopSpeaking() {
  window.speechSynthesis?.cancel();
  if (currentAudio) { currentAudio.pause(); currentAudio = null; }
}

/** Backend OpenAI TTS first (natural voice, streamed — see api.streamSpeechToAudio), browser speechSynthesis as offline fallback. */
async function speak(text: string, onDone: () => void) {
  stopSpeaking();
  try {
    const audio = await api.streamSpeechToAudio(text);
    const url = audio.src;
    currentAudio = audio;
    audio.onended = () => { URL.revokeObjectURL(url); onDone(); };
    audio.onerror = () => { URL.revokeObjectURL(url); onDone(); };
    await audio.play();
  } catch {
    // Offline, or TTS call failed — fall back to the browser's own voice.
    await speakWithBrowser(text);
    const check = setInterval(() => {
      if (!window.speechSynthesis?.speaking) { clearInterval(check); onDone(); }
    }, 300);
  }
}

interface ActionOutcome {
  success: boolean;
  message: string;
  /** True for outcomes that navigate to another page (create_session, open_session) —
   * the full-screen overlay would otherwise sit on top of the page it just navigated
   * to, hiding it. These collapse to a small pill instead of staying full-screen. */
  navigatesAway?: boolean;
  /** Set for delete_session — identifies WHICH session was found, but doesn't
   * delete it yet. Renders Yes/No buttons instead of "Ask something else";
   * deletion only happens if the teacher taps Yes. */
  pendingDelete?: { sessionId: string; label: string };
}

export function ClassroomBrain() {
  const [open, setOpen] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  // Defaults on (was explicitly requested — no more tapping the mic every
  // time) but stays a real, persisted opt-out: an always-listening mic is a
  // reasonable thing for a teacher to want off. See the wake-word effect below.
  const [wakeWordEnabled, setWakeWordEnabledState] = useState(true);
  useEffect(() => {
    try {
      const saved = localStorage.getItem("classroom-brain:wake-word-enabled");
      if (saved !== null) setWakeWordEnabledState(saved === "true");
    } catch { /* localStorage unavailable — default stays on */ }
  }, []);
  const setWakeWordEnabled = useCallback((enabled: boolean) => {
    setWakeWordEnabledState(enabled);
    try { localStorage.setItem("classroom-brain:wake-word-enabled", String(enabled)); } catch { /* best-effort */ }
  }, []);
  const [phase, setPhase] = useState<Phase>("idle");
  const [transcript, setTranscript] = useState("");
  const [result, setResult] = useState<VoiceCommandResponse | null>(null);
  const [actionResult, setActionResult] = useState<ActionOutcome | null>(null);
  const [errorMsg, setErrorMsg] = useState("");

  const router = useRouter();
  const pathname = usePathname();
  const currentSessionId = pathname?.match(/\/sessions\/([0-9a-f-]{36})/i)?.[1] ?? null;
  const onCapturePage = !!pathname?.match(/\/sessions\/[0-9a-f-]{36}\/capture/i);
  const onGuidedPracticePage = !!pathname?.match(/\/sessions\/[0-9a-f-]{36}\/guided-practice/i);
  // The student-facing Guided Practice station device (a separate top-level
  // route, not under /sessions/[id]/... at all) — its own camera/pause/
  // record-answer controls, distinct from onGuidedPracticePage (the
  // teacher's dashboard of station cards).
  const onPracticeStationPage = !!pathname?.match(/^\/practice-station\//i);
  const onTeachingPage = !!pathname?.match(/\/sessions\/[0-9a-f-]{36}\/textbook\/[0-9a-f-]{36}\/[0-9a-f-]{36}/i);
  const onWelcomePage = pathname === "/welcome";
  // Every tab that actually has a "Download PDF" button wired up. Kept in
  // sync manually with the pages that call classroom-brain:download_pdf.
  const onPdfPage = !!pathname?.match(
    /\/sessions\/[0-9a-f-]{36}\/(notes|quiz|homework|class-analysis|lesson-plan)(\/|$)/i
  );

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  // The acquired mic stream, kept alive across multiple auto-relisten turns
  // (see startListening/stopStream) instead of being torn down after every
  // single recording — see the comment on stopStream for why.
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const maxTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Bumped on every startListening() call and on close — the async
  // transcribe→command→execute chain checks it before touching any shared
  // state. Without this, closing mid-cycle (or a wake-word retrigger firing
  // right after close) let an old, still-in-flight cycle's result land
  // AFTER a newer one and silently overwrite it with stale transcript/answer
  // text (reported 2026-09-22 — "still shows the last transcribed text").
  const cycleIdRef = useRef(0);

  const cleanupTimers = useCallback(() => {
    if (maxTimerRef.current) { clearTimeout(maxTimerRef.current); maxTimerRef.current = null; }
  }, []);

  // Audio-reactive orb: samples real mic amplitude and scales/glows the orb
  // in sync with the teacher's actual voice, via a ref-driven rAF loop
  // (never React state — a 60fps state update would be janky and wasteful).
  // The SAME loop doubles as voice-activity detection (VAD): once real
  // speech has been heard, a sustained stretch below the noise floor means
  // the teacher has stopped talking, so the recording auto-stops on its
  // own — no need to say "over"/"done" or wait out the max-duration
  // timeout. Both of those stay in place as fallbacks (a noisy classroom
  // that never reads as "silent," a stuck analyser) — VAD is an earlier,
  // faster path to the same stop, not a replacement for them.
  const orbRef = useRef<HTMLDivElement | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const rafRef = useRef<number | null>(null);

  const stopVisualizer = useCallback(() => {
    if (rafRef.current !== null) { cancelAnimationFrame(rafRef.current); rafRef.current = null; }
    if (audioCtxRef.current) { audioCtxRef.current.close().catch(() => {}); audioCtxRef.current = null; }
    if (orbRef.current) { orbRef.current.style.transform = "scale(1)"; orbRef.current.style.opacity = "0.55"; }
  }, []);

  const startVisualizer = useCallback((stream: MediaStream, onSilence?: () => void) => {
    try {
      const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const audioCtx = new Ctx();
      // By the time we get here, we're a couple of `await`s removed from
      // the click/wake-word event that started startListening() (pauses
      // the wake-word detector, then getUserMedia) — some browsers only
      // treat an AudioContext as pre-authorized to run when it's created
      // synchronously inside the original user-gesture handler, and start
      // it "suspended" otherwise. A suspended context returns all-zero
      // frequency data forever, which would make `level` never cross the
      // VAD speech threshold — confirmed 2026-09-17: real recordings were
      // running the full 15s hard timeout instead of VAD ever triggering.
      // resume() is a harmless no-op if the context was already running.
      audioCtx.resume().catch(() => {});
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      // 128 is the minimum FFT size the Web Audio API allows — this orb only
      // ever needs a rough amplitude reading for its pulse, not frequency
      // detail, so there's no reason to ask for more bins than that.
      analyser.fftSize = 128;
      source.connect(analyser);
      audioCtxRef.current = audioCtx;

      const data = new Uint8Array(analyser.frequencyBinCount);
      let hasSpoken = false;
      let silenceStartedAt: number | null = null;
      // The whole recording can run for several seconds, and this loop was
      // touching the DOM on every single animation frame (up to 60/s) for
      // that entire window — real, sustained main-thread work for as long
      // as a teacher is talking. On a resource-constrained device (the
      // classroom Pi) that's enough to visibly compete with cursor/input
      // handling, reported as the airmouse cursor lagging specifically
      // while recording. VAD still samples every frame (timing accuracy
      // matters there), but the orb's style is now only updated every 3rd
      // frame (~20fps) — visually indistinguishable for a soft pulse,
      // roughly a third of the DOM writes.
      let frameCount = 0;
      const tick = () => {
        analyser.getByteFrequencyData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) sum += data[i];
        const level = Math.min(1, (sum / data.length) / 60); // normalized 0-1
        frameCount++;
        if (orbRef.current && frameCount % 3 === 0) {
          orbRef.current.style.transform = `scale(${1 + level * 0.6})`;
          orbRef.current.style.opacity = String(0.55 + level * 0.45);
        }

        if (onSilence) {
          if (level > VAD_SPEECH_THRESHOLD) {
            hasSpoken = true;
            silenceStartedAt = null;
          } else if (hasSpoken) {
            // Only start the silence clock once real speech has actually
            // been heard — otherwise a quiet moment right after tapping
            // the mic (before the teacher has said anything) would
            // auto-stop a recording that never really started.
            if (silenceStartedAt === null) {
              silenceStartedAt = performance.now();
            } else if (performance.now() - silenceStartedAt >= VAD_SILENCE_MS) {
              onSilence();
              return; // stop this rAF loop — the resulting mr.stop() tears everything down
            }
          }
        }

        rafRef.current = requestAnimationFrame(tick);
      };
      tick();
    } catch {
      // No Web Audio support — orb just stays static. Recording itself is unaffected.
    }
  }, []);

  const stopStream = useCallback(() => {
    // The one place the mic is actually released back to the wake-word
    // detector. startListening() below keeps the underlying MediaStream
    // alive across multiple auto-relisten turns rather than reacquiring it
    // per turn — re-calling getUserMedia() from auto-relisten's trigger (a
    // TTS "playback ended" callback, not a click) turned out to be silently
    // refused by the Pi's kiosk Chromium, which — unlike a normal desktop
    // browser, and unlike the sandboxed pane this was verified in — only
    // grants getUserMedia() from inside a genuine user-gesture handler.
    // Reported 2026-09-22: the feature worked in every simulated test but
    // never actually reopened the mic on the real device. Call this
    // whenever a turn is NOT continuing into another auto-relisten cycle.
    const stream = streamRef.current;
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    api.resumeWakeWord().catch(() => {});
  }, []);

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  const stopRecognition = useCallback(() => {
    try { recognitionRef.current?.stop(); } catch { /* already stopped */ }
    recognitionRef.current = null;
  }, []);

  // ── Voice "take a photo" from off the capture page ─────────────────────────
  // capture_frame navigates to /capture?autostart=camera first (see
  // executeIntent below), but getUserMedia is async — the shutter can't fire
  // until CameraCapture's camState actually reaches "active". CameraCapture
  // broadcasts "classroom-brain:camera_ready" every time that happens (see
  // CameraCapture.tsx); we only act on it while a capture_frame is actually
  // pending, and time it out so a LATER, unrelated camera start (e.g. the
  // teacher manually stops and restarts it) can't fire a stale photo.
  const pendingCaptureFrameRef = useRef(false);
  const pendingCaptureTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearPendingCaptureFrame = useCallback(() => {
    pendingCaptureFrameRef.current = false;
    if (pendingCaptureTimeoutRef.current) { clearTimeout(pendingCaptureTimeoutRef.current); pendingCaptureTimeoutRef.current = null; }
  }, []);

  const armPendingCaptureFrame = useCallback(() => {
    pendingCaptureFrameRef.current = true;
    if (pendingCaptureTimeoutRef.current) clearTimeout(pendingCaptureTimeoutRef.current);
    // Generous timeout — covers navigation + getUserMedia's permission
    // prompt, not just the camera init itself. If it's never reached
    // (permission denied, teacher navigated elsewhere again), we just drop
    // the pending capture rather than firing it against the wrong page.
    pendingCaptureTimeoutRef.current = setTimeout(clearPendingCaptureFrame, 10000);
  }, [clearPendingCaptureFrame]);

  useEffect(() => {
    function onCameraReady() {
      if (!pendingCaptureFrameRef.current) return;
      clearPendingCaptureFrame();
      window.dispatchEvent(new CustomEvent("classroom-brain:capture_frame"));
    }
    window.addEventListener("classroom-brain:camera_ready", onCameraReady);
    return () => window.removeEventListener("classroom-brain:camera_ready", onCameraReady);
  }, [clearPendingCaptureFrame]);

  useEffect(() => () => clearPendingCaptureFrame(), [clearPendingCaptureFrame]);

  const executeIntent = useCallback(async (res: VoiceCommandResponse): Promise<ActionOutcome | null> => {
    const params = res.params as Record<string, unknown>;

    // Same wording ("generate notes"/"generate my notes") the teacher uses
    // for a whole session means something different from a student's own
    // device — the classifier can't and shouldn't try to tell those apart
    // from words alone (same reasoning as start_camera above), so this
    // checks onPracticeStationPage BEFORE the generic session-wide
    // handling below ever runs, same pattern as start_camera/stop_camera.
    if (onPracticeStationPage && (res.intent === "generate_notes" || res.intent === "generate_quiz")) {
      const kind = res.intent === "generate_notes" ? "notes" : "quiz";
      window.dispatchEvent(new CustomEvent(`classroom-brain:station_generate_${kind}`));
      return { success: true, message: `Generating ${kind} for this station now.` };
    }

    const outputType = GENERATE_OUTPUT_BY_INTENT[res.intent];
    if (outputType) {
      const label = GENERATE_LABEL_BY_INTENT[res.intent] ?? outputType;
      if (!currentSessionId) {
        return { success: false, message: `Open a session first, then ask me to generate ${label}.` };
      }
      try {
        await api.triggerGeneration(currentSessionId, [outputType]);
        return { success: true, message: `Got it — generating ${label} now.` };
      } catch {
        return { success: false, message: `I couldn't start generating ${label} — please use the on-screen button instead.` };
      }
    }

    if (res.intent === "generate_practice_questions") {
      if (!currentSessionId) {
        return { success: false, message: "Open a session first, then ask me to generate practice questions." };
      }
      // Was hardcoded to `3` and ignored subject/topic entirely, even though
      // the classifier already extracted them — "generate 5 questions" and
      // "generate questions for grade 5 on light" both silently did the
      // exact same plain 3-question board-OCR generation (reported
      // 2026-09-22). count comes back as a number OR a numeric string
      // depending on which model classified it — coerce either way, and
      // clamp to the same 1-10 range the backend itself enforces so a
      // clamped-server-side value doesn't read as "the count was ignored".
      const rawCount = Number(params.count);
      const count = Number.isFinite(rawCount) && rawCount > 0 ? Math.min(10, Math.max(1, Math.round(rawCount))) : 3;
      const subject = (params.subject as string) || "";
      const grade = (params.grade as string) || "";
      let topic = (params.topic as string) || "";
      if (topic && grade) topic = `${grade} — ${topic}`;
      try {
        if (subject && topic) {
          await api.generatePracticeQuestionsFromTopic(currentSessionId, subject, topic, count);
          return { success: true, message: `Got it — generating ${count} guided-practice question${count === 1 ? "" : "s"} on ${params.topic} now.` };
        }
        await api.generatePracticeQuestions(currentSessionId, count);
        return { success: true, message: `Got it — generating ${count} guided-practice question${count === 1 ? "" : "s"} now.` };
      } catch {
        return { success: false, message: "I couldn't start generating practice questions — open Guided Practice and use the on-screen button instead." };
      }
    }

    if (res.intent === "start_station_capture" || res.intent === "stop_station_capture") {
      const starting = res.intent === "start_station_capture";
      if (!onGuidedPracticePage) {
        return { success: false, message: "Open Guided Practice first, then ask me to start or stop a station's capture." };
      }
      const station = (params.station as string) || "";
      window.dispatchEvent(new CustomEvent(`classroom-brain:${res.intent}`, { detail: { station } }));
      return { success: true, message: starting ? "Starting capture." : "Stopping capture." };
    }

    if (res.intent === "create_station") {
      if (!onGuidedPracticePage) {
        return { success: false, message: "Open Guided Practice first, then ask me to create a station." };
      }
      const station = (params.station as string) || "";
      if (!station) {
        return { success: false, message: "Who's this station for? Try again with a name." };
      }
      window.dispatchEvent(new CustomEvent("classroom-brain:create_station", { detail: { station } }));
      return { success: true, message: `Creating a station for ${station}.` };
    }

    if (res.intent === "assign_question_to_station") {
      if (!onGuidedPracticePage) {
        return { success: false, message: "Open Guided Practice first, then ask me to assign a question." };
      }
      const station = (params.station as string) || "";
      const which = (params.which as string) || "";
      if (!station || !which) {
        return { success: false, message: "Tell me both which student and which question — for example, \"assign the second question to Aisha\"." };
      }
      window.dispatchEvent(new CustomEvent("classroom-brain:assign_question_to_station", { detail: { station, which } }));
      return { success: true, message: `Assigning that question to ${station}.` };
    }

    if (res.intent === "approve_question" || res.intent === "reject_question") {
      const approving = res.intent === "approve_question";
      if (!onGuidedPracticePage) {
        return { success: false, message: `Open Guided Practice first, then ask me to ${approving ? "approve" : "reject"} a question.` };
      }
      const which = (params.which as string) || "";
      if (!which) {
        return { success: false, message: `Which question — say "the first one", "1st and 2nd", or "all".` };
      }
      window.dispatchEvent(new CustomEvent(`classroom-brain:${res.intent}`, { detail: { which } }));
      return { success: true, message: approving ? "Approving now." : "Rejecting now." };
    }

    if (res.intent === "set_auto_capture") {
      if (!onCapturePage) {
        return { success: false, message: "Open the Capture page first, then ask me to set the auto-capture interval." };
      }
      const rawSeconds = Number(params.seconds);
      const allowed = [0, 5, 10, 20, 30, 60];
      const seconds = allowed.includes(rawSeconds)
        ? rawSeconds
        : allowed.reduce((closest, v) => Math.abs(v - rawSeconds) < Math.abs(closest - rawSeconds) ? v : closest, 0);
      window.dispatchEvent(new CustomEvent("classroom-brain:set_auto_capture", { detail: { seconds } }));
      return { success: true, message: seconds === 0 ? "Auto-capture off." : `Auto-capturing every ${seconds} seconds.` };
    }

    if (res.intent === "end_session") {
      if (!currentSessionId) {
        return { success: false, message: "Open a session first, then ask me to end it." };
      }
      try {
        await api.patchSession(currentSessionId, { status: "completed" });
        return { success: true, message: "Session ended." };
      } catch {
        return { success: false, message: "I couldn't end the session — please use the on-screen button instead." };
      }
    }

    if (res.intent === "delete_session") {
      if (params.not_found) {
        return { success: false, message: "I couldn't find a matching session to delete." };
      }
      if (params.not_authorized) {
        const label = (params.session_label as string) || "that session";
        return { success: false, message: `The ${label} isn't yours, so I can't delete it — only the teacher who created a session can delete it.` };
      }
      const sessionId = params.session_id as string | undefined;
      const label = (params.session_label as string) || "that session";
      if (!sessionId) return { success: false, message: "I couldn't find a matching session to delete." };
      // Never delete on the strength of one utterance — surface which
      // session was found and wait for an explicit Yes tap. It's a soft
      // delete on the backend, but the teacher doesn't know that, and a
      // misheard command deleting the wrong class would still be bad UX.
      return {
        success: true,
        message: `Delete the ${label} session? This can't be undone from here.`,
        pendingDelete: { sessionId, label },
      };
    }

    if (res.intent === "capture_frame") {
      if (onCapturePage) {
        window.dispatchEvent(new CustomEvent("classroom-brain:capture_frame"));
        return { success: true, message: "Capturing the board now." };
      }
      if (!currentSessionId) {
        return { success: false, message: "Open a session first, then ask me to take a photo." };
      }
      // Camera isn't up yet on this navigation — armPendingCaptureFrame fires
      // the actual shutter once CameraCapture reports it's live (see the
      // "classroom-brain:camera_ready" listener above).
      armPendingCaptureFrame();
      router.push(`/sessions/${currentSessionId}/capture?autostart=camera`);
      return { success: true, message: "Opening the capture screen — taking the photo in a moment.", navigatesAway: true };
    }

    if (res.intent === "start_camera") {
      if (onPracticeStationPage) {
        window.dispatchEvent(new CustomEvent("classroom-brain:station_start_camera"));
        return { success: true, message: "Starting the camera." };
      }
      if (onCapturePage) {
        window.dispatchEvent(new CustomEvent("classroom-brain:start_camera"));
        return { success: true, message: "Starting the camera." };
      }
      if (!currentSessionId) {
        return { success: false, message: "Open a session first, then ask me to start the camera." };
      }
      // ?autostart=camera IS the requested action here (CameraCapture starts
      // itself on mount) — no post-navigation event needed, unlike capture_frame.
      router.push(`/sessions/${currentSessionId}/capture?autostart=camera`);
      return { success: true, message: "Opening the capture screen and starting the camera.", navigatesAway: true };
    }

    if (res.intent === "stop_camera") {
      // The camera only ever runs while CameraCapture is mounted, i.e. while
      // already on /capture — off that page there's nothing running to stop,
      // so unlike the start intents this never navigates anywhere. The
      // practice-station page has no separate "stop camera" action of its
      // own (photo/tutor modes keep the camera running throughout) — only
      // start_camera and the pause/record intents apply there.
      if (!onCapturePage) {
        return { success: false, message: "The camera isn't running right now." };
      }
      window.dispatchEvent(new CustomEvent("classroom-brain:stop_camera"));
      return { success: true, message: "Stopping the camera." };
    }

    if (res.intent === "station_toggle_capture") {
      if (!onPracticeStationPage) {
        return { success: false, message: "Open your practice station first, then ask me to pause or resume." };
      }
      window.dispatchEvent(new CustomEvent("classroom-brain:station_toggle_capture"));
      return { success: true, message: "Got it." };
    }

    if (res.intent === "station_record_answer") {
      if (!onPracticeStationPage) {
        return { success: false, message: "Open your practice station first, then ask me to record your answer." };
      }
      window.dispatchEvent(new CustomEvent("classroom-brain:station_record_answer"));
      return { success: true, message: "Recording your answer — go ahead." };
    }

    if (res.intent === "reprocess_ocr") {
      if (!onCapturePage) {
        return { success: false, message: "Open the capture screen for a session first, then ask me to reprocess a photo." };
      }
      window.dispatchEvent(new CustomEvent("classroom-brain:reprocess_ocr"));
      return { success: true, message: "Reprocessing the last photo." };
    }

    if (res.intent === "start_recording") {
      const type = (params.type as string) === "video" ? "video" : "audio";
      if (onCapturePage) {
        window.dispatchEvent(new CustomEvent("classroom-brain:start_recording", { detail: { type } }));
        return { success: true, message: `Starting ${type} recording.` };
      }
      if (!currentSessionId) {
        return { success: false, message: "Open a session first, then ask me to record." };
      }
      // Same as start_camera: ?autostart=audio|video already starts the
      // recorder itself once the capture page mounts, so no follow-up event
      // is needed here (contrast with capture_frame's ready handshake).
      const qs = type === "video" ? "tab=video&autostart=video" : "autostart=audio";
      router.push(`/sessions/${currentSessionId}/capture?${qs}`);
      return { success: true, message: `Opening the capture screen and starting ${type} recording.`, navigatesAway: true };
    }

    if (res.intent === "stop_recording") {
      // Recording only ever runs while already on /capture (its state lives
      // in that page component) — off that page there's nothing to stop.
      if (!onCapturePage) {
        return { success: false, message: "Nothing is currently recording." };
      }
      const type = (params.type as string) === "video" ? "video" : "audio";
      window.dispatchEvent(new CustomEvent("classroom-brain:stop_recording", { detail: { type } }));
      return { success: true, message: `Stopping ${type} recording.` };
    }

    if (res.intent === "open_session") {
      if (params.not_found) {
        return { success: false, message: "I couldn't find a matching session." };
      }
      const sessionId = params.session_id as string | undefined;
      if (!sessionId) return { success: false, message: "I couldn't find a matching session." };
      const output = params.output as string | undefined;
      router.push(sessionTabPath(sessionId, output));
      return { success: true, message: output ? `Opening ${speakableTabLabel(output)}.` : "Opening that session.", navigatesAway: true };
    }

    if (res.intent === "view_tab") {
      if (!currentSessionId) {
        return { success: false, message: "Open a session first, then ask me to go to a specific tab." };
      }
      const output = params.output as string | undefined;
      router.push(sessionTabPath(currentSessionId, output));
      return { success: true, message: `Going to ${output ? speakableTabLabel(output) : "the summary"}.`, navigatesAway: true };
    }

    if (res.intent === "download_pdf") {
      if (!onPdfPage) {
        return { success: false, message: "Open the notes, quiz, homework, class analysis, or lesson plan page first, then ask me to download it." };
      }
      window.dispatchEvent(new CustomEvent("classroom-brain:download_pdf"));
      return { success: true, message: "Downloading the PDF now." };
    }

    if (res.intent === "start_teaching") {
      if (!currentSessionId) {
        return { success: false, message: "Open a session with a textbook attached first, then ask me to start a chapter." };
      }
      const chapterQuery = (params.chapter as string) || "";
      try {
        if (!chapterQuery && onTeachingPage) {
          // Already inside a chapter and no chapter was named — "continue"
          // here means advance to the next segment, not re-navigate to the
          // same URL (which would just reload, not actually move forward).
          window.dispatchEvent(new CustomEvent("classroom-brain:teaching_continue"));
          return { success: true, message: "Continuing." };
        }
        if (!chapterQuery) {
          // A bare "start"/"continue" with no chapter named — the on-screen
          // "Continue teaching" button (CommandCenter.tsx) doesn't call
          // locate_chapter for this either, because it can't: an empty
          // query has no words to score chapter titles against, so it
          // always 404'd here and told the teacher to "upload a textbook"
          // even though one was already right there, mid-lecture (reported
          // 2026-09-22). Resume the same way the button does — the most
          // recently-taught chapter — falling back to the very first
          // chapter of the first ready textbook if nothing's been started.
          const { textbooks } = await api.listTextbooks(currentSessionId);
          const hero = findHeroChapter(textbooks);
          let target = hero
            ? { textbook_id: hero.textbookId, chapter_id: hero.chapter.chapter_id, title: hero.chapter.title }
            : null;
          if (!target) {
            const first = textbooks
              .filter((tb) => tb.status === "ready")
              .flatMap((tb) => (tb.chapters ?? []).map((ch) => ({ tb, ch })))
              .sort((a, b) => a.ch.order_index - b.ch.order_index)[0];
            target = first ? { textbook_id: first.tb.textbook_id, chapter_id: first.ch.chapter_id, title: first.ch.title } : null;
          }
          if (!target) {
            return { success: false, message: "I couldn't find a textbook chapter to start — upload a textbook on the Textbook tab first." };
          }
          router.push(`/sessions/${currentSessionId}/textbook/${target.textbook_id}/${target.chapter_id}`);
          return { success: true, message: `${hero ? "Continuing" : "Starting"} the ${target.title} chapter.`, navigatesAway: true };
        }
        const match = await api.locateChapter(currentSessionId, chapterQuery);
        router.push(`/sessions/${currentSessionId}/textbook/${match.textbook_id}/${match.chapter_id}`);
        return { success: true, message: `Starting the ${match.title} chapter.`, navigatesAway: true };
      } catch (err) {
        // A textbook genuinely being uploaded/processed reads very
        // differently from none existing at all — collapsing both into
        // "upload a textbook first" told the teacher to do something
        // they'd already done (reported 2026-09-22: a PDF was visible on
        // the Textbook tab, still mid-processing, and the assistant said
        // it couldn't find an upload). See textbooks.py's locate_chapter
        // for the distinct error codes this now checks.
        const code = err instanceof APIError ? err.code : "";
        if (code === "TEXTBOOK_PROCESSING") {
          return { success: false, message: "Your textbook is still being processed — give it a moment and try again." };
        }
        if (code === "TEXTBOOK_FAILED") {
          return { success: false, message: "That textbook couldn't be processed — check the Textbook tab for details." };
        }
        return {
          success: false,
          message: chapterQuery
            ? `I couldn't find a chapter matching "${chapterQuery}" — check the Textbook tab to see what's uploaded.`
            : "I couldn't find a textbook chapter to start — upload a textbook on the Textbook tab first.",
        };
      }
    }

    if (res.intent === "check_understanding") {
      // Deliberately NOT auto-opening the quiz here (dispatching straight
      // to the same classroom-brain:check_understanding event the on-screen
      // button uses) — a voice command popping a question with no
      // confirmation read as "automatic" to a teacher even though it was
      // technically voice-triggered; reported 2026-09-24 as unwanted.
      // "Check understanding" now only ever opens from that explicit
      // on-screen tap, never from voice.
      if (!onTeachingPage) {
        return { success: false, message: "Open a chapter on the Textbook tab first, then tap \"Check understanding\" when you're ready." };
      }
      return { success: true, message: "Tap \"Check understanding\" on screen when you're ready to quiz the class." };
    }

    if (res.intent === "mute_audio" || res.intent === "unmute_audio") {
      if (!onTeachingPage) {
        return { success: false, message: "Open a chapter on the Textbook tab first — that's where the narration plays." };
      }
      const muted = res.intent === "mute_audio";
      window.dispatchEvent(new CustomEvent("classroom-brain:set_muted", { detail: { muted } }));
      return { success: true, message: muted ? "Audio muted." : "Audio back on." };
    }

    // Welcome/attendance flow (frontend/src/app/welcome/page.tsx) — each
    // event is a no-op there unless the matching step is actually active
    // (see that file's own listeners), so saying e.g. "see summary" before
    // attendance is done just doesn't do anything rather than erroring.
    if (
      res.intent === "welcome_begin" || res.intent === "welcome_take_attendance" ||
      res.intent === "welcome_see_summary" || res.intent === "welcome_go_to_dashboard"
    ) {
      if (!onWelcomePage) {
        return { success: false, message: "That's only available on the welcome screen." };
      }
      window.dispatchEvent(new CustomEvent(`classroom-brain:${res.intent}`));
      const WELCOME_INTENT_MESSAGE: Record<string, string> = {
        welcome_begin: "Let's get started.",
        welcome_take_attendance: "Taking attendance.",
        welcome_see_summary: "Here's the summary.",
        welcome_go_to_dashboard: "Heading to the dashboard.",
      };
      return { success: true, message: WELCOME_INTENT_MESSAGE[res.intent] };
    }

    return null; // not an intent we execute
    // onGuidedPracticePage was missing here (2026-09-25): navigating between
    // two session sub-pages that don't change currentSessionId/onCapturePage/
    // onPdfPage/onTeachingPage/onWelcomePage (e.g. session home ->
    // guided-practice) never recreated this callback, so the closure kept
    // whatever onGuidedPracticePage was at the last recreation — stale
    // false, making every guided-practice-gated intent (start/stop/create
    // station, approve/reject question) wrongly report "Open Guided
    // Practice first" while the teacher was already looking at it.
  }, [router, currentSessionId, onCapturePage, onGuidedPracticePage, onPracticeStationPage, onPdfPage, onTeachingPage, onWelcomePage, armPendingCaptureFrame]);

  const startListening = useCallback(async () => {
    const myCycleId = ++cycleIdRef.current;
    setErrorMsg("");
    setResult(null);
    setActionResult(null);
    setTranscript("");
    setPhase("listening");

    try {
      // Reuse the already-granted stream when one's still live (an
      // auto-relisten continuing the same conversation) instead of asking
      // for the mic again — see stopStream's comment for why a fresh
      // getUserMedia() call here would silently fail on the Pi. Only a
      // genuinely fresh open (first tap, wake word, or after the stream was
      // released) goes through the full acquisition below.
      let stream = streamRef.current;
      const streamIsLive = !!stream && stream.getAudioTracks().some((t) => t.readyState === "live");
      if (!streamIsLive) {
        // The backend's "Hey XP" detector holds the Pi's only microphone
        // continuously — asking it to step aside BEFORE requesting our own
        // mic access avoids the two fighting over the same hardware, which
        // otherwise broke voice commands entirely (not just wake-word
        // detection), confirmed 2026-09-16. A no-op (resolves immediately)
        // when wake word is disabled or unreachable, and best-effort either
        // way — a failure here shouldn't block a teacher from recording.
        await api.pauseWakeWord().catch(() => {});

        // Explicit constraints (not just `audio: true`) so noise suppression /
        // echo cancellation / auto-gain are requested consistently across
        // different mic hardware (built-in, USB, Bluetooth) rather than
        // relying on each browser's/device's default — relevant for a noisy
        // classroom with other students talking in the background.
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
          video: false,
        });
        streamRef.current = stream;
      }
      if (!stream) throw new Error("no mic stream"); // unreachable — satisfies the type checker
      const liveStream = stream;
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";
      const mr = new MediaRecorder(liveStream, { mimeType });
      chunksRef.current = [];
      mr.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };

      mr.onstop = async () => {
        // NOTE: deliberately does NOT stop the stream's tracks or resume
        // the wake word here anymore — the stream now stays live across
        // auto-relisten turns (see stopStream). Every path below that
        // ISN'T continuing into another startListening() call explicitly
        // calls stopStream() itself once it's genuinely done.
        cleanupTimers();
        stopVisualizer();
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        // Bail if a newer cycle has already started (teacher closed and
        // reopened, or the wake word retriggered right after close) — this
        // cycle's result is stale and must not touch any shared state.
        if (cycleIdRef.current !== myCycleId) return;
        setPhase("processing");

        // A separate /voice/transcribe call used to run first so the
        // transcript could show up early, during the "processing" spinner,
        // before the slower intent-classification step. Cut (2026-09-22) —
        // it cost a whole extra sequential network round trip for a purely
        // cosmetic early preview, on a path already measured to take up to
        // ~10s end to end. /voice/command already transcribes internally
        // when no transcript_hint is given, so this is now one call instead
        // of two; the transcript still appears, just alongside the answer
        // once everything resolves (result.transcript, "answered" phase)
        // rather than a beat earlier.
        try {
          const res = await api.voiceCommand(blob, "command.webm");
          if (cycleIdRef.current !== myCycleId) return;
          setResult(res);
          setTranscript(res.transcript);

          // create_session used to hand off to a step-by-step wizard asking
          // subject/grade/topic/instructor before creating anything — now
          // creates immediately with whatever was said (often nothing) and
          // jumps straight to capture. Subject/topic no longer need to be
          // known upfront at all: the backend auto-fills them from the
          // first photo's OCR text once the teacher starts capturing (see
          // _detect_subject_and_topic in ocr_service.py). Anything wrong or
          // still blank stays editable from the session page afterward.
          if (res.intent === "create_session") {
            const p = res.params as Record<string, unknown>;
            await createSessionFromVoice({
              subject: (p.subject as string) || "",
              grade: (p.grade as string) || "",
              title: (p.title as string) || "",
              instructorName: (p.author as string) || "",
            }, myCycleId);
            return;
          }

          const outcome = await executeIntent(res);
          if (cycleIdRef.current !== myCycleId) return;
          setActionResult(outcome);
          setPhase("answered");
          // A pending delete needs its Yes/No buttons clearly visible, not
          // tucked into the small pill — always show the full view for it.
          if (outcome?.pendingDelete) setMinimized(false);

          // Auto-relisten after a command that actually succeeded — "every
          // audio command needs a fresh mic tap" was the single most-repeated
          // complaint this project has gotten (2026-09-22). Hooked here, not
          // as a general timer, because this callback only ever runs after
          // speak() has played a REAL answer — a command that failed to
          // classify or came back with an empty transcript never reaches
          // speak() at all (see the `!res.transcript` branch below), so a
          // silent/noisy room can never bounce into an endless auto-relisten
          // loop on its own: the chain breaks the moment one turn comes back
          // with nothing to say. Applies even after a navigating outcome
          // (generate notes, go to a tab, start teaching a chapter, etc.) —
          // ClassroomBrain is mounted once in (dashboard)/layout.tsx, a
          // shared layout that persists across client-side navigation
          // between every one of these pages, so this component (and the
          // held mic stream) is still very much alive on the other side of
          // a router.push(); reported 2026-09-22 that the mic re-tap was
          // back specifically after navigating commands, which is exactly
          // what an earlier, over-cautious "might be gone by now" guard
          // here was causing. Skipped only when a stale cycle (the teacher
          // closed the panel, or tapped the mic again manually, while the
          // answer was still being spoken) has already superseded this one.
          function relistenIfStillCurrent() {
            if (cycleIdRef.current === myCycleId) startListening();
          }

          if (outcome) {
            // Navigating outcomes (create/open session) collapse to a small
            // pill once spoken, so the full-screen overlay stops hiding the
            // page it just navigated to — listening then continues from
            // that compact pill rather than the full-screen view.
            speak(outcome.message, () => {
              if (outcome.navigatesAway) setMinimized(true);
              // A pending delete is only ever confirmed by tapping the
              // on-screen Yes/No buttons (voice "yes"/"no" isn't wired to
              // it — deliberately, for a destructive action) — reopening
              // the mic here would just listen into a dead end.
              if (outcome.pendingDelete) { stopStream(); return; }
              relistenIfStillCurrent();
            });
          } else if (res.brain_answer?.answer) {
            speak(res.brain_answer.answer, relistenIfStillCurrent);
          } else if (!res.transcript) {
            setErrorMsg("I didn't catch that — try again.");
            stopStream();
          } else {
            // A real transcript came back, but the classified intent wasn't
            // one executeIntent handles (returned null) and there was no
            // Brain-chat answer either — a genuinely unbuilt/unrecognized
            // command. Previously this fell through all three branches
            // silently: no message set, nothing spoken, no relisten/
            // stopStream — from the teacher's side that looked exactly like
            // the assistant collapsing back to its icon having done nothing
            // (reported 2026-09-25: "silently revert back to classroom
            // brain icon without telling what happened"). Give it the same
            // clear, spoken, visible-in-the-pill treatment every other
            // outcome gets instead of just going quiet.
            const notBuilt: ActionOutcome = {
              success: false,
              message: "I'm not built to do that yet — try a different command.",
            };
            setActionResult(notBuilt);
            speak(notBuilt.message, relistenIfStillCurrent);
          }
        } catch {
          if (cycleIdRef.current !== myCycleId) return;
          setPhase("error");
          setErrorMsg("Couldn't reach the assistant. Check the connection and try again.");
          stopStream();
        }
      };

      mr.start();
      mediaRecorderRef.current = mr;
      startVisualizer(liveStream, () => stopListening());
      maxTimerRef.current = setTimeout(() => {
        if (mr.state !== "inactive") mr.stop();
      }, MAX_RECORDING_MS);

      // Optional: spoken "over" / "done" as an alternative to tapping the
      // Done button. Purely a stop trigger — Whisper (on the actual
      // recorded audio) still produces the real transcript used for the
      // command. Feature-detected: silently absent on browsers without
      // SpeechRecognition (e.g. some Safari versions), where tap-to-stop
      // and the max-duration timeout are the only ways to stop, same as before.
      const recognition = getSpeechRecognition();
      if (recognition) {
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.lang = "en-US";
        recognition.onresult = (event) => {
          for (let i = event.resultIndex; i < event.results.length; i++) {
            const r = event.results[i];
            // Chrome's SpeechRecognition can take 1-3+ seconds of trailing
            // silence before flagging a result isFinal, even though the
            // interim text already has the right words — that wait was the
            // whole "says over, nothing happens for 4-5s" complaint. Safe to
            // act on interim text here because it's ONLY ever used to decide
            // *when* to stop recording — the actual command transcript
            // always comes from Whisper on the real recorded audio, never
            // from this API, so a slightly-eager trigger can't corrupt it.
            if (STOP_WORD_PATTERN.test(r[0].transcript.trim())) {
              stopListening();
              return;
            }
          }
        };
        recognition.onerror = () => { /* non-fatal — Done button still works */ };
        recognition.onend = null;
        recognitionRef.current = recognition;
        try { recognition.start(); } catch { recognitionRef.current = null; }
      }
    } catch {
      setPhase("error");
      setErrorMsg("Microphone access denied or unavailable.");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cleanupTimers, executeIntent, startVisualizer, stopVisualizer, stopStream]);

  const stopListening = useCallback(() => {
    stopRecognition();
    const mr = mediaRecorderRef.current;
    if (mr && mr.state !== "inactive") mr.stop();
  }, [stopRecognition]);

  const handleOpen = useCallback(() => {
    // Start in the compact bottom-right window, not the full-screen
    // overlay — the full-screen takeover on every single interaction was
    // the actual complaint; the pill already shows listening/transcript/
    // processing state just fine, so there's no functional loss here,
    // only an explicit "maximize" to opt into the bigger view (see
    // reopenFromMinimized below).
    setOpen(true);
    setMinimized(true);
    startListening();
  }, [startListening]);

  // ── Wake word: ambient "Hey XP" listener ──────────────────────────────────
  // Detection runs on the BACKEND (openWakeWord) — see src/hooks/useWakeWord.ts
  // for why. Only active while the assistant itself is closed (it has its
  // own mic use, and there'd be nothing useful to open it into anyway).
  const { status: wakeWordStatus, error: wakeWordError } = useWakeWord({
    enabled: wakeWordEnabled && !open,
    onWake: handleOpen,
  });

  const handleClose = useCallback(() => {
    // Bump the cycle id first — stopStream() below triggers the recorder's
    // native "stop" event, which runs the SAME onstop pipeline (transcribe
    // → command → execute) as a normal stop; this makes sure that pipeline
    // sees itself as already-superseded and skips straight past its own
    // state updates instead of resurrecting them after close.
    cycleIdRef.current += 1;
    cleanupTimers();
    stopStream();
    stopRecognition();
    stopVisualizer();
    stopSpeaking();
    setOpen(false);
    setMinimized(false);
    setShowHelp(false);
    setPhase("idle");
    setResult(null);
    setTranscript("");
  }, [cleanupTimers, stopStream, stopRecognition, stopVisualizer]);

  const reopenFromMinimized = useCallback(() => {
    setMinimized(false);
    // Only start a NEW recording when there's nothing already in flight —
    // if the teacher taps the pill while it's actively listening or
    // processing, that's a "maximize" (show the same in-progress state
    // bigger), not "start over". Restarting would cut off whatever was
    // already being recorded.
    if (phase !== "listening" && phase !== "processing") {
      startListening();
    }
  }, [startListening, phase]);

  /** Mic button on the minimized pill — records the next command right there
   * without expanding to the full-screen overlay, so the page underneath
   * (e.g. the tab just navigated to) stays visible the whole time. */
  const listenInline = useCallback(() => {
    stopSpeaking();
    setTimeout(startListening, 250);
  }, [startListening]);

  const createSessionFromVoice = useCallback(async (
    result: { subject: string; grade: string; title: string; instructorName: string },
    myCycleId: number,
  ) => {
    try {
      const created = await api.createSession({
        teacher_id: DEV_TEACHER_ID,
        subject: result.subject || null,
        grade: result.grade || null,
        title: result.title || null,
        instructor_name: result.instructorName || null,
        board_type: "chalkboard",
        capture_mode: "time_based",
        capture_interval_sec: 30,
        classroom_id: null,
        client_session_id: generateUUID(),
      });
      if (cycleIdRef.current !== myCycleId) return;
      router.push(`/sessions/${created.session_id}/capture`);
      const outcome = { success: true, message: result.title || result.subject
        ? `Starting your ${result.title || result.subject} session — capture the board whenever you're ready.`
        : "Starting your session — capture the board whenever you're ready.", navigatesAway: true };
      setActionResult(outcome);
      setPhase("answered");
      // Same reasoning as the main navigatesAway branch above — this
      // component lives in the shared (dashboard) layout and survives the
      // router.push() to the new session, so it's safe (and expected) to
      // keep listening right on the page the teacher just landed on.
      speak(outcome.message, () => { setMinimized(true); if (cycleIdRef.current === myCycleId) startListening(); });
    } catch {
      if (cycleIdRef.current !== myCycleId) return;
      const outcome = { success: false, message: "I couldn't create the session — please try the on-screen button." };
      setActionResult(outcome);
      setPhase("answered");
      // Didn't navigate anywhere (creation failed), so — same as every other
      // non-navigating answered turn — let the teacher just try again by
      // voice instead of having to tap the mic.
      speak(outcome.message, () => { if (cycleIdRef.current === myCycleId) startListening(); });
    }
  }, [router, speak, startListening]);

  const confirmDelete = useCallback(async () => {
    const pending = actionResult?.pendingDelete;
    if (!pending) return;
    try {
      await api.deleteSession(pending.sessionId);
      // If the teacher was looking at the session that just got deleted,
      // its page would 404 underneath — send them back to the list instead.
      if (currentSessionId === pending.sessionId) router.push("/sessions");
      const outcome: ActionOutcome = { success: true, message: `Deleted the ${pending.label} session.` };
      setActionResult(outcome);
      speak(outcome.message, () => {});
    } catch {
      const outcome: ActionOutcome = { success: false, message: "I couldn't delete that session — please try the on-screen button." };
      setActionResult(outcome);
      speak(outcome.message, () => {});
    }
  }, [actionResult, currentSessionId, router]);

  const cancelDelete = useCallback(() => {
    const outcome: ActionOutcome = { success: true, message: "Okay, kept it." };
    setActionResult(outcome);
    speak(outcome.message, () => {});
  }, []);

  const askAgain = useCallback(() => {
    stopSpeaking();
    // Brief settle delay before opening the mic again — starting a new
    // recording the instant playback is paused risks the mic picking up
    // the tail of the previous answer's audio (speaker bleed into mic,
    // especially on a laptop where they're close together), which can
    // garble the next transcript with leftover words from the last answer.
    setTimeout(startListening, 250);
  }, [startListening]);

  useEffect(() => () => { cleanupTimers(); stopStream(); stopRecognition(); stopVisualizer(); stopSpeaking(); }, [cleanupTimers, stopStream, stopRecognition, stopVisualizer]);


  if (minimized) {
    const pillText =
      phase === "listening" ? "Listening…"
      : phase === "processing" ? (transcript ? `“${transcript}”` : "Thinking…")
      : actionResult?.message ?? result?.brain_answer?.answer ?? "Classroom Brain";

    return (
      <div className="brain-fade-in fixed bottom-6 right-6 z-40 flex max-w-sm items-center gap-2.5 rounded-full border border-white/10 bg-slate-900/95 py-2.5 pl-5 pr-2.5 text-base text-slate-200 shadow-xl backdrop-blur">
        <button
          onClick={reopenFromMinimized}
          aria-label="Expand Classroom Brain assistant"
          className="flex min-w-0 items-center gap-2.5 hover:text-white"
        >
          {phase === "listening" ? (
            <span className="relative flex h-5 w-5 shrink-0 items-center justify-center">
              <span className="absolute h-5 w-5 animate-ping rounded-full bg-indigo-400/50" />
              <Mic className="relative h-5 w-5 text-indigo-400" />
            </span>
          ) : phase === "processing" ? (
            <div className="h-5 w-5 shrink-0 animate-spin rounded-full border-2 border-indigo-500/30 border-t-indigo-400" />
          ) : (
            <Brain className="h-5 w-5 shrink-0 text-indigo-400" />
          )}
          <span className="truncate">{pillText}</span>
        </button>

        {/* Buttons in this pill (mic/maximize/close) are sized up from the
            original 28px — small adjacent targets in a tight cluster are
            exactly what's hardest to hit precisely with an airmouse cursor. */}
        {phase === "listening" ? (
          <button
            onClick={stopListening}
            aria-label="Stop and send"
            className="shrink-0 rounded-full border border-white/20 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/10"
          >
            Done
          </button>
        ) : phase !== "processing" ? (
          <button
            onClick={listenInline}
            aria-label="Ask a follow-up without leaving this page"
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-white/10 text-indigo-300 transition hover:bg-white/20 hover:text-white"
          >
            <Mic className="h-5 w-5" />
          </button>
        ) : null}

        <button
          onClick={reopenFromMinimized}
          aria-label="Maximize"
          title="Maximize"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-slate-500 transition hover:bg-white/10 hover:text-white"
        >
          <Maximize2 className="h-5 w-5" />
        </button>

        <button
          onClick={handleClose}
          aria-label="Close"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-slate-500 transition hover:bg-white/10 hover:text-white"
        >
          <X className="h-5 w-5" />
        </button>
      </div>
    );
  }

  if (!open) {
    return (
      <button
        onClick={() => handleOpen()}
        aria-label="Open Classroom Brain assistant"
        // Sized well above a typical touch target (56px -> 80px) — this is
        // the one control that has to be reliably hittable with an airmouse
        // cursor across a classroom, where precise pointing is much harder
        // than with a mouse or a finger on a touchscreen.
        className="brain-breathe fixed bottom-6 right-6 z-40 flex h-20 w-20 items-center justify-center rounded-full bg-gradient-to-br from-indigo-600 to-violet-600 text-white shadow-lg shadow-indigo-600/40 transition hover:scale-105 hover:shadow-xl active:scale-95"
      >
        <Brain className="h-9 w-9" />
      </button>
    );
  }

  const clarifying = result?.brain_answer?.needs_clarification;

  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center overflow-hidden bg-slate-950 backdrop-blur-sm">
      <style>{`
        @keyframes brain-fade-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes brain-breathe { 0%, 100% { box-shadow: 0 0 0 0 rgba(99,102,241,0.5); } 50% { box-shadow: 0 0 0 10px rgba(99,102,241,0); } }
        @keyframes brain-drift { 0%, 100% { transform: translate(-10%, -10%) scale(1); } 50% { transform: translate(10%, 5%) scale(1.15); } }
        .brain-breathe { animation: brain-breathe 2.6s ease-in-out infinite; }
        .brain-fade-in { animation: brain-fade-in 0.35s ease-out; }
      `}</style>

      {/* Ambient drifting glow — purely decorative, gives the overlay a living background instead of flat dark */}
      <div className="pointer-events-none absolute left-1/2 top-[85%] h-56 w-56 -translate-x-1/2 -translate-y-1/2 rounded-full bg-indigo-600/8 blur-2xl [animation:brain-drift_9s_ease-in-out_infinite]" />

      <button
        onClick={() => setShowHelp((v) => !v)}
        aria-label="Show example commands"
        className={`absolute left-6 top-6 z-10 flex h-12 w-12 items-center justify-center rounded-full transition hover:bg-white/10 ${showHelp ? "bg-white/10 text-white" : "text-slate-400 hover:text-white"}`}
      >
        <HelpCircle className="h-6 w-6" />
      </button>

      <button
        onClick={handleClose}
        aria-label="Close"
        className="absolute right-6 top-6 z-10 flex h-12 w-12 items-center justify-center rounded-full text-slate-400 transition hover:bg-white/10 hover:text-white"
      >
        <X className="h-6 w-6" />
      </button>

      {showHelp && (
        <div className="brain-fade-in absolute left-6 top-20 z-10 w-72 rounded-2xl border border-white/10 bg-slate-900/95 p-4 text-left shadow-xl">
          <label className="mb-1 flex items-center justify-between gap-3 rounded-lg bg-white/5 px-3 py-2.5 text-left">
            <span className="min-w-0">
              <span className="block text-sm font-medium text-white">Always listen for &quot;Hey XP&quot;</span>
              <span className="block text-[0.6875rem] text-slate-400">Opens hands-free — no need to tap the mic</span>
            </span>
            <input
              type="checkbox"
              checked={wakeWordEnabled}
              onChange={(e) => setWakeWordEnabled(e.target.checked)}
              className="h-5 w-9 shrink-0 cursor-pointer appearance-none rounded-full bg-slate-600 transition-colors checked:bg-indigo-500 relative
                         before:absolute before:left-0.5 before:top-0.5 before:h-4 before:w-4 before:rounded-full before:bg-white before:transition-transform
                         checked:before:translate-x-4"
            />
          </label>
          {wakeWordEnabled && wakeWordStatus === "error" && (
            <p className="mb-4 px-3 text-[0.6875rem] text-amber-400">{wakeWordError ?? "Wake word isn't reachable — tap the mic instead."}</p>
          )}
          {wakeWordEnabled && wakeWordStatus === "listening" && (
            <p className="mb-4 px-3 text-[0.6875rem] text-slate-500">Listening now.</p>
          )}
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-indigo-300">Things you can say</p>
          <div className="flex flex-col gap-3">
            {SAMPLE_COMMANDS.map((g) => (
              <div key={g.group}>
                <p className="mb-1 text-[0.6875rem] font-medium text-slate-500">{g.group}</p>
                <ul className="flex flex-col gap-1">
                  {g.examples.map((ex) => (
                    <li key={ex} className="text-sm text-slate-300">{ex}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="relative z-10 flex w-full max-w-xl flex-col items-center gap-6 px-6 text-center">
        {(phase === "listening" || phase === "idle") && (
          <div key="listening" className="brain-fade-in flex flex-col items-center gap-6">
            <div className="relative flex h-32 w-32 items-center justify-center">
              <div
                ref={orbRef}
                className="absolute h-24 w-24 rounded-full bg-gradient-to-br from-indigo-400 to-violet-500 blur-md transition-transform duration-75 ease-out"
                style={{ opacity: 0.55 }}
              />
              <div className="relative flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-lg shadow-indigo-500/50">
                <Mic className="h-7 w-7" />
              </div>
            </div>
            <p className="text-lg font-medium text-white">Listening…</p>
            <p className="text-xs text-slate-500">Say &quot;over&quot; when you&apos;re done, or tap below</p>
            <button
              onClick={stopListening}
              className="rounded-full border border-white/20 bg-white/10 px-8 py-3.5 text-base font-medium text-white transition hover:bg-white/20 active:scale-95"
            >
              Done
            </button>
          </div>
        )}

        {phase === "processing" && (
          <div key="processing" className="brain-fade-in flex flex-col items-center gap-4">
            <div className="flex h-16 w-16 items-center justify-center">
              <div className="h-10 w-10 animate-spin rounded-full border-4 border-indigo-500/30 border-t-indigo-400" />
            </div>
            {transcript ? (
              <>
                <p className="text-base italic text-slate-400">&quot;{transcript}&quot;</p>
                <p className="text-sm text-slate-500">Thinking…</p>
              </>
            ) : (
              <p className="text-lg font-medium text-white">Understanding…</p>
            )}
          </div>
        )}

        {phase === "answered" && result && (
          <div key="answered" className="brain-fade-in flex w-full flex-col items-center gap-4">
            {result.transcript && (
              <p className="text-sm italic text-slate-400">&quot;{result.transcript}&quot;</p>
            )}

            {actionResult ? (
              <p className={actionResult.success ? "text-xl leading-relaxed text-white" : "text-lg text-amber-300"}>
                {actionResult.message}
              </p>
            ) : result.brain_answer ? (
              <>
                {clarifying && (
                  <div className="flex items-center gap-2 text-amber-300">
                    <HelpCircle className="h-5 w-5" />
                    <span className="text-xs font-medium uppercase tracking-wide">Quick question</span>
                  </div>
                )}
                <p className="text-xl leading-relaxed text-white">{result.brain_answer.answer}</p>
                {!clarifying && (
                  <div className="flex flex-wrap justify-center gap-2 pt-2">
                    {result.brain_answer.pending_concepts.length > 0 && (
                      <span className="rounded-full bg-amber-500/15 px-3 py-1 text-xs text-amber-300">
                        Pending: {result.brain_answer.pending_concepts.slice(0, 3).join(", ")}
                      </span>
                    )}
                    {result.brain_answer.suggested_next && (
                      <span className="rounded-full bg-emerald-500/15 px-3 py-1 text-xs text-emerald-300">
                        Next: {result.brain_answer.suggested_next}
                      </span>
                    )}
                    <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-slate-400">
                      {result.brain_answer.source === "local" ? "Answered offline" : "Answered online"}
                    </span>
                  </div>
                )}
              </>
            ) : result.intent !== "unknown" && result.intent !== "ask_question" ? (
              <p className="text-lg text-white">
                Got it — I understood <span className="font-semibold text-indigo-300">{result.intent.replace(/_/g, " ")}</span>.
                <br />
                <span className="text-sm text-slate-400">(Executing this action isn&apos;t available yet — for now, please use the on-screen controls.)</span>
              </p>
            ) : (
              <p className="text-lg text-slate-300">{errorMsg || "I didn't quite catch that — try again."}</p>
            )}

            {actionResult?.pendingDelete ? (
              <div className="mt-4 flex gap-3">
                <button
                  onClick={cancelDelete}
                  className="rounded-full border border-white/20 px-5 py-2 text-sm text-slate-200 transition hover:bg-white/10"
                >
                  No, keep it
                </button>
                <button
                  onClick={confirmDelete}
                  className="rounded-full bg-red-600 px-5 py-2 text-sm font-medium text-white shadow-lg shadow-red-600/30 transition hover:scale-105"
                >
                  Yes, delete
                </button>
              </div>
            ) : (
              <button
                onClick={askAgain}
                className="mt-4 rounded-full bg-gradient-to-br from-indigo-600 to-violet-600 px-6 py-2.5 text-sm font-medium text-white shadow-lg shadow-indigo-600/30 transition hover:scale-105"
              >
                {clarifying ? "Answer" : "Ask something else"}
              </button>
            )}
          </div>
        )}

        {phase === "error" && (
          <div key="error" className="brain-fade-in flex flex-col items-center gap-4">
            <p className="text-lg text-red-300">{errorMsg}</p>
            <button
              onClick={askAgain}
              className="rounded-full border border-white/20 px-5 py-2 text-sm text-slate-200 transition hover:bg-white/10"
            >
              Try again
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
