"use client";

import { useCallback, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { AudienceFrameResponse, ZoneData } from "@/lib/api";

export type AudienceState  = "off" | "loading" | "active" | "error";
export type CameraFacing   = "user" | "environment";
export type Emotion        = "happy" | "confused" | "surprised" | "disengaged" | "neutral";

export interface EmotionBreakdown {
  happy:      number;
  confused:   number;
  surprised:  number;
  disengaged: number;
  neutral:    number;
}

export interface AudienceLiveStats {
  facesDetected:   number;
  attentionPct:    number;
  handRaises:      number;
  minuteNumber:    number;
  dominantEmotion: Emotion;
  emotions:        EmotionBreakdown;
}

// Re-export for capture page consumers that import from this hook
export type { ZoneData };

// Near-real-time: analyse a frame every 10 s. The backend upserts by
// minute_number, so the DB still holds one row per minute (latest capture
// in that minute wins) while the live overlay refreshes every capture.
const CAPTURE_INTERVAL_MS = 10_000;

const ZONE_COLORS: Record<string, string> = {
  front:  "#22c55e",
  middle: "#f59e0b",
  back:   "#ef4444",
};

const ZERO_EMOTIONS: EmotionBreakdown = {
  happy: 0, confused: 0, surprised: 0, disengaged: 0, neutral: 0,
};

// ── Canvas overlay: draw per-face bounding boxes from backend response ─────────
function drawFaceBoxes(
  canvas: HTMLCanvasElement,
  video:  HTMLVideoElement,
  result: AudienceFrameResponse,
) {
  const vw = video.videoWidth  || canvas.offsetWidth  || 640;
  const vh = video.videoHeight || canvas.offsetHeight || 480;

  if (canvas.width !== vw || canvas.height !== vh) {
    canvas.width  = vw;
    canvas.height = vh;
  }

  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  for (const face of result.faces) {
    const { x, y, w, h } = face.box;
    const color = ZONE_COLORS[face.zone] ?? "#94a3b8";
    const label = `${face.zone.charAt(0).toUpperCase()} ${face.emotion}`;

    // Bounding box
    ctx.strokeStyle = color;
    ctx.lineWidth   = 1.5;
    ctx.globalAlpha = face.attentive ? 0.75 : 0.35;
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, 4);
    ctx.stroke();
    ctx.globalAlpha = 1;

    // Label badge above the box
    const fontSize = Math.max(9, Math.min(12, h * 0.20));
    ctx.font = `bold ${fontSize}px system-ui, sans-serif`;
    const tw = ctx.measureText(label).width;
    const bw = tw + 8;
    const bh = fontSize + 5;
    const bx = x;
    const by = Math.max(0, y - bh - 2);

    ctx.globalAlpha = face.attentive ? 0.80 : 0.45;
    ctx.fillStyle   = "rgba(0,0,0,0.65)";
    ctx.beginPath();
    ctx.roundRect(bx, by, bw, bh, 3);
    ctx.fill();
    ctx.globalAlpha = 1;

    ctx.fillStyle    = "white";
    ctx.textAlign    = "left";
    ctx.textBaseline = "middle";
    ctx.fillText(label, bx + 4, by + bh / 2);
  }
}

// ────────────────────────────────────────────────────────────────────────────────

