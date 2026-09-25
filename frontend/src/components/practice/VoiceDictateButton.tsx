"use client";

/**
 * A mic button that records a short voice note and transcribes it via the
 * same cloud Whisper endpoint the Classroom Brain assistant uses
 * (api.voiceTranscribe) — lets a teacher speak an instruction to a student
 * instead of typing it. Tap to start, tap again to stop (or it auto-stops
 * after MAX_RECORDING_MS), then hands the transcript to the caller, which
 * decides where it goes (fill a field, append to one, etc).
 */

import { useCallback, useRef, useState } from "react";
import { Mic, Square, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const MAX_RECORDING_MS = 20000;

type State = "idle" | "recording" | "transcribing" | "error";

export function VoiceDictateButton({
  onTranscript, title = "Speak instead of typing",
}: {
  onTranscript: (text: string) => void;
  title?: string;
}) {
  const [state, setState] = useState<State>("idle");
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const maxTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stop = useCallback(() => {
    const mr = mediaRecorderRef.current;
    if (mr && mr.state !== "inactive") mr.stop();
  }, []);

  const start = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus" : "audio/webm";
      const mr = new MediaRecorder(stream, { mimeType });
      chunksRef.current = [];
      mr.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        if (maxTimerRef.current) { clearTimeout(maxTimerRef.current); maxTimerRef.current = null; }
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        setState("transcribing");
        try {
          const { transcript } = await api.voiceTranscribe(blob, "note.webm");
          if (transcript.trim()) onTranscript(transcript.trim());
        } catch {
          /* transcription failed — teacher can just try again or type instead */
        } finally {
          setState("idle");
        }
      };
      mr.start();
      mediaRecorderRef.current = mr;
      maxTimerRef.current = setTimeout(stop, MAX_RECORDING_MS);
      setState("recording");
    } catch {
      setState("error");
      setTimeout(() => setState("idle"), 2000);
    }
  }, [stop]);

  return (
    <button
      type="button"
      title={state === "recording" ? "Tap to stop" : title}
      onClick={() => (state === "recording" ? stop() : state === "idle" ? start() : undefined)}
      disabled={state === "transcribing"}
      className={cn(
        "flex items-center justify-center rounded-lg p-1.5 transition-colors shrink-0",
        state === "recording" ? "bg-red-500 text-white animate-pulse" :
        state === "error" ? "bg-red-100 text-red-600" :
        "bg-slate-50 border border-slate-200 text-slate-500 hover:bg-slate-100"
      )}
    >
      {state === "transcribing" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> :
       state === "recording" ? <Square className="h-3.5 w-3.5" /> :
       <Mic className="h-3.5 w-3.5" />}
    </button>
  );
}
