"use client";

/**
 * Records a spoken answer to a guided-practice question — the audio
 * counterpart to CameraSnapButton, for theory/conceptual questions where
 * there's no handwritten work to photograph (the student reasons out loud
 * instead of writing in a notebook).
 *
 * Auto-stops on silence (same VAD approach as ClassroomBrain.tsx's voice
 * assistant — an AnalyserNode threshold + sustained-silence timer) and
 * submits immediately, no separate "stop" or "confirm" tap required.
 *
 * Every piece of state that matters is shown ON SCREEN, not just logged to
 * the console (2026-09-17): debugging this on a kiosk device with no easy
 * DevTools access kept stalling on "I can't tell what's happening" — a
 * visible mic-level meter, a live status line, and any live-preview error
 * text mean the person testing this can just describe what they SEE,
 * without needing a console at all.
 */

import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { Mic, Square, Loader2, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";

type RecState = "idle" | "requesting" | "recording" | "submitting" | "error";

// Imperative trigger for a voice command ("record my answer") to start
// THIS specific button's recording — a plain onClick prop won't do, since
// the caller (e.g. ClassroomBrain, via a page-level CustomEvent listener)
// needs to reach into one particular instance, not simulate a click.
// Deliberately NOT a self-contained `window.addEventListener` inside this
// component: GuidedPracticeClassicView/PremiumView render one
// VoiceAnswerButton per question row, so a global event would fire every
// mounted instance at once (every station's "Speak" button) instead of
// just the one the student is actually looking at — the caller must pick
// which instance via its own ref.
export type VoiceAnswerButtonHandle = { startRecording: () => void };

// Same tuned values as ClassroomBrain.tsx's startVisualizer — a shorter
// silence window here caused real accuracy problems there (cut speech off
// mid-sentence), so this reuses the same, already-corrected numbers rather
// than re-guessing.
const VAD_SPEECH_THRESHOLD = 0.12;
const VAD_SILENCE_MS = 1400;
// Hard backstop if VAD never fires (e.g. sustained background noise) — a
// spoken answer can reasonably run much longer than a voice command, so
// this is generous, not a tight cap.
const MAX_RECORDING_MS = 90_000;

// Whisper has no true streaming/partial-result API — this isn't word-by-word
// live transcription, it's re-transcribing the WHOLE growing recording on a
// timer so text visibly appears soon after the student starts talking,
// instead of dead silence until they stop. Real cost: each tick is a full
// Whisper call, so a 60s answer at this interval is ~20 extra calls versus
// the one call the eventual real submission makes. It's a pure preview
// either way, never wired into what actually gets validated.
const LIVE_TRANSCRIBE_INTERVAL_MS = 3000;

export const VoiceAnswerButton = forwardRef<VoiceAnswerButtonHandle, {
  onCapture: (blob: Blob) => void | Promise<void>;
  label?: string;
  size?: "sm" | "md" | "lg";
}>(function VoiceAnswerButton({
  onCapture, label = "Speak your answer", size = "sm",
}, ref) {
  const [state, setState] = useState<RecState>("idle");
  const [errorMsg, setErrorMsg] = useState("");
  const [elapsedSec, setElapsedSec] = useState(0);
  const [liveTranscript, setLiveTranscript] = useState("");
  const [previewError, setPreviewError] = useState("");
  const [level, setLevel] = useState(0); // 0-1, visible mic-level meter
  const [hasSpokenUi, setHasSpokenUi] = useState(false); // mirrors the VAD loop's own hasSpoken, for on-screen status only
  const [audioCtxState, setAudioCtxState] = useState(""); // "running"/"suspended"/"closed" — shown on screen, see the resume() comment below

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  // setInterval, not requestAnimationFrame — see the VAD tick() comment
  // below for why (rAF throttling was found 2026-09-25 to silently freeze
  // useVoiceConversation.ts's identical VAD loop; this component has the
  // same rAF-based pattern and the same exposure, just never reported here
  // specifically since it defaults to the 90s MAX_RECORDING_MS ceiling
  // instead of an obviously-wrong "always catches nothing").
  const vadTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const liveTranscribeRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const maxTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const transcribingRef = useRef(false); // guards against overlapping live-preview calls

  const teardown = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (vadTimerRef.current !== null) { clearInterval(vadTimerRef.current); vadTimerRef.current = null; }
    if (audioCtxRef.current) { audioCtxRef.current.close().catch(() => {}); audioCtxRef.current = null; }
    if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null; }
    if (liveTranscribeRef.current) { clearInterval(liveTranscribeRef.current); liveTranscribeRef.current = null; }
    if (maxTimerRef.current) { clearTimeout(maxTimerRef.current); maxTimerRef.current = null; }
    // The wake-word detector and this button compete for the Pi's one
    // physical microphone (see wake_word_service.py) — this was never
    // paused/resumed around recording at all until 2026-09-25, unlike
    // ClassroomBrain.tsx's own mic use and useVoiceConversation.ts (the AI
    // Tutor's hook), both of which already do this. Best-effort: a failed
    // resume shouldn't block tearing the rest of this down.
    api.resumeWakeWord().catch(() => {});
  }, []);

  useEffect(() => () => teardown(), [teardown]);

  function stopRecording() {
    const mr = mediaRecorderRef.current;
    if (mr && mr.state !== "inactive") mr.stop();
  }

  const startRecording = useCallback(async () => {
    setState("requesting");
    setErrorMsg("");
    setLiveTranscript("");
    setPreviewError("");
    setLevel(0);
    setHasSpokenUi(false);

    // Created FIRST, synchronously, before any await — a browser's autoplay
    // policy can suspend an AudioContext created even one microtask removed
    // from the original click, and that suspension makes getByteFrequencyData
    // return all-zero forever regardless of real mic input (confirmed
    // 2026-09-17: the level meter stayed completely flat, never moving even
    // while speaking — the earlier fix of calling .resume() on a
    // late-created context wasn't enough here). Creating it in the exact
    // same synchronous tick as the click handler gives the browser the best
    // chance of treating this as gesture-initiated and never suspending it
    // in the first place, rather than trying to un-suspend it after the fact.
    let audioCtx: AudioContext | null = null;
    try {
      const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      audioCtx = new Ctx();
      audioCtx.resume().catch(() => {});
    } catch {
      // No Web Audio support at all — VAD/level-meter won't work, but
      // tap-to-stop and the MAX_RECORDING_MS backstop still do.
    }

    try {
      await api.pauseWakeWord().catch(() => {});
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      streamRef.current = stream;
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";
      const mr = new MediaRecorder(stream, { mimeType });
      chunksRef.current = [];
      mr.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      mr.onstop = async () => {
        teardown();
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        setState("submitting");
        try {
          await onCapture(blob);
        } finally {
          setState("idle");
        }
      };
      // 1000ms timeslice: MediaRecorder.start() with NO argument only ever
      // fires ondataavailable ONCE, right when .stop() is called — without
      // this, chunksRef stays empty the whole time you're talking, so the
      // live-transcribe preview below would never have anything to send.
      mr.start(1000);
      mediaRecorderRef.current = mr;
      setElapsedSec(0);
      tickRef.current = setInterval(() => setElapsedSec((s) => s + 1), 1000);
      maxTimerRef.current = setTimeout(stopRecording, MAX_RECORDING_MS);

      liveTranscribeRef.current = setInterval(async () => {
        if (transcribingRef.current || chunksRef.current.length === 0) return;
        transcribingRef.current = true;
        try {
          const soFar = new Blob(chunksRef.current, { type: "audio/webm" });
          const { transcript } = await api.voiceTranscribe(soFar, "partial.webm");
          setPreviewError("");
          if (transcript.trim()) setLiveTranscript(transcript.trim());
        } catch (err) {
          // Surfaced on screen, not just swallowed — if this is ALWAYS
          // failing (bad API key, network, wrong endpoint), you'll see
          // exactly that here instead of just "no text ever appears" with
          // no clue why.
          setPreviewError(err instanceof Error ? err.message : "preview check failed");
        } finally {
          transcribingRef.current = false;
        }
      }, LIVE_TRANSCRIBE_INTERVAL_MS);

      // VAD auto-stop — same pattern as ClassroomBrain.tsx's startVisualizer,
      // using the AudioContext created synchronously at the top of this
      // function (see comment there) rather than a fresh one here.
      try {
        if (!audioCtx) throw new Error("no AudioContext available");
        audioCtx.resume().catch(() => {}); // harmless no-op if already running; cheap extra attempt
        const source = audioCtx.createMediaStreamSource(stream);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);
        audioCtxRef.current = audioCtx;

        const data = new Uint8Array(analyser.frequencyBinCount);
        let hasSpoken = false;
        let silenceStartedAt: number | null = null;
        let lastCtxStateCheck = 0;
        // setInterval, not requestAnimationFrame — confirmed 2026-09-25 in
        // useVoiceConversation.ts (the AI Tutor's identical VAD pattern)
        // that rAF-based polling is throttled/suspended by the browser
        // based on rendering/visibility state, which silently stopped the
        // silence timer from ever advancing and made every recording run
        // to the full MAX_RECORDING_MS regardless of real speech. Same
        // risk here — a student looking down at their notebook rather
        // than the screen is exactly the "not painting" state rAF gets
        // throttled under. ~20Hz (50ms) is far more than this needs.
        const tick = () => {
          analyser.getByteFrequencyData(data);
          let sum = 0;
          for (let i = 0; i < data.length; i++) sum += data[i];
          const lvl = Math.min(1, (sum / data.length) / 60);
          setLevel(lvl);

          // Cheap poll, not an event — AudioContext has no statechange-only
          // API worth wiring here for a value that only matters while
          // debugging. If this ever reads "suspended" on screen, the level
          // meter being stuck at 0 is explained: a suspended context always
          // returns all-zero frequency data, regardless of real mic input.
          const now = performance.now();
          if (now - lastCtxStateCheck > 500) {
            lastCtxStateCheck = now;
            setAudioCtxState(audioCtx.state);
          }

          if (lvl > VAD_SPEECH_THRESHOLD) {
            if (!hasSpoken) setHasSpokenUi(true);
            hasSpoken = true;
            silenceStartedAt = null;
          } else if (hasSpoken) {
            if (silenceStartedAt === null) {
              silenceStartedAt = performance.now();
            } else if (performance.now() - silenceStartedAt >= VAD_SILENCE_MS) {
              if (vadTimerRef.current !== null) { clearInterval(vadTimerRef.current); vadTimerRef.current = null; }
              stopRecording();
            }
          }
        };
        vadTimerRef.current = setInterval(tick, 50);
      } catch {
        // No Web Audio support — VAD just doesn't run; tap-to-stop and the
        // MAX_RECORDING_MS backstop still work. The level meter just won't move.
      }

      setState("recording");
    } catch (err) {
      // If getUserMedia itself failed, audioCtx was created above but never
      // handed to audioCtxRef (that only happens on the success path) — close
      // it directly here so it doesn't leak.
      if (audioCtx && audioCtxRef.current !== audioCtx) audioCtx.close().catch(() => {});
      setState("error");
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMsg(/Permission|NotAllowed|denied/i.test(msg)
        ? "Microphone permission denied."
        : "No microphone available.");
    }
  }, [teardown]);

  useImperativeHandle(ref, () => ({
    // idle-only: a voice command re-triggering an already-active/submitting
    // recording would just restart it mid-answer, which is never useful.
    startRecording: () => { if (state === "idle") startRecording(); },
  }), [state, startRecording]);

  if (state === "recording") {
    return (
      <div className="flex flex-col gap-1.5 w-full max-w-xs">
        <button
          type="button"
          onClick={stopRecording}
          className="flex items-center gap-1.5 rounded-lg bg-red-600 px-3 py-1.5 text-xs font-semibold text-white animate-pulse"
        >
          <Square className="h-3.5 w-3.5" /> Listening… {elapsedSec}s (tap to submit now)
        </button>

        {/* Visible mic-level meter — if this never moves when you talk,
            the mic isn't picking anything up. No console needed to see that. */}
        <div className="h-2 w-full rounded-full bg-slate-200 overflow-hidden">
          <div
            className="h-full bg-emerald-500 transition-all duration-75"
            style={{ width: `${Math.round(level * 100)}%` }}
          />
        </div>
        <p className="text-[0.6875rem] text-slate-500">
          {hasSpokenUi ? "Heard you — pause when you're done." : "Waiting to hear you speak…"}
          {audioCtxState && (
            <span className={audioCtxState === "running" ? "text-slate-400" : "font-semibold text-red-500"}>
              {" "}(audio: {audioCtxState})
            </span>
          )}
        </p>

        {liveTranscript && (
          <p className="text-[0.6875rem] italic text-slate-400">"{liveTranscript}"</p>
        )}
        {previewError && (
          <p className="text-[0.6875rem] text-red-500">Preview check failed: {previewError}</p>
        )}
      </div>
    );
  }

  if (state === "submitting") {
    return (
      <span className="flex items-center gap-1.5 rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-500">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Checking your answer…
      </span>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <Button size={size} loading={state === "requesting"} onClick={startRecording}>
        <Mic className="h-3.5 w-3.5" /> {label}
      </Button>
      {state === "error" && (
        <span className="flex items-center gap-1 text-[0.6875rem] text-red-500">
          <AlertTriangle className="h-3 w-3" /> {errorMsg}
        </span>
      )}
    </div>
  );
});
VoiceAnswerButton.displayName = "VoiceAnswerButton";