export function useAudienceAnalyser(sessionId: string) {
  const [state,     setState]     = useState<AudienceState>("off");
  const [errorMsg,  setErrorMsg]  = useState<string>("");
  const [facing,    setFacing]    = useState<CameraFacing>("user");
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState<string>("");
  const [zoneStats, setZoneStats] = useState<ZoneData | null>(null);
  const [liveStats, setLiveStats] = useState<AudienceLiveStats>({
    facesDetected: 0, attentionPct: 0, handRaises: 0, minuteNumber: 1,
    dominantEmotion: "neutral", emotions: { ...ZERO_EMOTIONS },
  });

  const videoRef     = useRef<HTMLVideoElement | null>(null);
  const canvasRef    = useRef<HTMLCanvasElement | null>(null);
  const streamRef    = useRef<MediaStream | null>(null);
  const captureTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedAtRef = useRef(0);
  const facingRef    = useRef<CameraFacing>("user");

  // ── Capture current video frame → POST to backend → update stats ────────────
  async function captureAndAnalyse() {
    const video  = videoRef.current;
    if (!video || video.readyState < 2 || video.videoWidth === 0) return;

    setAnalyzing(true);
    // Minute derives from elapsed time, so multiple captures within the same
    // minute upsert the same backend row.
    const minute = Math.max(1, Math.floor((Date.now() - startedAtRef.current) / 60_000) + 1);

    // Render the current frame into a temporary canvas, then export as JPEG
    const snap   = document.createElement("canvas");
    snap.width   = video.videoWidth;
    snap.height  = video.videoHeight;
    const snapCtx = snap.getContext("2d");
    if (!snapCtx) { setAnalyzing(false); return; }
    snapCtx.drawImage(video, 0, 0);

    try {
      const blob = await new Promise<Blob | null>((resolve) =>
        snap.toBlob(resolve, "image/jpeg", 0.85)
      );
      if (!blob) return;

      const result = await api.postAudienceFrame(sessionId, blob, minute);

      setLiveStats({
        facesDetected:   result.faces_detected,
        attentionPct:    Math.round(result.attention_pct),
        handRaises:      0,
        minuteNumber:    result.minute_number,
        dominantEmotion: (result.dominant_emotion as Emotion) ?? "neutral",
        emotions: {
          happy:      Math.round(result.emotion_breakdown.happy),
          confused:   Math.round(result.emotion_breakdown.confused),
          surprised:  Math.round(result.emotion_breakdown.surprised),
          disengaged: Math.round(result.emotion_breakdown.disengaged),
          neutral:    Math.round(result.emotion_breakdown.neutral),
        },
      });
      setZoneStats(result.zone_summary);
      setAnalysisError("");

      if (canvasRef.current && video) {
        drawFaceBoxes(canvasRef.current, video, result);
      }
    } catch (err) {
      // Network / server failure — keep the loop running but surface it in the UI
      const msg = err instanceof Error ? err.message : "Network error";
      setAnalysisError(msg.slice(0, 100));
    } finally {
      setAnalyzing(false);
    }
  }

  // ── Open camera stream ────────────────────────────────────────────────────────
  async function startStream(f: CameraFacing) {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: f, width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false,
    });
    streamRef.current = stream;
    const video = videoRef.current;
    if (video) {
      video.srcObject = stream;
      await video.play().catch(() => {});
    }
    return stream;
  }

  // ── Start ─────────────────────────────────────────────────────────────────────
  const start = useCallback(async (initialFacing: CameraFacing = "user") => {
    if (state !== "off" && state !== "error") return;
    setState("loading");
    setErrorMsg("");
    facingRef.current = initialFacing;
    setFacing(initialFacing);

    try {
      await startStream(initialFacing);

      startedAtRef.current = Date.now();

      // Give the camera 2 s to stabilise, then fire the first analysis immediately
      // so the teacher sees results without waiting for the first interval tick.
      setTimeout(() => { captureAndAnalyse(); }, 2000);
      captureTimer.current = setInterval(captureAndAnalyse, CAPTURE_INTERVAL_MS);

      setState("active");
    } catch (err) {
      streamRef.current?.getTracks().forEach((t) => t.stop());
      const msg = err instanceof Error ? err.message : "Unknown error";
      setErrorMsg(
        msg.includes("Permission") || msg.includes("NotAllowed")
          ? "Camera permission denied — allow camera access in browser settings"
          : msg.includes("NotFound") || msg.includes("DevicesNotFound")
          ? "No camera found on this device"
          : msg.includes("NotReadable") || msg.includes("TrackStart")
          ? "Camera is in use by another app"
          : `Failed to start: ${msg.slice(0, 80)}`
      );
      setState("error");
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, sessionId]);

  // ── Flip camera ───────────────────────────────────────────────────────────────
  const toggleCamera = useCallback(async () => {
    if (state !== "active") return;
    const next: CameraFacing = facingRef.current === "user" ? "environment" : "user";
    facingRef.current = next;
    setFacing(next);
    try { await startStream(next); } catch { /* keep current stream on failure */ }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);

  // ── Stop ──────────────────────────────────────────────────────────────────────
  const stop = useCallback(async () => {
    if (captureTimer.current) {
      clearInterval(captureTimer.current);
      captureTimer.current = null;
    }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    const video = videoRef.current;
    if (video) video.srcObject = null;
    const canvas = canvasRef.current;
    if (canvas) {
      const ctx = canvas.getContext("2d");
      ctx?.clearRect(0, 0, canvas.width, canvas.height);
    }
    setState("off");
    setErrorMsg("");
    setAnalyzing(false);
    setAnalysisError("");
    setZoneStats(null);
    setLiveStats({
      facesDetected: 0, attentionPct: 0, handRaises: 0, minuteNumber: 1,
      dominantEmotion: "neutral", emotions: { ...ZERO_EMOTIONS },
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    state, errorMsg, facing, liveStats, videoRef, canvasRef,
    start, stop, toggleCamera,
    analyzing, analysisError, zoneStats,
  };
}
