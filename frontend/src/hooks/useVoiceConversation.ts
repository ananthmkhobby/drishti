"use client";

/**
 * Record-until-silence, hand the blob to a caller-supplied handler, repeat —
 * the VAD (voice-activity detection) + MediaRecorder pattern proven in
 * ClassroomBrain.tsx, extracted so Guided Practice's AI Tutor (Learning
 * mode) doesn't become a THIRD copy of it (it's already duplicated once in
 * VoiceAnswerButton.tsx). Built by following ClassroomBrain's implementation
 * rather than refactoring ClassroomBrain to use this hook — that component's
 * version has been carefully tuned and re-verified multiple times and isn't
 * worth destabilizing for this change; unifying every call site onto one
 * hook is a reasonable follow-up, not part of this one.
 *
 * Preserves two hardware-specific fixes discovered the hard way on the
 * classroom Pi (both documented in ClassroomBrain.tsx, dated 2026-09-16/17):
 *  - The underlying MediaStream is kept alive across repeated
 *    startListening() calls rather than re-acquired each time — a fresh
 *    getUserMedia() call from anything other than a genuine user-gesture
 *    handler (e.g. a "TTS finished playing" callback, not a click) is
 *    silently refused by the Pi's kiosk Chromium.
 *  - The AudioContext is explicitly .resume()d — otherwise some browsers
 *    leave it "suspended" this many `await`s removed from the original
 *    gesture, which makes the VAD's level reading stay at zero forever.
 *
 * Does NOT auto-relisten on its own — same control-flow shape as
 * ClassroomBrain: the caller decides when to call startListening() again
 * (typically after TTS playback of a reply has finished), not this hook.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

const VAD_SPEECH_THRESHOLD = 0.12;
// Deliberately longer than ClassroomBrain.tsx's own 1400ms — that value was
// tuned for short, deliberate single-word/short-phrase voice COMMANDS. A
// real conversational follow-up question is longer and more likely to
// contain a brief natural thinking pause mid-sentence; at 1400ms that pause
// alone could stop the recording early, mid-question, producing a reply to
// a truncated thought — and then capturing the rest of what the student
// was still saying as a SECOND, immediate follow-up turn. Two replies that
// close together, one interrupting the other's playback, is exactly what
// got reported as "dual voice" (2026-09-24) — this alone won't rule out
// genuine acoustic echo, but it removes a real, mundane way to trigger it.
const VAD_SILENCE_MS = 1800;
// Same safety-ceiling reasoning as ClassroomBrain.tsx's MAX_RECORDING_MS
// (lowered from 15000 there on 2026-09-23) — a real turn normally stops via
// VAD shortly after the student finishes speaking, so this is rarely hit.
const MAX_RECORDING_MS = 9000;

export type VoiceConversationState = "idle" | "listening" | "processing";

export function useVoiceConversation({
  onRecording,
  pauseWakeWord = true,
}: {
  /** Called once per completed recording with the audio blob. Awaited —
   * `state` stays "processing" until this resolves (or rejects). */
  onRecording: (blob: Blob) => Promise<void> | void;
  /** Pause/resume the Pi's background wake-word listener around each
   * acquisition — the wake-word detector holds the Pi's one physical
   * microphone continuously, and letting it fight this hook for the same
   * hardware breaks BOTH (see wake_word_service.py). Default on; only
   * turn off if the caller already handles this itself. */
  pauseWakeWord?: boolean;
}) {
  const [state, setState] = useState<VoiceConversationState>("idle");
  const [level, setLevel] = useState(0); // 0-1 amplitude, for a UI pulse

  const streamRef = useRef<MediaStream | null>(null);
  const mrRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const maxTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  // setInterval, not requestAnimationFrame — see startVisualizer's own
  // comment for why (rAF throttling was found to silently freeze the
  // VAD's silence timer, 2026-09-25).
  const vadTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const cycleIdRef = useRef(0);
  const onRecordingRef = useRef(onRecording);
  onRecordingRef.current = onRecording;

  const cleanupTimers = useCallback(() => {
    if (maxTimerRef.current) { clearTimeout(maxTimerRef.current); maxTimerRef.current = null; }
  }, []);

  const stopVisualizer = useCallback(() => {
    if (vadTimerRef.current !== null) { clearInterval(vadTimerRef.current); vadTimerRef.current = null; }
    if (audioCtxRef.current) { audioCtxRef.current.close().catch(() => {}); audioCtxRef.current = null; }
    setLevel(0);
  }, []);

  const startVisualizer = useCallback((stream: MediaStream, onSilence: () => void) => {
    try {
      const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const audioCtx = new Ctx();
      audioCtx.resume().catch(() => {});
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 128;
      source.connect(analyser);
      audioCtxRef.current = audioCtx;

      const data = new Uint8Array(analyser.frequencyBinCount);
      let hasSpoken = false;
      let silenceStartedAt: number | null = null;
      let frameCount = 0;
      // setInterval, not requestAnimationFrame — confirmed via real usage
      // (2026-09-25) that rAF-based polling was letting every single
      // recording run to the full MAX_RECORDING_MS safety ceiling instead
      // of ever stopping early via silence detection, DESPITE the mic
      // genuinely picking up real speech (the level meter moved
      // correctly). rAF is throttled/suspended by the browser based on
      // rendering/visibility state — exactly the kind of thing that
      // doesn't apply while a student is looking down at their notebook
      // rather than the screen. VAD has nothing to do with rendering; it
      // should keep running on its own clock regardless of what's
      // currently painted. ~20Hz (50ms) is far more than this needs.
      const tick = () => {
        analyser.getByteFrequencyData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) sum += data[i];
        const lvl = Math.min(1, (sum / data.length) / 60);
        frameCount++;
        if (frameCount % 2 === 0) setLevel(lvl);

        if (lvl > VAD_SPEECH_THRESHOLD) {
          hasSpoken = true;
          silenceStartedAt = null;
        } else if (hasSpoken) {
          if (silenceStartedAt === null) {
            silenceStartedAt = performance.now();
          } else if (performance.now() - silenceStartedAt >= VAD_SILENCE_MS) {
            if (vadTimerRef.current !== null) { clearInterval(vadTimerRef.current); vadTimerRef.current = null; }
            onSilence();
          }
        }
      };
      vadTimerRef.current = setInterval(tick, 50);
    } catch {
      // No Web Audio support — recording still works, just no VAD auto-stop
      // (the MAX_RECORDING_MS ceiling still applies).
    }
  }, []);

  const stopStream = useCallback(() => {
    const stream = streamRef.current;
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (pauseWakeWord) api.resumeWakeWord().catch(() => {});
  }, [pauseWakeWord]);

  const startListening = useCallback(async () => {
    // Re-entrancy guard: if a previous cycle's recorder is somehow still
    // active when this is called again (e.g. called twice in close
    // succession — a real, confirmed way this could happen: TTS firing
    // BOTH onended and onerror for the same playback schedules two
    // separate relisten calls), stop it and detach its handler BEFORE
    // starting a new one. Without this, two live MediaRecorder instances
    // end up recording the same stream at once, each eventually completing
    // and each independently triggering its own reply — which is exactly
    // what "dual voice" sounds like from the student's side, even though
    // each individual reply is a normal, single Audio element (reported
    // 2026-09-24, most likely to show up on a longer follow-up question
    // where there's more time for this kind of double-trigger to occur).
    const prevMr = mrRef.current;
    if (prevMr && prevMr.state !== "inactive") {
      prevMr.onstop = null; // don't let the abandoned recorder fire its own onRecording
      prevMr.stop();
    }
    cleanupTimers();
    stopVisualizer();

    const myCycleId = ++cycleIdRef.current;
    setState("listening");
    try {
      let stream = streamRef.current;
      const streamIsLive = !!stream && stream.getAudioTracks().some((t) => t.readyState === "live");
      if (!streamIsLive) {
        if (pauseWakeWord) await api.pauseWakeWord().catch(() => {});
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
          video: false,
        });
        streamRef.current = stream;
      }
      // Non-null: either the existing stream was confirmed live above, or
      // getUserMedia just resolved (it always resolves with a stream or
      // rejects, never resolves null) — TS just can't follow that through
      // the conditional reassignment.
      const liveStream = stream!;
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus" : "audio/webm";
      const mr = new MediaRecorder(liveStream, { mimeType });
      mrRef.current = mr;
      chunksRef.current = [];
      mr.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      mr.onstop = async () => {
        cleanupTimers();
        stopVisualizer();
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        if (cycleIdRef.current !== myCycleId) return; // superseded by a newer cycle
        setState("processing");
        try {
          await onRecordingRef.current(blob);
        } finally {
          if (cycleIdRef.current === myCycleId) setState("idle");
        }
      };
      mr.start();
      startVisualizer(liveStream, () => { if (mr.state !== "inactive") mr.stop(); });
      maxTimerRef.current = setTimeout(() => {
        if (mr.state !== "inactive") mr.stop();
      }, MAX_RECORDING_MS);
    } catch (err) {
      if (cycleIdRef.current === myCycleId) setState("idle");
      throw err;
    }
  }, [pauseWakeWord, cleanupTimers, stopVisualizer, startVisualizer]);

  /** Stops the current recording early (e.g. a "Done" tap) without tearing
   * the stream down — still fires onRecording with whatever was captured. */
  const stopListening = useCallback(() => {
    const mr = mrRef.current;
    if (mr && mr.state !== "inactive") mr.stop();
  }, []);

  /** Fully tears everything down — stream released, wake word resumed, no
   * pending onRecording fires. Call on unmount or when leaving the
   * conversation entirely (not between turns). */
  const teardown = useCallback(() => {
    cycleIdRef.current += 1; // invalidate any in-flight cycle first
    cleanupTimers();
    stopVisualizer();
    const mr = mrRef.current;
    if (mr && mr.state !== "inactive") { mr.onstop = null; mr.stop(); }
    stopStream();
    setState("idle");
  }, [cleanupTimers, stopVisualizer, stopStream]);

  useEffect(() => teardown, [teardown]);

  return { state, level, startListening, stopListening, teardown };
}
