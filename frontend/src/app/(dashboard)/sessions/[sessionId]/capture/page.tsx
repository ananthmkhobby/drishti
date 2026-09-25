"use client";

import { use, useState, useCallback, useEffect, useRef } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import {
  Camera, Upload, ImagePlus, CheckCircle2, AlertCircle,
  FileImage, ChevronRight, Cpu, Wifi, WifiOff,
  CloudUpload, Clock, ArrowUpCircle, ShieldCheck, ShieldAlert,
  Shield, X, ZoomIn, RefreshCw, Timer, Mic, MicOff, Square,
  Trash2, ChevronDown, ChevronUp, Video, StopCircle, Users, Eye,
  Maximize2, Minimize2,
} from "lucide-react";
import { useAudienceAnalyser } from "@/hooks/useAudienceAnalyser";
import { generateUUID } from "@/lib/uuid";
import { api, getFrameImageUrl, type OCRResult, type AudioRecording, type Frame } from "@/lib/api";
import type { AudioUploadResponse, VideoUploadResponse } from "@/lib/api";
import { addPendingFrame, getFramesBySession, saveRecordingToQueue, type PendingFrame } from "@/lib/offline-store";
import { compressImage } from "@/lib/sync-engine";
import { cn, timeAgo } from "@/lib/utils";
import { useSyncQueue } from "@/hooks/useSyncQueue";
import { CameraCapture, type UploadStatus } from "@/components/capture/CameraCapture";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";

// ── Types ─────────────────────────────────────────────────────────────────────

type Tab = "camera" | "upload" | "video";

interface LocalPreviewFrame {
  id: string;
  blobUrl: string;
  sequenceNo: number;
  capturedAt: string;
  sizeKb: number;
  syncStatus: "pending" | "uploading" | "done" | "failed" | "skipped";
  errorMessage: string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function ocrBadgeColour(status: string): string {
  if (status === "done")       return "bg-green-100 text-green-700";
  if (status === "failed")     return "bg-red-100 text-red-700";
  if (status === "processing") return "bg-yellow-100 text-yellow-700";
  return "bg-slate-100 text-slate-500";
}

function fmtCountdown(secs: number): string {
  if (secs < 60)  return `${secs}s`;
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return s === 0 ? `${m}m` : `${m}m ${s}s`;
}

// ── Privacy shield icon ───────────────────────────────────────────────────────
// Shows as:  grey = scan not done  |  green = privacy applied (board-exterior blur)
//
// With the board-exterior blur strategy, background is ALWAYS blurred (blurred >= 1).
// blurred === 0 is only possible if blur failed entirely (rare).

function PrivacyIcon({ blurred, ocr_status }: { blurred: number | null; ocr_status?: string }) {
  if (ocr_status && ocr_status !== "done") {
    return (
      <span title="Privacy scan pending">
        <Shield className="h-3.5 w-3.5 text-slate-400" />
      </span>
    );
  }
  if (blurred === null || blurred === undefined) {
    return (
      <span title="Privacy scan pending">
        <Shield className="h-3.5 w-3.5 text-slate-400" />
      </span>
    );
  }
  if (blurred > 0) {
    return (
      <span title="Background blurred — board area preserved">
        <ShieldCheck className="h-3.5 w-3.5 text-green-500" />
      </span>
    );
  }
  // blurred === 0: blur was not applied (should be rare)
  return (
    <span title="Privacy blur was not applied">
      <ShieldAlert className="h-3.5 w-3.5 text-orange-400" />
    </span>
  );
}

// ── Full-screen image lightbox ────────────────────────────────────────────────

function Lightbox({
  frame,
  ocr,
  serverFrameId,
  sessionId,
  ocrDone,
  onClose,
}: {
  frame: LocalPreviewFrame;
  ocr: OCRResult | null | undefined;
  /** Server-side frame UUID — when set and OCR is done, shows the blurred image */
  serverFrameId?: string;
  sessionId: string;
  /** True as soon as serverFrameMap says ocr_status==="done" (don't wait for OCR detail) */
  ocrDone?: boolean;
  onClose: () => void;
}) {
  const blurred = ocr?.privacy_blurred ?? null;
  // ocrDone prop (from serverFrameMap) takes precedence — it's available sooner
  // than the OCR detail fetch, and is what controls the image source switch.
  const serverReady = ocrDone || (ocr !== null && ocr !== undefined);

  // Use server image (blurred) once OCR is done; fall back to local blob while pending
  // Append ?v=ocrdone so the browser doesn't serve a stale cached original
  const imageSrc = serverReady && serverFrameId
    ? `${getFrameImageUrl(sessionId, serverFrameId)}?v=done`
    : frame.blobUrl;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
      onClick={onClose}
    >
      <div
        className="relative flex w-full max-w-3xl flex-col rounded-2xl bg-white shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-100">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-800">Frame #{frame.sequenceNo}</span>
            <span className="text-xs text-slate-400">{timeAgo(frame.capturedAt)}</span>
            <span className="text-xs text-slate-400">· {frame.sizeKb} KB</span>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5 text-xs">
              <PrivacyIcon blurred={blurred} />
              <span className={cn(
                blurred === null ? "text-slate-400" :
                blurred > 0     ? "text-green-600" : "text-orange-500"
              )}>
                {blurred === null ? "Scanning…" :
                 blurred > 0     ? "Privacy applied" :
                 "Blur not applied"}
              </span>
            </div>
            <button
              onClick={onClose}
              className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Image — server (blurred) when OCR done, local blob while pending */}
        <div className="relative bg-slate-900 flex items-center justify-center min-h-[18.75rem] max-h-[60vh]">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={imageSrc}
            alt={`Frame ${frame.sequenceNo}`}
            className={cn(
              "max-h-[60vh] max-w-full object-contain transition-[filter] duration-700",
              // Apply CSS blur while privacy scan is in progress.
              // Removed once serverReady=true (OCR done) and the server image loads.
              !serverReady && "blur-2xl",
            )}
          />

          {/* Privacy scan pending overlay (shown while image is CSS-blurred) */}
          {!serverReady && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 pointer-events-none">
              <div className="flex items-center gap-2 rounded-xl bg-slate-900/70 px-4 py-3 backdrop-blur-sm">
                <Shield className="h-4 w-4 text-white/70 animate-pulse" />
                <span className="text-sm font-medium text-white/80">
                  Privacy scan in progress…
                </span>
              </div>
              <span className="text-xs text-white/50">
                Image will be shown once people are detected and blurred
              </span>
            </div>
          )}

          {/* Privacy badge (after scan: board-exterior blur applied) */}
          {blurred !== null && blurred > 0 && serverReady && (
            <div className="absolute bottom-3 right-3 flex items-center gap-1.5 rounded-lg bg-green-600/90 px-2.5 py-1.5 text-xs text-white font-medium backdrop-blur-sm">
              <ShieldCheck className="h-3.5 w-3.5" />
              Background blurred
            </div>
          )}
          {/* No-blur badge (very rare — blur pipeline failed) */}
          {blurred === 0 && serverReady && (
            <div className="absolute bottom-3 right-3 flex items-center gap-1.5 rounded-lg bg-orange-500/80 px-2.5 py-1.5 text-xs text-white font-medium backdrop-blur-sm">
              <ShieldAlert className="h-3.5 w-3.5" />
              Privacy blur unavailable
            </div>
          )}
        </div>

        {/* OCR result */}
        {ocr && (
          <div className="px-5 py-4 border-t border-slate-100 bg-slate-50 space-y-2">
            {/* OCR engine row */}
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
                OCR Result
              </p>
              <span className="text-xs text-slate-400">· {ocr.engine_used}</span>
              {ocr.confidence > 0 && (
                <span className="text-xs text-slate-400">
                  · {(ocr.confidence * 100).toFixed(0)}% conf
                </span>
              )}
            </div>
            {/* Board detection row — not shown for notebook mode, which never
                attempts board detection in the first place (nothing to report) */}
            {ocr.board_detection_method !== "fallback" && ocr.board_detection_method !== "notebook_no_board" && (
              <div className="flex flex-wrap items-center gap-1.5 text-[0.625rem]">
                <span className="font-medium text-slate-500">Board:</span>
                <span className={cn(
                  "rounded px-1.5 py-0.5 font-medium",
                  ocr.board_type === "whiteboard" ? "bg-slate-100 text-slate-700" :
                  ocr.board_type === "greenboard"  ? "bg-green-100 text-green-700" :
                  ocr.board_type === "blackboard"  ? "bg-slate-800 text-white" :
                  "bg-amber-100 text-amber-700",
                )}>
                  {ocr.board_type}
                </span>
                <span className="text-slate-400">{(ocr.board_confidence * 100).toFixed(0)}% via {ocr.board_detection_method}</span>
              </div>
            )}
            <p className="text-sm text-slate-700 font-mono whitespace-pre-wrap leading-relaxed line-clamp-6">
              {ocr.ocr_text || "(no text extracted)"}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Thumbnail strip ───────────────────────────────────────────────────────────

function ThumbnailStrip({
  localFrames,
  serverFrameMap,
  sessionId,
  onSelect,
}: {
  localFrames: LocalPreviewFrame[];
  serverFrameMap: Map<string, { ocr_status: string; frame_id: string }>;
  sessionId: string;
  onSelect: (frame: LocalPreviewFrame) => void;
}) {
  if (localFrames.length === 0) {
    return (
      <div className="flex items-center justify-center gap-2 py-10 text-slate-300">
        <Camera className="h-7 w-7" />
        <span className="text-sm">Captured frames will appear here</span>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 max-h-[26.25rem] overflow-y-auto pr-1">
      {localFrames.map((f) => {
        const server = serverFrameMap.get(f.id);
        const ocrStatus = server?.ocr_status ?? (f.syncStatus === "done" ? "pending" : undefined);
        // Show the server (blurred) image once OCR is complete.
        // ?v=done busts browser cache so we never serve a previously cached original.
        const thumbSrc = (ocrStatus === "done" && server?.frame_id)
          ? `${getFrameImageUrl(sessionId, server.frame_id)}?v=done`
          : f.blobUrl;

        // While OCR is pending (scan not done yet), apply a strong CSS blur so people
        // are not visible in the thumbnail. The server overwrites the stored file with
        // a properly blurred version once OCR + privacy scan completes; at that point
        // thumbSrc switches to the server URL and the CSS blur is removed.
        const privacyPending = ocrStatus !== "done" && f.syncStatus === "done";

        return (
          <button
            key={f.id}
            onClick={() => onSelect(f)}
            className="group relative aspect-[4/3] overflow-hidden rounded-xl border-2 border-transparent hover:border-indigo-400 transition-all focus:outline-none focus:border-indigo-500"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={thumbSrc}
              alt={`Frame ${f.sequenceNo}`}
              className={cn(
                "h-full w-full object-cover transition-[filter] duration-500",
                // Blur faces while privacy scan is running on the server.
                // Removed once ocrStatus === "done" and server (blurred) image loads.
                privacyPending && "blur-xl",
              )}
            />

            {/* Privacy scan in-progress overlay */}
            {privacyPending && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-black/30">
                <Shield className="h-5 w-5 text-white/80 animate-pulse" />
                <span className="text-[0.5625rem] font-semibold text-white/80 text-center leading-tight px-1">
                  Privacy<br/>scanning…
                </span>
              </div>
            )}

            {/* Sequence badge */}
            <span className="absolute top-1.5 left-1.5 rounded-md bg-black/60 px-1.5 py-0.5 text-[0.625rem] font-bold text-white">
              #{f.sequenceNo}
            </span>

            {/* Privacy shield — once OCR is done, show green (blur always applied) */}
            <span className="absolute top-1.5 right-1.5">
              <PrivacyIcon blurred={ocrStatus === "done" ? 1 : null} ocr_status={ocrStatus} />
            </span>

            {/* Bottom bar: OCR status + sync status */}
            <div className="absolute bottom-0 inset-x-0 flex items-center justify-between gap-1 bg-gradient-to-t from-black/70 to-transparent px-1.5 py-1.5">
              {ocrStatus && (
                <span className={cn("text-[0.5625rem] font-semibold rounded px-1 py-0.5",
                  ocrStatus === "done"       ? "bg-green-500/80 text-white" :
                  ocrStatus === "failed"     ? "bg-red-500/80 text-white" :
                  ocrStatus === "processing" ? "bg-yellow-400/80 text-slate-900" :
                  "bg-slate-500/60 text-white"
                )}>
                  {ocrStatus}
                </span>
              )}
              <span
                title={f.syncStatus === "skipped" ? (f.errorMessage ?? "Upload failed — won't retry") : undefined}
                className={cn("ml-auto text-[0.5625rem] font-semibold rounded px-1 py-0.5",
                  f.syncStatus === "done"      ? "bg-green-500/80 text-white" :
                  f.syncStatus === "uploading" ? "bg-blue-400/80 text-white" :
                  f.syncStatus === "failed"    ? "bg-red-500/80 text-white" :
                  // "skipped" = the sync engine gave up permanently (e.g. a 4xx
                  // like "session has ended") — this is NOT the same as still
                  // pending, so it needs its own look, not the default "…"
                  // that made a dead upload look identical to an in-progress one.
                  f.syncStatus === "skipped"   ? "bg-amber-500/80 text-white" :
                  "bg-slate-500/60 text-white"
                )}
              >
                {f.syncStatus === "done" ? "✓" :
                 f.syncStatus === "uploading" ? "↑" :
                 f.syncStatus === "failed" ? "✗" :
                 f.syncStatus === "skipped" ? "⚠" : "…"}
              </span>
            </div>
            {f.syncStatus === "skipped" && (
              <div className="absolute inset-x-0 bottom-6 bg-amber-600/90 px-1.5 py-1 text-[0.5625rem] font-medium text-white leading-tight">
                {f.errorMessage ?? "Upload failed"}
              </div>
            )}

            {/* Hover zoom hint */}
            <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-black/20">
              <ZoomIn className="h-6 w-6 text-white drop-shadow" />
            </div>
          </button>
        );
      })}
    </div>
  );
}

// ── Sync status bar ───────────────────────────────────────────────────────────

interface SyncStatusBarProps {
  isOnline:             boolean;
  isSyncing:            boolean;
  queueCount:           number;
  recordingsPending:    number;
  secondsUntilAutoSync: number | null;
  lastSyncAt:           Date | null;
  onSyncNow:            () => void;
}

function SyncStatusBar({
  isOnline, isSyncing, queueCount, recordingsPending, secondsUntilAutoSync, lastSyncAt, onSyncNow,
}: SyncStatusBarProps) {
  const totalPending = queueCount + recordingsPending;
  const allSynced    = totalPending === 0;

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-2.5">

      {/* Online / offline pill */}
      <span className={cn(
        "flex items-center gap-1.5 text-xs font-medium",
        isOnline ? "text-green-600" : "text-amber-600",
      )}>
        {isOnline
          ? <><Wifi    className="h-3.5 w-3.5" /> Online</>
          : <><WifiOff className="h-3.5 w-3.5" /> Offline — capturing locally</>
        }
      </span>

      <span className="h-4 w-px bg-slate-200" />

      {/* Frame queue */}
      {queueCount > 0 && (
        <span className="flex items-center gap-1.5 text-xs text-slate-600">
          {isSyncing
            ? <CloudUpload className="h-3.5 w-3.5 animate-pulse text-indigo-500" />
            : <Clock       className="h-3.5 w-3.5 text-amber-500" />
          }
          <strong className="font-semibold">{queueCount}</strong>
          {" "}frame{queueCount !== 1 ? "s" : ""}{" "}
          {isSyncing ? "uploading…" : "pending"}
        </span>
      )}

      {/* Recording queue */}
      {recordingsPending > 0 && (
        <span className="flex items-center gap-1.5 text-xs text-violet-700">
          {isSyncing
            ? <CloudUpload className="h-3.5 w-3.5 animate-pulse text-violet-500" />
            : <Clock       className="h-3.5 w-3.5 text-violet-400" />
          }
          <strong className="font-semibold">{recordingsPending}</strong>
          {" "}recording{recordingsPending !== 1 ? "s" : ""}{" "}
          {isSyncing ? "uploading…" : "saved offline"}
        </span>
      )}

      {/* All synced */}
      {allSynced && (
        <span className="flex items-center gap-1.5 text-xs text-green-600">
          <CheckCircle2 className="h-3.5 w-3.5" />
          All synced
          {lastSyncAt && <span className="text-slate-400 font-normal">{" "}· {timeAgo(lastSyncAt.toISOString())}</span>}
        </span>
      )}

      {/* Progress rail while uploading */}
      {isSyncing && totalPending > 0 && (
        <span className="h-1.5 w-20 overflow-hidden rounded-full bg-slate-100">
          <span className="block h-full w-1/2 animate-pulse rounded-full bg-indigo-500" />
        </span>
      )}

      {/* Auto-sync countdown */}
      {secondsUntilAutoSync !== null && !isSyncing && totalPending > 0 && (
        <span className="flex items-center gap-1 text-xs text-slate-400">
          <RefreshCw className="h-3 w-3" />
          Auto-sync in {fmtCountdown(secondsUntilAutoSync)}
        </span>
      )}

      {/* Manual sync button */}
      {totalPending > 0 && isOnline && !isSyncing && (
        <button
          onClick={onSyncNow}
          className="ml-auto flex touch-manipulation items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 transition-colors"
        >
          <ArrowUpCircle className="h-3.5 w-3.5" />
          Sync Now
        </button>
      )}

      {!isOnline && totalPending > 0 && (
        <span className="ml-auto text-xs text-amber-600 font-medium">
          Will auto-upload when WiFi returns
        </span>
      )}
    </div>
  );
}

// ── Audio recorder hook ───────────────────────────────────────────────────────

type AudioState = "idle" | "recording" | "uploading" | "done" | "error";

function useAudioRecorder(
  sessionId: string,
  onUploaded: (r: AudioUploadResponse) => void,
  onQueued: () => void,
) {
  const [audioState, setAudioState] = useState<AudioState>("idle");
  const [recordingSec, setRecordingSec] = useState(0);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";
      const mr = new MediaRecorder(stream, { mimeType });
      chunksRef.current = [];
      mr.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      mr.start(1000);
      mediaRecorderRef.current = mr;
      setAudioState("recording");
      setRecordingSec(0);
      timerRef.current = setInterval(() => setRecordingSec((s) => s + 1), 1000);
    } catch {
      setAudioState("error");
    }
  }, []);

  const stopAndUpload = useCallback(async () => {
    const mr = mediaRecorderRef.current;
    if (!mr || mr.state === "inactive") return;
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    setAudioState("uploading");

    await new Promise<void>((resolve) => {
      mr.onstop = () => resolve();
      mr.stop();
      mr.stream.getTracks().forEach((t) => t.stop());
    });

    const mimeType = "audio/webm";
    const blob = new Blob(chunksRef.current, { type: mimeType });

    // ── Online path (unchanged behaviour) ─────────────────────────────────────
    try {
      const result = await api.uploadAudio(sessionId, blob, "recording.webm");
      onUploaded(result);
      setAudioState("idle");
      return;
    } catch { /* fall through to offline queue */ }

    // ── Offline fallback ──────────────────────────────────────────────────────
    try {
      await saveRecordingToQueue(sessionId, "audio", blob, mimeType, "recording.webm");
      onQueued();           // triggers useSyncQueue refresh so count updates
      setAudioState("idle"); // teacher can record another clip immediately
    } catch {
      setAudioState("error"); // IDB also failed (private browsing / storage full)
    }
  }, [sessionId, onUploaded, onQueued]);

  // Same destination as a live recording — a picked file and a MediaRecorder
  // blob both end up as a plain Blob POSTed to the same endpoint, so this
  // reuses the identical upload-then-transcribe path (online with offline
  // queue fallback), just skipping the record step.
  const uploadFile = useCallback(async (file: File) => {
    setAudioState("uploading");
    try {
      const result = await api.uploadAudio(sessionId, file, file.name);
      onUploaded(result);
      setAudioState("idle");
      return;
    } catch { /* fall through to offline queue */ }

    try {
      await saveRecordingToQueue(sessionId, "audio", file, file.type || "audio/webm", file.name);
      onQueued();
      setAudioState("idle");
    } catch {
      setAudioState("error");
    }
  }, [sessionId, onUploaded, onQueued]);

  useEffect(() => () => {
    if (timerRef.current) clearInterval(timerRef.current);
    mediaRecorderRef.current?.stream?.getTracks().forEach((t) => t.stop());
  }, []);

  return { audioState, recordingSec, startRecording, stopAndUpload, uploadFile };
}

function fmtDuration(secs: number): string {
  const m = Math.floor(secs / 60).toString().padStart(2, "0");
  const s = (secs % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function RecordingRow({
  recording,
  onDelete,
  onRetry,
}: {
  recording: AudioRecording;
  onDelete: () => void;
  onRetry?: () => Promise<void>;
}) {
  const [expanded, setExpanded] = useState(!!recording.transcript);
  const [deleting, setDeleting] = useState(false);
  const [retrying, setRetrying] = useState(false);

  return (
    <div className="px-3 py-2.5 bg-white">
      <div className="flex items-center gap-2">
        {/* Number badge */}
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-[0.625rem] font-bold text-indigo-700">
          {recording.recording_number}
        </span>

        {recording.duration_sec != null && (
          <span className="text-[0.6875rem] font-mono text-slate-500 shrink-0">
            {fmtDuration(Math.round(recording.duration_sec))}
          </span>
        )}

        {recording.source === "video" && (
          <span className="rounded-full bg-violet-100 px-2 py-0.5 text-[0.625rem] font-semibold text-violet-700 shrink-0">
            Video
          </span>
        )}
        {recording.transcribed ? (
          <span className="flex items-center gap-0.5 rounded-full bg-green-50 px-2 py-0.5 text-[0.625rem] font-semibold text-green-700 shrink-0">
            <CheckCircle2 className="h-2.5 w-2.5" /> Transcribed
          </span>
        ) : (
          <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[0.625rem] font-semibold text-amber-600 shrink-0">
            Not transcribed
          </span>
        )}
        {recording.whisper_tokens > 0 && (
          <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[0.625rem] text-indigo-500 shrink-0">
            {recording.whisper_tokens.toLocaleString()} tok
          </span>
        )}

        <div className="flex items-center gap-1 ml-auto">
          {!recording.transcribed && onRetry && (
            <button
              onClick={async () => {
                if (retrying) return;
                setRetrying(true);
                try { await onRetry(); } finally { setRetrying(false); }
              }}
              disabled={retrying}
              className="flex items-center gap-0.5 rounded-full bg-indigo-600 px-2 py-0.5 text-[0.625rem] font-semibold text-white hover:bg-indigo-700 transition-colors disabled:opacity-60"
            >
              <RefreshCw className={cn("h-2.5 w-2.5", retrying && "animate-spin")} />
              {retrying ? "Retrying…" : "Retry"}
            </button>
          )}
          {recording.transcript && (
            <button
              onClick={() => setExpanded((e) => !e)}
              className="flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[0.6875rem] text-indigo-500 hover:bg-indigo-50 transition-colors"
            >
              {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
              {expanded ? "Hide" : "Show"}
            </button>
          )}
          <button
            onClick={async () => {
              if (deleting) return;
              setDeleting(true);
              try { await onDelete(); } finally { setDeleting(false); }
            }}
            disabled={deleting}
            className="flex h-6 w-6 items-center justify-center rounded text-red-400 hover:text-red-600 hover:bg-red-50 transition-colors disabled:opacity-40"
            title="Delete recording"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {expanded && recording.transcript && (
        <div className="mt-2 rounded-lg bg-slate-50 border border-slate-100 px-3 py-2">
          <p className="text-[0.75rem] text-slate-600 leading-relaxed whitespace-pre-wrap">
            {recording.transcript}
          </p>
        </div>
      )}
    </div>
  );
}

// ── Video recorder hook ───────────────────────────────────────────────────────

type VideoState = "idle" | "recording" | "uploading" | "done" | "error";

// Auto-rotate recording every 5 minutes so each upload stays small and
// processes in parallel rather than waiting for one huge file.
const SEGMENT_MS  = 5 * 60 * 1000;
const SEGMENT_SEC = SEGMENT_MS / 1000;

function useVideoRecorder(
  sessionId: string,
  onUploaded: (r: VideoUploadResponse) => void,
  onQueued: () => void,
) {
  const [videoState, setVideoState] = useState<VideoState>("idle");
  const [recordingSec, setRecordingSec] = useState(0);
  const [uploadSizeMb, setUploadSizeMb] = useState(0);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [hasAudio, setHasAudio] = useState(false);
  const [segmentIndex, setSegmentIndex] = useState(1);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef        = useRef<MediaStream | null>(null);
  const chunksRef        = useRef<Blob[]>([]);
  const timerRef         = useRef<ReturnType<typeof setInterval> | null>(null);
  const previewRef       = useRef<HTMLVideoElement | null>(null);
  const segmentIndexRef  = useRef(1);
  const segmentRotatingRef = useRef(false);
  const segmentTimerRef  = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mimeTypeRef      = useRef("video/webm");
  const rotateSegmentRef = useRef<() => Promise<void>>(async () => {});

  // Upload one segment blob in the background (fire-and-forget from the caller).
  const uploadSegment = useCallback(async (blob: Blob, segIdx: number) => {
    const sizeMb = Math.round(blob.size / 1024 / 1024 * 10) / 10;
    try {
      const result = sizeMb > 5
        ? await api.uploadVideoChunked(sessionId, blob, () => {})
        : await api.uploadVideo(sessionId, blob, `segment_${segIdx}.webm`);
      onUploaded(result);
    } catch {
      try {
        await saveRecordingToQueue(sessionId, "video", blob, "video/webm", `segment_${segIdx}.webm`);
        onQueued();
      } catch { /* IDB full — segment lost */ }
    }
  }, [sessionId, onUploaded, onQueued]);

  // Stop the current MediaRecorder, upload its data, then immediately restart
  // a fresh recorder on the same stream so recording is continuous.
  const rotateSegment = useCallback(async () => {
    const mr     = mediaRecorderRef.current;
    const stream = streamRef.current;
    if (!mr || mr.state === "inactive" || !stream || segmentRotatingRef.current) return;

    segmentRotatingRef.current = true;
    const captured = [...chunksRef.current];
    chunksRef.current = [];
    const idx = segmentIndexRef.current;

    await new Promise<void>((resolve) => {
      mr.onstop = () => resolve();
      mr.stop();
    });

    // Upload completed segment in background while recording continues
    if (captured.length > 0) {
      void uploadSegment(new Blob(captured, { type: "video/webm" }), idx);
    }

    segmentIndexRef.current += 1;
    setSegmentIndex(segmentIndexRef.current);

    // Restart recording on same stream (stream stays open the whole time)
    const newMr = new MediaRecorder(stream, { mimeType: mimeTypeRef.current });
    newMr.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
    newMr.start(1000);
    mediaRecorderRef.current = newMr;
    segmentRotatingRef.current = false;

    // Schedule the next rotation
    segmentTimerRef.current = setTimeout(() => { void rotateSegmentRef.current(); }, SEGMENT_MS);
  }, [uploadSegment]);

  useEffect(() => { rotateSegmentRef.current = rotateSegment; }, [rotateSegment]);

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      streamRef.current = stream;
      setHasAudio(stream.getAudioTracks().length > 0);

      if (previewRef.current) {
        previewRef.current.srcObject = stream;
        previewRef.current.play().catch(() => {});
      }

      // Prefer VP9+Opus for best compression; fall back to plain webm
      const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp9,opus")
        ? "video/webm;codecs=vp9,opus"
        : MediaRecorder.isTypeSupported("video/webm;codecs=vp8,opus")
        ? "video/webm;codecs=vp8,opus"
        : "video/webm";
      mimeTypeRef.current = mimeType;
      const mr = new MediaRecorder(stream, { mimeType });
      chunksRef.current = [];
      mr.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      mr.start(1000);
      mediaRecorderRef.current = mr;
      segmentIndexRef.current = 1;
      setSegmentIndex(1);
      setVideoState("recording");
      setRecordingSec(0);
      timerRef.current = setInterval(() => setRecordingSec((s) => s + 1), 1000);
      // First auto-rotation fires after 5 minutes
      segmentTimerRef.current = setTimeout(rotateSegment, SEGMENT_MS);
    } catch {
      setVideoState("error");
    }
  }, [rotateSegment]);

  const stopStream = useCallback(() => {
    if (timerRef.current)        { clearInterval(timerRef.current);  timerRef.current        = null; }
    if (segmentTimerRef.current) { clearTimeout(segmentTimerRef.current); segmentTimerRef.current = null; }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    if (previewRef.current) previewRef.current.srcObject = null;
  }, []);

  const cancelRecording = useCallback(() => {
    if (segmentTimerRef.current) { clearTimeout(segmentTimerRef.current); segmentTimerRef.current = null; }
    const mr = mediaRecorderRef.current;
    if (mr && mr.state !== "inactive") mr.stop();
    stopStream();
    chunksRef.current = [];
    setVideoState("idle");
    setRecordingSec(0);
  }, [stopStream]);

  const stopAndUpload = useCallback(async () => {
    // Prevent any scheduled rotation from firing after we stop
    if (segmentTimerRef.current) { clearTimeout(segmentTimerRef.current); segmentTimerRef.current = null; }

    // If a rotation is mid-flight, wait for it to finish so chunksRef is stable
    while (segmentRotatingRef.current) {
      await new Promise((r) => setTimeout(r, 50));
    }

    const mr = mediaRecorderRef.current;
    if (!mr || mr.state === "inactive") return;
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    setVideoState("uploading");

    await new Promise<void>((resolve) => {
      mr.onstop = () => resolve();
      mr.stop();
      streamRef.current?.getTracks().forEach((t) => t.stop());
      if (previewRef.current) previewRef.current.srcObject = null;
    });

    const blob = new Blob(chunksRef.current, { type: "video/webm" });
    const sizeMb = Math.round(blob.size / 1024 / 1024 * 10) / 10;
    setUploadSizeMb(sizeMb);
    setUploadProgress(0);

    // ── Online path ───────────────────────────────────────────────────────────
    try {
      const result = sizeMb > 5
        ? await api.uploadVideoChunked(sessionId, blob, (pct) => setUploadProgress(pct))
        : await api.uploadVideo(sessionId, blob, "recording.webm");
      onUploaded(result);
      setVideoState("idle");
      return;
    } catch { /* fall through to offline queue */ }

    // ── Offline fallback ──────────────────────────────────────────────────────
    try {
      await saveRecordingToQueue(sessionId, "video", blob, "video/webm", "recording.webm");
      onQueued();
      setVideoState("idle");
    } catch {
      setVideoState("error");
    }
  }, [sessionId, onUploaded, onQueued]);

  useEffect(() => () => {
    if (timerRef.current)        clearInterval(timerRef.current);
    if (segmentTimerRef.current) clearTimeout(segmentTimerRef.current);
    streamRef.current?.getTracks().forEach((t) => t.stop());
  }, []);

  return { videoState, recordingSec, uploadSizeMb, uploadProgress, hasAudio, segmentIndex, startRecording, stopAndUpload, cancelRecording, previewRef };
}

// ── Emotion helpers ───────────────────────────────────────────────────────────

const EMOTION_EMOJI: Record<string, string> = {
  happy:      "😊",
  confused:   "🤔",
  surprised:  "😮",
  disengaged: "😴",
  neutral:    "😐",
};
const EMOTION_COLOR: Record<string, string> = {
  happy:      "#22c55e",
  confused:   "#f59e0b",
  surprised:  "#6366f1",
  disengaged: "#ef4444",
  neutral:    "#94a3b8",
};

// ── AudienceInlineReport ──────────────────────────────────────────────────────

const EMOTIONS_ORDER = ["happy", "confused", "surprised", "disengaged"] as const;

function dominantEmotion(m: { happy_pct: number; confused_pct: number; surprised_pct: number; disengaged_pct: number }): string {
  const vals = { happy: m.happy_pct, confused: m.confused_pct, surprised: m.surprised_pct, disengaged: m.disengaged_pct };
  const top = (Object.entries(vals) as [string, number][]).reduce((a, b) => b[1] > a[1] ? b : a, ["neutral", 0]);
  return top[1] >= 10 ? top[0] : "neutral";
}

function AudienceInlineReport({
  sessionId,
  liveMinute,
  liveAtt,
}: {
  sessionId: string;
  liveMinute: number;
  liveAtt: number;
}) {
  const { data } = useSWR(
    `audience-inline-${sessionId}`,
    () => api.getAudienceMetrics(sessionId),
    { refreshInterval: 30_000, revalidateOnFocus: false }
  );

  if (!data || data.metrics.length === 0) return null;

  const metrics = data.metrics;
  const maxAtt  = Math.max(...metrics.map((m) => m.attention_pct), 1);
  const maxFaces = Math.max(...metrics.map((m) => m.faces_detected), 1);

  // Average emotion across all stored minutes
  const n = metrics.length || 1;
  const avgEmotions = EMOTIONS_ORDER.reduce((acc, e) => {
    acc[e] = Math.round(metrics.reduce((s, m) => s + (m[`${e}_pct` as keyof typeof m] as number ?? 0), 0) / n);
    return acc;
  }, {} as Record<string, number>);

  // Trend: compare last 2 minutes vs first 2 minutes for attention
  let trendArrow = "";
  if (metrics.length >= 4) {
    const early = (metrics[0].attention_pct + metrics[1].attention_pct) / 2;
    const late  = (metrics[metrics.length - 2].attention_pct + metrics[metrics.length - 1].attention_pct) / 2;
    trendArrow = late - early > 5 ? " ↑" : late - early < -5 ? " ↓" : "";
  }

  return (
    <div className="border-t border-indigo-100 bg-white/60">
      {/* Attention + face count timeline */}
      <div className="px-3 pt-2 pb-1">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[0.6875rem] font-semibold text-slate-600">Attention by minute</span>
          {data.avg_attention_pct != null && (
            <span className="text-[0.6875rem] text-indigo-600 font-medium">
              avg {Math.round(data.avg_attention_pct)}%{trendArrow}
            </span>
          )}
        </div>
        <div className="flex items-end gap-1" style={{ height: 44 }}>
          {metrics.map((m) => {
            const isLive = m.minute_number === liveMinute;
            const pct    = isLive ? liveAtt : m.attention_pct;
            const h      = Math.max(4, Math.round((pct / maxAtt) * 36));
            const attColor = pct >= 70 ? "#22c55e" : pct >= 40 ? "#f59e0b" : "#ef4444";
            const emo    = dominantEmotion(m);
            // Top 3px stripe shows dominant emotion colour; body shows attention level
            const emoColor = emo !== "neutral" ? EMOTION_COLOR[emo] : attColor;
            const faceH  = Math.max(2, Math.round((m.faces_detected / maxFaces) * 6));
            return (
              <div
                key={m.minute_number}
                className="flex flex-col items-center gap-0.5 flex-1"
                title={`Min ${m.minute_number}: ${Math.round(pct)}% attentive · ${m.faces_detected} faces · ${emo}`}
              >
                {/* Emotion colour stripe on top */}
                <div style={{ height: "0.1875rem", background: emoColor, borderRadius: "0.125rem 0.125rem 0 0", width: "100%", opacity: isLive ? 1 : 0.8 }} />
                {/* Attention bar */}
                <div style={{ height: h, background: attColor, width: "100%", opacity: isLive ? 1 : 0.70 }} />
                {/* Face count dot row at bottom */}
                <div style={{ height: faceH, background: "#6366f1", borderRadius: "0 0 0.125rem 0.125rem", width: "100%", opacity: 0.55 }} />
                <span className="text-[0.5rem] text-slate-400">{m.minute_number}</span>
              </div>
            );
          })}
        </div>
        {/* Legend */}
        <div className="flex items-center gap-3 mt-1">
          <span className="flex items-center gap-1 text-[0.5625rem] text-slate-400">
            <span style={{ width: "0.5rem", height: "0.1875rem", background: "#22c55e", display: "inline-block", borderRadius: "0.0625rem" }} /> attention
          </span>
          <span className="flex items-center gap-1 text-[0.5625rem] text-slate-400">
            <span style={{ width: "0.5rem", height: "0.1875rem", background: "#f59e0b", display: "inline-block", borderRadius: "0.0625rem" }} /> mood stripe
          </span>
          <span className="flex items-center gap-1 text-[0.5625rem] text-slate-400">
            <span style={{ width: "0.5rem", height: "0.1875rem", background: "#6366f1", display: "inline-block", borderRadius: "0.0625rem" }} /> faces
          </span>
        </div>
      </div>

      {/* Emotion averages with mini progress bars */}
      <div className="px-3 pb-2.5">
        <div className="flex items-center gap-2 flex-wrap">
          {EMOTIONS_ORDER.filter(e => avgEmotions[e] >= 5).map((emotion) => (
            <div key={emotion} className="flex items-center gap-1.5 min-w-[4.375rem]">
              <span className="text-[0.625rem]">{EMOTION_EMOJI[emotion]}</span>
              <div className="flex-1 h-1.5 rounded-full bg-slate-100 overflow-hidden">
                <div
                  style={{ width: `${Math.min(avgEmotions[emotion], 100)}%`, background: EMOTION_COLOR[emotion], height: "100%", borderRadius: 9999 }}
                />
              </div>
              <span className="text-[0.5625rem] font-semibold" style={{ color: EMOTION_COLOR[emotion] }}>
                {avgEmotions[emotion]}%
              </span>
            </div>
          ))}
          {EMOTIONS_ORDER.every(e => avgEmotions[e] < 5) && (
            <span className="text-[0.625rem] text-slate-400">Mostly neutral 😐</span>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CapturePage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  const searchParams = useSearchParams();

  // Dashboard "Quick capture" shortcuts land here with ?tab=video so the
  // manual tab-switch tap they used to need is skipped too.
  const initialTabParam = searchParams.get("tab");
  const [tab, setTab] = useState<Tab>(
    initialTabParam === "video" || initialTabParam === "upload" ? initialTabParam : "camera",
  );

  // ── Recordings list ────────────────────────────────────────────────────────
  const { data: audioData, mutate: mutateAudio } = useSWR(
    ["audio", sessionId],
    () => api.getAudio(sessionId),
    { revalidateOnFocus: false },
  );
  const serverRecordings = audioData?.recordings ?? [];

  // ── Offline sync queue (must come before recorder hooks that use refreshCounts) ──
  const {
    pending, uploading, recordingsPending, isOnline, isSyncing,
    secondsUntilAutoSync, lastSyncAt,
    triggerSync, refresh: refreshCounts,
  } = useSyncQueue(sessionId);
  const queueCount = pending + uploading;

  const handleAudioUploaded = useCallback((_r: AudioUploadResponse) => {
    mutateAudio();
  }, [mutateAudio]);

  const { audioState, recordingSec, startRecording, stopAndUpload, uploadFile } = useAudioRecorder(sessionId, handleAudioUploaded, refreshCounts);
  const audioFileInputRef = useRef<HTMLInputElement>(null);

  // ── Auto-capture interval (0 = off / manual; positive = seconds between shots) ──
  // Completely independent of session.capture_mode so teachers can always use it.
  const [captureIntervalSec, setCaptureIntervalSec] = useState(0);

  // ── Session duration (auto-stop) ───────────────────────────────────────────
  // 0 = no limit; positive value = stop auto-capture after N minutes
  const [sessionDurationMin, setSessionDurationMin] = useState(0);

  // ── Banner ─────────────────────────────────────────────────────────────────
  const [banner, setBanner] = useState<{ ok: boolean; message: string } | null>(null);
  const bannerTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  function showBanner(ok: boolean, message: string) {
    if (bannerTimer.current) clearTimeout(bannerTimer.current);
    setBanner({ ok, message });
    bannerTimer.current = setTimeout(() => setBanner(null), 4000);
  }
  useEffect(() => () => { if (bannerTimer.current) clearTimeout(bannerTimer.current); }, []);

  // ── Server data ────────────────────────────────────────────────────────────
  const { data: session } = useSWR(["session", sessionId], () => api.getSession(sessionId));
  const { data: framesData, mutate: mutateFrames } = useSWR(
    ["frames", sessionId],
    () => api.getFrames(sessionId),
    {
      // Poll every 3 s while any frame is still being OCR'd / privacy-scanned.
      // Stops automatically once all frames reach a terminal state.
      refreshInterval: (data) => {
        const frames = data?.frames ?? [];
        const hasInProgress = frames.some(
          (f) => f.ocr_status !== "done" && f.ocr_status !== "failed" && f.ocr_status !== "skipped",
        );
        return hasInProgress ? 3000 : 0;
      },
      // Re-validate when the user returns to the tab (catches frames that finished
      // while the page was in the background).
      revalidateOnFocus: true,
    },
  );
  const serverFrames = framesData?.frames ?? [];

  const handleVideoUploaded = useCallback((_r: VideoUploadResponse) => {
    mutateAudio();
    mutateFrames();
  }, [mutateAudio, mutateFrames]);

  // When the sync engine finishes uploading a queued recording, refresh the list
  useEffect(() => {
    function onRecordingSynced(e: Event) {
      const ev = e as CustomEvent<{ sessionId: string }>;
      if (ev.detail?.sessionId === sessionId) {
        mutateAudio();
        refreshCounts();
      }
    }
    window.addEventListener("aci:recording-synced", onRecordingSynced);
    return () => window.removeEventListener("aci:recording-synced", onRecordingSynced);
  }, [sessionId, mutateAudio, refreshCounts]);

  const { videoState, recordingSec: videoSec, uploadSizeMb, uploadProgress, hasAudio: videoHasAudio, segmentIndex: videoSegmentIndex, startRecording: startVideo, stopAndUpload: stopVideo, cancelRecording: cancelVideo, previewRef: videoPreviewRef } = useVideoRecorder(sessionId, handleVideoUploaded, refreshCounts);

  // Voice-triggered recording start/stop ("start recording audio" /
  // "stop the video") — ClassroomBrain is mounted globally and reaches this
  // page's recorder state via the same DOM-event bridge already used above
  // for aci:recording-synced, rather than prop-drilling or context.
  useEffect(() => {
    function onStart(e: Event) {
      const type = (e as CustomEvent<{ type?: string }>).detail?.type;
      if (type === "video") { if (videoState === "idle") startVideo(); }
      else { if (audioState === "idle") startRecording(); }
    }
    function onStop(e: Event) {
      const type = (e as CustomEvent<{ type?: string }>).detail?.type;
      if (type === "video") { if (videoState === "recording") stopVideo(); }
      else { if (audioState === "recording") stopAndUpload(); }
    }
    window.addEventListener("classroom-brain:start_recording", onStart);
    window.addEventListener("classroom-brain:stop_recording", onStop);
    return () => {
      window.removeEventListener("classroom-brain:start_recording", onStart);
      window.removeEventListener("classroom-brain:stop_recording", onStop);
    };
  }, [audioState, videoState, startRecording, stopAndUpload, startVideo, stopVideo]);

  // Dashboard "Quick capture" shortcuts land here with ?autostart=camera|
  // audio|video so the separate "now get the camera/mic actually going" tap
  // they used to need is skipped — the person still has to confirm/stop
  // manually, nothing captures or uploads on its own. Audio/video call the
  // recorder functions directly (they already live in this component) so
  // there's no mount-order race; the camera case is handled by passing
  // autoStart down to <CameraCapture>, which is a separate component and so
  // has to trigger its own startCamera() from its own mount effect instead.
  const autostartParam = searchParams.get("autostart");
  const autostartFiredRef = useRef(false);
  useEffect(() => {
    if (autostartFiredRef.current || !autostartParam) return;
    if (autostartParam === "audio" && audioState === "idle") {
      autostartFiredRef.current = true;
      startRecording();
    } else if (autostartParam === "video" && videoState === "idle") {
      autostartFiredRef.current = true;
      startVideo();
    }
  }, [autostartParam, audioState, videoState, startRecording, startVideo]);

  // Voice-triggered "reprocess that photo" — targets the most recently
  // captured frame (highest sequence_no), same as api.retryOCR already
  // exposed for (this was defined but never actually wired to any UI
  // trigger before voice commands needed it).
  useEffect(() => {
    function onReprocess() {
      const latest = serverFrames.reduce<Frame | null>(
        (best, f) => (!best || f.sequence_no > best.sequence_no) ? f : best, null,
      );
      if (latest) {
        api.retryOCR(latest.frame_id).then(() => mutateFrames()).catch(() => {});
      }
    }
    window.addEventListener("classroom-brain:reprocess_ocr", onReprocess);
    return () => window.removeEventListener("classroom-brain:reprocess_ocr", onReprocess);
  }, [serverFrames, mutateFrames]);

  // Voice-triggered "auto-capture every 5 seconds" / "stop auto capture" —
  // the interval picker above is a plain local state with no server-side
  // counterpart, so this is a direct setState, no API call needed.
  useEffect(() => {
    function onSetAutoCapture(e: Event) {
      const seconds = (e as CustomEvent<{ seconds?: number }>).detail?.seconds;
      if (typeof seconds === "number" && [0, 5, 10, 20, 30, 60].includes(seconds)) {
        setCaptureIntervalSec(seconds);
      }
    }
    window.addEventListener("classroom-brain:set_auto_capture", onSetAutoCapture);
    return () => window.removeEventListener("classroom-brain:set_auto_capture", onSetAutoCapture);
  }, []);
  const [videoFullscreen, setVideoFullscreen] = useState(false);
  const [audienceFullscreen, setAudienceFullscreen] = useState(false);

  // ── Phase 2: audience face analysis ──────────────────────────────────────
  const {
    state: audienceState,
    errorMsg: audienceError,
    facing: audienceFacing,
    liveStats: audienceStats,
    videoRef: audienceVideoRef,
    canvasRef: audienceCanvasRef,
    start: startAudience,
    stop: stopAudience,
    toggleCamera: toggleAudienceCamera,
    analyzing: audienceAnalyzing,
    analysisError: audienceAnalysisError,
    zoneStats: audienceZoneStats,
  } = useAudienceAnalyser(sessionId);

  // Build a map of localFrameId → {ocr_status, frame_id} for overlaying on thumbnails
  const serverFrameMap = new Map(
    serverFrames.map((f) => [f.local_frame_id, { ocr_status: f.ocr_status, frame_id: f.frame_id }])
  );

  // Refs so handleCameraCapture doesn't rebuild every time polling updates framesData.
  // Without this, capture() in CameraCapture also rebuilds, resetting the auto-capture interval.
  const framesDataRef = useRef(framesData);
  const queueCountRef = useRef(queueCount);
  useEffect(() => { framesDataRef.current = framesData; }, [framesData]);
  useEffect(() => { queueCountRef.current = queueCount; }, [queueCount]);

  // ── Local frame previews ──────────────────────────────────────────────────
  const [localFrames, setLocalFrames] = useState<LocalPreviewFrame[]>([]);
  const blobUrlsRef = useRef<string[]>([]);

  // Load IDB frames on mount (survives page refresh)
  useEffect(() => {
    async function loadFromIDB() {
      try {
        const idbFrames: PendingFrame[] = await getFramesBySession(sessionId);
        const previews: LocalPreviewFrame[] = idbFrames
          .filter((f) => f.blob)
          .sort((a, b) => b.sequenceNo - a.sequenceNo)
          .map((f) => {
            const blobUrl = URL.createObjectURL(f.blob);
            blobUrlsRef.current.push(blobUrl);
            return {
              id:           f.id,
              blobUrl,
              sequenceNo:   f.sequenceNo,
              capturedAt:   f.capturedAt,
              sizeKb:       f.sizeKb,
              syncStatus:   f.status,
              errorMessage: f.errorMessage,
            };
          });
        // Merge with any frames already added by handleCameraCapture while IDB
        // was loading — prevents a race where the user captures a photo before
        // getFramesBySession resolves and the IDB result overwrites it.
        setLocalFrames(prev => {
          if (prev.length === 0) return previews;
          const prevIds = new Set(prev.map(f => f.id));
          const fromIDB = previews.filter(f => !prevIds.has(f.id));
          if (fromIDB.length === 0) return prev;
          return [...prev, ...fromIDB].sort((a, b) => b.sequenceNo - a.sequenceNo);
        });
      } catch {
        // IDB unavailable
      }
    }
    loadFromIDB();

    return () => {
      blobUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
      blobUrlsRef.current = [];
    };
  }, [sessionId]);

  // ── Lightbox state ─────────────────────────────────────────────────────────
  const [lightboxFrame, setLightboxFrame] = useState<LocalPreviewFrame | null>(null);
  const lightboxServerInfo = lightboxFrame
    ? serverFrameMap.get(lightboxFrame.id)
    : null;
  const lightboxFrameId  = lightboxServerInfo?.frame_id ?? null;
  // True as soon as the serverFrameMap says OCR is done — don't wait for the
  // OCR detail fetch, which can 404 (frame still processing) and never retry.
  const lightboxOcrDone  = lightboxServerInfo?.ocr_status === "done";

  const { data: lightboxOCR } = useSWR(
    lightboxFrameId ? ["ocr", lightboxFrameId] : null,
    () => api.getOCR(lightboxFrameId!),
    {
      // Retry up to 6 times so the lightbox auto-updates once OCR finishes
      shouldRetryOnError: true,
      errorRetryCount: 6,
      errorRetryInterval: 3000,
      // Also poll every 4 s while the lightbox is open and OCR isn't done yet
      refreshInterval: lightboxOcrDone ? 0 : 4000,
    },
  );

  // ── Upload status for camera component ────────────────────────────────────
  const [uploadStatus, setUploadStatus] = useState<UploadStatus>("idle");
  const [uploadedKb,   setUploadedKb]   = useState<number | undefined>();

  const prevIsSyncing = useRef(false);
  useEffect(() => {
    const justFinished = prevIsSyncing.current && !isSyncing;
    prevIsSyncing.current = isSyncing;
    if (!justFinished) return;

    let cancelled = false;
    let doneTimer: ReturnType<typeof setTimeout> | undefined;

    // Fetch the server frame list immediately after upload completes.
    // This is critical: mutateFrames() called in handleCameraCapture fires
    // before the sync engine has uploaded, so the frame doesn't exist on the
    // server yet. This call fires once upload is confirmed, ensuring the new
    // frame (with ocr_status "pending") appears in the cache — which then
    // kicks off the polling loop below.
    mutateFrames().then(() => {
      if (cancelled || uploadStatus !== "uploading") return;
      setUploadStatus(queueCount === 0 ? "done" : "idle");
      if (queueCount === 0) {
        doneTimer = setTimeout(() => { if (!cancelled) setUploadStatus("idle"); }, 3000);
      }
    });

    return () => {
      cancelled = true;
      if (doneTimer) clearTimeout(doneTimer);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSyncing, queueCount, uploadStatus]);

  // ── OCR status polling ─────────────────────────────────────────────────────
  // Belt-and-suspenders: if any server frame is still in OCR / privacy scan,
  // poll every 3 s. Stops automatically once all frames are terminal.
  // This useEffect-based approach is more reliable than the SWR refreshInterval
  // function form because it re-evaluates whenever serverFrames changes.
  useEffect(() => {
    const hasPending = serverFrames.some(
      (f) => f.ocr_status !== "done" && f.ocr_status !== "failed" && f.ocr_status !== "skipped",
    );
    if (!hasPending) return;
    const id = setInterval(() => mutateFrames(), 3000);
    return () => clearInterval(id);
  }, [serverFrames, mutateFrames]);

  // ── Camera capture → IDB → sync ──────────────────────────────────────────
  const handleCameraCapture = useCallback(async (blob: Blob) => {
    const id    = generateUUID();
    const seqNo = (framesDataRef.current?.total ?? 0) + queueCountRef.current + 1;

    setUploadStatus("saving");
    setUploadedKb(undefined);

    try {
      const compressed = await compressImage(blob);
      const sizeKb     = Math.round(compressed.size / 1024);
      setUploadedKb(sizeKb);

      await addPendingFrame({
        id, sessionId,
        sequenceNo: seqNo,
        blob:       compressed,
        capturedAt: new Date().toISOString(),
        sizeKb,
      });

      // Add to local preview strip immediately (no server round-trip needed)
      const blobUrl = URL.createObjectURL(compressed);
      blobUrlsRef.current.push(blobUrl);
      setLocalFrames((prev) => [
        {
          id, blobUrl, sequenceNo: seqNo,
          capturedAt: new Date().toISOString(),
          sizeKb, syncStatus: "pending", errorMessage: null,
        },
        ...prev,
      ]);

      refreshCounts();
      mutateFrames();

      if (isOnline) {
        setUploadStatus("uploading");
        triggerSync();
      } else {
        setUploadStatus("idle");
        showBanner(true, "Saved locally — will upload when back online.");
      }
    } catch {
      setUploadStatus("error");
      showBanner(false, "Failed to save frame locally.");
    }
  }, [sessionId, isOnline, triggerSync, refreshCounts, mutateFrames]);

  // ── File upload tab ────────────────────────────────────────────────────────
  const [isFileUploading, setIsFileUploading] = useState(false);
  const [dragOver,        setDragOver]        = useState(false);
  const [preview,         setPreview]         = useState<string | null>(null);
  const [file,            setFile]            = useState<File | null>(null);

  function handleFile(f: File) {
    if (!f.type.startsWith("image/")) return;
    setFile(f);
    const reader = new FileReader();
    reader.onload = (e) => setPreview(e.target?.result as string);
    reader.readAsDataURL(f);
  }
  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  }
  async function handleFileUpload() {
    if (!file) return;
    setIsFileUploading(true);
    try {
      const blob = new Blob([await file.arrayBuffer()], { type: file.type });
      await handleCameraCapture(blob);
      setFile(null);
      setPreview(null);
    } catch {
      showBanner(false, "Upload failed.");
    } finally {
      setIsFileUploading(false);
    }
  }
  async function handleGenerateAI() {
    try {
      await api.triggerGeneration(sessionId);
      showBanner(true, "AI generation queued — outputs appear in ~2 min in the Notes tab.");
    } catch {
      showBanner(false, "Could not trigger AI generation.");
    }
  }

  return (
    <div className="space-y-4">

      {/* Lightbox */}
      {lightboxFrame && (
        <Lightbox
          frame={lightboxFrame}
          ocr={lightboxOCR}
          serverFrameId={lightboxFrameId ?? undefined}
          sessionId={sessionId}
          ocrDone={lightboxOcrDone}
          onClose={() => setLightboxFrame(null)}
        />
      )}

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Capture</h1>
          {session && (
            <p className="mt-0.5 text-sm text-slate-500">
              {session.subject ?? "Subject auto-detecting"} · {session.grade ?? "—"} ·{" "}
              {serverFrames.length} frame{serverFrames.length !== 1 ? "s" : ""} on server
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" size="sm" onClick={handleGenerateAI}>
            <Cpu className="h-3.5 w-3.5" /> Generate AI
          </Button>
          <Link href={`/sessions/${sessionId}/notes`}>
            <Button variant="ghost" size="sm">
              Notes <ChevronRight className="h-4 w-4" />
            </Button>
          </Link>
        </div>
      </div>

      {/* Sync status bar */}
      <SyncStatusBar
        isOnline={isOnline}
        isSyncing={isSyncing}
        queueCount={queueCount}
        recordingsPending={recordingsPending}
        secondsUntilAutoSync={secondsUntilAutoSync}
        lastSyncAt={lastSyncAt}
        onSyncNow={triggerSync}
      />

      {/* Tab switcher */}
      <div className="flex gap-1 rounded-xl bg-slate-100 p-1">
        {([
          { id: "camera", icon: Camera, label: "Camera" },
          { id: "video",  icon: Video,  label: "Video" },
          { id: "upload", icon: Upload, label: "Upload" },
        ] as const).map(({ id, icon: Icon, label }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={cn(
              "flex flex-1 touch-manipulation items-center justify-center gap-2 rounded-lg py-2.5 text-sm font-medium transition-colors",
              tab === id ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700",
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Banner */}
      {banner && (
        <div className={cn(
          "flex items-center gap-2 rounded-xl px-4 py-3 text-sm",
          banner.ok ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600",
        )}>
          {banner.ok
            ? <CheckCircle2 className="h-4 w-4 shrink-0" />
            : <AlertCircle  className="h-4 w-4 shrink-0" />
          }
          {banner.message}
        </div>
      )}

      {/* Main grid */}
      <div className="grid gap-4 lg:grid-cols-2">

        {/* Left: Camera or Upload */}
        <Card>
          <CardHeader>
            <CardTitle>
              {tab === "camera" ? "Live Camera" : tab === "video" ? "Video Recording" : "Upload Image"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {tab === "camera" ? (
              <div className="space-y-3">

                {/* ── Auto-capture interval picker (always visible) ─────────── */}
                <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 space-y-2">
                  {/* Interval row */}
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="flex items-center gap-1.5 text-xs font-medium text-slate-600">
                      <Timer className="h-3.5 w-3.5 text-slate-400" />
                      Auto-capture every:
                    </span>
                    {([
                      { label: "Off",  val: 0  },
                      { label: "5s",   val: 5  },
                      { label: "10s",  val: 10 },
                      { label: "20s",  val: 20 },
                      { label: "30s",  val: 30 },
                      { label: "60s",  val: 60 },
                    ] as const).map(({ label, val }) => (
                      <button
                        key={val}
                        onClick={() => setCaptureIntervalSec(val)}
                        className={cn(
                          "rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors",
                          captureIntervalSec === val
                            ? "bg-indigo-600 text-white"
                            : "bg-white border border-slate-200 text-slate-600 hover:border-indigo-300",
                        )}
                      >
                        {label}
                      </button>
                    ))}
                  </div>

                  {/* Auto-stop duration row (only shown when a capture interval is selected) */}
                  {captureIntervalSec > 0 && (
                    <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-slate-200">
                      <span className="flex items-center gap-1.5 text-xs font-medium text-slate-500">
                        <Timer className="h-3 w-3 text-slate-300" />
                        Auto-stop after:
                      </span>
                      {([
                        { label: "No limit", val: 0  },
                        { label: "15 min",   val: 15 },
                        { label: "30 min",   val: 30 },
                        { label: "45 min",   val: 45 },
                        { label: "60 min",   val: 60 },
                      ] as const).map(({ label, val }) => (
                        <button
                          key={val}
                          onClick={() => setSessionDurationMin(val)}
                          className={cn(
                            "rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors",
                            sessionDurationMin === val
                              ? "bg-slate-700 text-white"
                              : "bg-white border border-slate-200 text-slate-500 hover:border-slate-400",
                          )}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {/* Audio recording section */}
                <div className="rounded-xl border border-slate-200 bg-slate-50 overflow-hidden">
                  {/* Controls row */}
                  <div className="px-3 py-2.5 flex items-center gap-3 flex-wrap">
                    <span className="flex items-center gap-1.5 text-xs font-medium text-slate-600">
                      <Mic className="h-3.5 w-3.5 text-slate-400" />
                      Audio:
                    </span>
                    {audioState === "idle" && (
                      <>
                        <button
                          onClick={startRecording}
                          className="flex items-center gap-1.5 rounded-full bg-rose-600 px-3 py-1 text-xs font-medium text-white hover:bg-rose-700 transition-colors"
                        >
                          <Mic className="h-3 w-3" /> {serverRecordings.length > 0 ? "Record Another" : "Start Recording"}
                        </button>
                        <button
                          onClick={() => audioFileInputRef.current?.click()}
                          className="flex items-center gap-1.5 rounded-full border border-slate-300 bg-white px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100 transition-colors"
                        >
                          <Upload className="h-3 w-3" /> Upload Recording
                        </button>
                        <input
                          ref={audioFileInputRef}
                          type="file"
                          accept="audio/*"
                          className="hidden"
                          onChange={(e) => {
                            const file = e.target.files?.[0];
                            if (file) void uploadFile(file);
                            e.target.value = ""; // allow picking the same file again later
                          }}
                        />
                      </>
                    )}
                    {audioState === "recording" && (
                      <>
                        <span className="flex items-center gap-1.5 text-xs font-semibold text-rose-600">
                          <span className="inline-block h-2 w-2 rounded-full bg-rose-500 animate-pulse" />
                          Recording {fmtDuration(recordingSec)}
                        </span>
                        <button
                          onClick={stopAndUpload}
                          className="flex items-center gap-1.5 rounded-full bg-slate-700 px-3 py-1 text-xs font-medium text-white hover:bg-slate-800 transition-colors"
                        >
                          <Square className="h-3 w-3" /> Stop & Upload
                        </button>
                      </>
                    )}
                    {audioState === "uploading" && (
                      <span className="flex items-center gap-1.5 text-xs text-indigo-600">
                        <CloudUpload className="h-3.5 w-3.5 animate-pulse" /> Transcribing…
                      </span>
                    )}
                    {audioState === "error" && (
                      <span className="flex items-center gap-1.5 text-xs text-red-600">
                        <MicOff className="h-3.5 w-3.5" /> Mic access denied or upload failed
                      </span>
                    )}
                    {serverRecordings.length > 0 && audioState === "idle" && (
                      <span className="ml-auto text-[0.6875rem] text-slate-400">
                        {serverRecordings.length} recording{serverRecordings.length > 1 ? "s" : ""}
                      </span>
                    )}
                  </div>

                  {/* Recordings list */}
                  {serverRecordings.length > 0 && (
                    <div className="border-t border-slate-200 divide-y divide-slate-100">
                      {serverRecordings.map((rec) => (
                        <RecordingRow
                          key={rec.audio_id}
                          recording={rec}
                          onDelete={async () => {
                            await api.deleteAudio(sessionId, rec.audio_id);
                            mutateAudio();
                          }}
                          onRetry={async () => {
                            await api.retryTranscription(sessionId, rec.audio_id);
                            mutateAudio();
                          }}
                        />
                      ))}
                    </div>
                  )}
                </div>

                <CameraCapture
                  onCapture={handleCameraCapture}
                  uploadStatus={uploadStatus}
                  uploadedKb={uploadedKb}
                  isOnline={isOnline}
                  intervalSec={captureIntervalSec > 0 ? captureIntervalSec : undefined}
                  stopAfterMinutes={sessionDurationMin > 0 ? sessionDurationMin : undefined}
                  onAutoCaptureStopped={() =>
                    showBanner(true, "Auto-capture stopped — session time limit reached.")
                  }
                  disabled={!session}
                  autoStart={autostartParam === "camera"}
                />
              </div>
            ) : tab === "video" ? (
              /* ── Video recording tab ─────────────────────────────────────── */
              <div className="space-y-3">

                {/* Board recording preview — wraps video + controls; becomes fullscreen overlay when expanded */}
                <div className={cn(
                  videoFullscreen && videoState === "recording"
                    ? "fixed inset-0 z-50 flex flex-col bg-black"
                    : "contents",
                )}>
                  <video
                    ref={videoPreviewRef}
                    autoPlay
                    muted
                    playsInline
                    style={{
                      display: videoState === "recording" ? "block" : "none",
                      width: "100%",
                      borderRadius: videoFullscreen ? 0 : 12,
                      background: "#000",
                      ...(videoFullscreen
                        ? { flex: 1, objectFit: "cover" }
                        : { aspectRatio: "16 / 9", objectFit: "cover" }),
                    }}
                  />

                  {/* Recording controls bar */}
                  {videoState === "recording" && (
                    <div className={cn(
                      "flex items-center justify-between",
                      videoFullscreen
                        ? "absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/90 via-black/50 to-transparent px-5 pb-8 pt-16"
                        : "rounded-xl bg-rose-50 border border-rose-100 px-4 py-3",
                    )}>
                      <div className="flex items-center gap-2">
                        <span className="h-2.5 w-2.5 rounded-full bg-rose-500 animate-pulse" />
                        <div className="flex flex-col">
                          <span className={cn("text-sm font-semibold leading-tight", videoFullscreen ? "text-white" : "text-rose-600")}>
                            {videoSegmentIndex > 1 && `Seg ${videoSegmentIndex} · `}{fmtDuration(videoSec)} total
                          </span>
                          <span className={cn("text-[0.625rem] leading-tight", videoFullscreen ? "text-white/50" : "text-rose-400")}>
                            auto-saves in {fmtCountdown(Math.max(0, SEGMENT_SEC - (videoSec % SEGMENT_SEC)))}
                          </span>
                        </div>
                        {videoHasAudio
                          ? <span className={cn("flex items-center gap-1 text-[0.625rem] font-semibold rounded-full px-2 py-0.5",
                              videoFullscreen ? "text-green-300 bg-green-900/50" : "text-green-700 bg-green-50 border border-green-200"
                            )}><Mic className="h-2.5 w-2.5" />Audio</span>
                          : <span className={cn("flex items-center gap-1 text-[0.625rem] font-semibold rounded-full px-2 py-0.5",
                              videoFullscreen ? "text-amber-300 bg-amber-900/50" : "text-amber-700 bg-amber-50 border border-amber-200"
                            )}><MicOff className="h-2.5 w-2.5" />No mic</span>
                        }
                      </div>
                      <div className="flex items-center gap-2">
                        {/* Fullscreen toggle */}
                        <button
                          onClick={() => setVideoFullscreen((v) => !v)}
                          className={cn(
                            "flex h-8 w-8 items-center justify-center rounded-full transition-colors touch-manipulation",
                            videoFullscreen
                              ? "bg-white/20 text-white hover:bg-white/30"
                              : "bg-slate-100 text-slate-600 hover:bg-slate-200",
                          )}
                          aria-label={videoFullscreen ? "Exit fullscreen" : "Go fullscreen"}
                        >
                          {videoFullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
                        </button>
                        <button
                          onClick={() => { setVideoFullscreen(false); cancelVideo(); }}
                          className={cn(
                            "flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors touch-manipulation",
                            videoFullscreen
                              ? "bg-white/20 text-white hover:bg-white/30"
                              : "bg-white border border-slate-200 text-slate-600 hover:bg-slate-50",
                          )}
                        >
                          <X className="h-3 w-3" /> Cancel
                        </button>
                        <button
                          onClick={() => { setVideoFullscreen(false); stopVideo(); }}
                          className={cn(
                            "flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium text-white transition-colors touch-manipulation",
                            videoFullscreen
                              ? "bg-rose-600 hover:bg-rose-700 shadow-lg"
                              : "bg-slate-800 hover:bg-slate-900",
                          )}
                        >
                          <StopCircle className="h-3 w-3" /> Stop & Upload
                        </button>
                      </div>
                    </div>
                  )}
                </div>

                {/* ── Audience Analysis section — independent of recording state ── */}
                <div className="rounded-xl border border-indigo-100 bg-indigo-50/40 overflow-hidden">
                  {/* Header row */}
                  <div className="flex items-center justify-between px-4 py-2.5 border-b border-indigo-100">
                    <div className="flex items-center gap-2">
                      <Users className="h-4 w-4 text-indigo-500" />
                      <span className="text-sm font-semibold text-indigo-800">Audience Analysis</span>
                      {audienceState === "active" && (
                        <span className="flex items-center gap-1 text-[0.625rem] font-semibold text-indigo-600 bg-indigo-100 rounded-full px-2 py-0.5">
                          <span className="h-1.5 w-1.5 rounded-full bg-indigo-500 animate-pulse" />
                          LIVE
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {/* Camera flip button — only when active */}
                      {audienceState === "active" && (
                        <button
                          onClick={toggleAudienceCamera}
                          title={`Switch to ${audienceFacing === "user" ? "rear" : "front"} camera`}
                          className="flex items-center gap-1 rounded-full bg-white border border-indigo-200 px-2.5 py-1 text-[0.6875rem] font-medium text-indigo-700 hover:bg-indigo-50 transition-colors"
                        >
                          <RefreshCw className="h-3 w-3" />
                          {audienceFacing === "user" ? "Rear cam" : "Front cam"}
                        </button>
                      )}
                      {/* Main start / stop button */}
                      {(audienceState === "off" || audienceState === "error") ? (
                        <button
                          onClick={() => startAudience("user")}
                          className="flex items-center gap-1.5 rounded-full bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 transition-colors"
                        >
                          <Eye className="h-3 w-3" /> Start Analysis
                        </button>
                      ) : audienceState === "loading" ? (
                        <span className="text-[0.6875rem] text-indigo-400 font-medium px-2">Loading model…</span>
                      ) : (
                        <button
                          onClick={() => { setAudienceFullscreen(false); stopAudience(); }}
                          className="flex items-center gap-1.5 rounded-full bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-700 transition-colors"
                        >
                          <Square className="h-3 w-3" /> Stop Analysis
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Error state — descriptive message + retry */}
                  {audienceState === "error" && (
                    <div className="px-4 py-3 flex items-start gap-3 bg-red-50 border-b border-red-100">
                      <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 shrink-0" />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-semibold text-red-700">Could not start camera</p>
                        <p className="text-[0.6875rem] text-red-500 mt-0.5 leading-relaxed">
                          {audienceError || "Camera access failed — check permissions and try again."}
                        </p>
                      </div>
                      <button
                        onClick={() => startAudience("user")}
                        className="shrink-0 rounded-md bg-red-600 px-2.5 py-1 text-[0.6875rem] font-semibold text-white hover:bg-red-700"
                      >
                        Retry
                      </button>
                    </div>
                  )}

                  {/* Loading state */}
                  {audienceState === "loading" && (
                    <div className="px-4 py-4 flex flex-col items-center gap-2 text-center">
                      <Users className="h-7 w-7 text-indigo-400 animate-pulse" />
                      <p className="text-sm font-medium text-indigo-700">Loading face analysis…</p>
                      <p className="text-xs text-indigo-400">Downloading MediaPipe model (~10 MB, cached after first use)</p>
                    </div>
                  )}

                  {/* Active: camera preview + live stats */}
                  {audienceState === "active" && (
                    <div className={cn(
                      audienceFullscreen
                        ? "fixed inset-0 z-50 flex flex-col bg-black"
                        : "contents",
                    )}>
                      {/* Camera feed */}
                      <div className={cn("relative bg-black", audienceFullscreen && "flex-1")}>
                        <video
                          ref={audienceVideoRef}
                          autoPlay
                          muted
                          playsInline
                          style={{
                            width: "100%",
                            display: "block",
                            objectFit: "cover",
                            ...(audienceFullscreen
                              ? { height: "100%", position: "absolute", inset: 0 }
                              : { aspectRatio: "4 / 3" }),
                          }}
                        />
                        {/* Per-face overlay canvas — face numbers + emotion badges */}
                        <canvas
                          ref={audienceCanvasRef}
                          style={{
                            position: "absolute", top: 0, left: 0,
                            width: "100%", height: "100%",
                            pointerEvents: "none",
                          }}
                        />
                        {/* Live stats overlay */}
                        <div className={cn(
                          "absolute bg-black/65 backdrop-blur-sm px-3 py-2 flex flex-col gap-1.5",
                          audienceFullscreen
                            ? "inset-x-0 bottom-0 rounded-none pb-8"
                            : "bottom-2 left-2 right-2 rounded-lg",
                        )}>
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-1.5 text-white">
                              <Users className="h-3.5 w-3.5 text-indigo-300" />
                              <span className="text-xs font-semibold">{audienceStats.facesDetected} faces</span>
                            </div>
                            <div className="flex items-center gap-1.5">
                              <Eye className="h-3.5 w-3.5 text-green-300" />
                              <span className={`text-xs font-bold ${
                                audienceStats.attentionPct >= 70 ? "text-green-300" :
                                audienceStats.attentionPct >= 40 ? "text-amber-300" : "text-red-300"
                              }`}>
                                {audienceStats.attentionPct}% attentive
                              </span>
                            </div>
                            <span className="text-[0.625rem] text-slate-400">
                              {audienceFacing === "user" ? "Front" : "Rear"} · Min {audienceStats.minuteNumber}
                            </span>
                            {/* Fullscreen toggle */}
                            <button
                              onClick={() => setAudienceFullscreen((v) => !v)}
                              className="flex h-7 w-7 items-center justify-center rounded-full bg-white/20 text-white hover:bg-white/30 transition-colors touch-manipulation"
                              aria-label={audienceFullscreen ? "Exit fullscreen" : "Go fullscreen"}
                            >
                              {audienceFullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
                            </button>
                          </div>
                          {/* Emotion row */}
                          <div className="flex items-center gap-1.5">
                            <span className="text-base leading-none" title={audienceStats.dominantEmotion}>
                              {EMOTION_EMOJI[audienceStats.dominantEmotion] ?? "😐"}
                            </span>
                            <span className="text-[0.625rem] text-slate-300 capitalize">{audienceStats.dominantEmotion}</span>
                            {audienceAnalyzing && (
                              <span className="ml-1 text-[0.5625rem] text-indigo-300 animate-pulse">Analysing…</span>
                            )}
                            <span className="ml-auto flex items-center gap-1">
                              {(["happy","confused","surprised","disengaged"] as const).map((e) => (
                                audienceStats.emotions[e] > 5 ? (
                                  <span key={e} className="text-[0.5625rem] font-semibold" style={{ color: EMOTION_COLOR[e] }}>
                                    {EMOTION_EMOJI[e]}{audienceStats.emotions[e]}%
                                  </span>
                                ) : null
                              ))}
                            </span>
                          </div>
                          {/* Analysis failure — backend unreachable or errored */}
                          {audienceAnalysisError && (
                            <div className="flex items-center gap-1 pt-0.5 border-t border-white/10">
                              <AlertCircle className="h-3 w-3 text-red-300 shrink-0" />
                              <span className="text-[0.5625rem] text-red-300 truncate">
                                Analysis failed: {audienceAnalysisError}
                              </span>
                            </div>
                          )}
                          {/* Zone breakdown row — shown when backend returns zone data */}
                          {audienceZoneStats && (audienceZoneStats.front.count + audienceZoneStats.middle.count + audienceZoneStats.back.count) > 0 && (
                            <div className="flex items-center gap-2 pt-0.5 border-t border-white/10">
                              {(["front","middle","back"] as const).map((zone) => {
                                const z = audienceZoneStats[zone];
                                if (!z || z.count === 0) return null;
                                const color = zone === "front" ? "#22c55e" : zone === "middle" ? "#f59e0b" : "#ef4444";
                                return (
                                  <span key={zone} className="flex items-center gap-0.5 text-[0.5625rem] font-semibold">
                                    <span className="h-1.5 w-1.5 rounded-full inline-block" style={{ backgroundColor: color }} />
                                    <span className="text-slate-300 capitalize">{zone[0].toUpperCase()}</span>
                                    <span className="text-white">{z.count}</span>
                                    <span className="text-slate-400">{Math.round(z.attention_pct)}%</span>
                                  </span>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      </div>
                      {/* Inline engagement report — hidden in fullscreen */}
                      {!audienceFullscreen && (
                        <AudienceInlineReport sessionId={sessionId} liveMinute={audienceStats.minuteNumber} liveAtt={audienceStats.attentionPct} />
                      )}
                    </div>
                  )}

                  {/* Off state: description */}
                  {audienceState === "off" && (
                    <div className="px-4 py-3 text-xs text-indigo-500 leading-relaxed">
                      Point camera at your students to track face count, attention %, and engagement minute-by-minute.
                      Works with front or rear camera.
                    </div>
                  )}
                </div>

                {/* Idle / error: start board recording button */}
                {(videoState === "idle" || videoState === "error") && (
                  <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-center space-y-3">
                    <div className="flex justify-center">
                      <Video className="h-10 w-10 text-slate-300" />
                    </div>
                    <div>
                      <p className="text-sm font-medium text-slate-700">Record board + audio</p>
                      <p className="text-xs text-slate-400 mt-0.5">
                        Auto-saves every 5 min · frames every 10 s · audio transcribed
                      </p>
                    </div>
                    {videoState === "error" && (
                      <p className="text-xs text-red-500">Upload failed — tap to try again</p>
                    )}
                    <button
                      onClick={startVideo}
                      className="inline-flex items-center gap-2 rounded-full bg-rose-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-rose-700 transition-colors"
                    >
                      <Video className="h-4 w-4" /> Start Recording
                    </button>
                  </div>
                )}

                {/* Uploading */}
                {videoState === "uploading" && (
                  <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-4 text-center space-y-2">
                    <CloudUpload className="h-8 w-8 text-indigo-500 animate-pulse mx-auto" />
                    <p className="text-sm font-semibold text-indigo-700">
                      Uploading{uploadSizeMb > 0 ? ` ${uploadSizeMb} MB` : ""}…
                    </p>
                    {uploadSizeMb > 5 && uploadProgress > 0 && (
                      <div className="space-y-1">
                        <div className="h-2 w-full rounded-full bg-indigo-100 overflow-hidden">
                          <div
                            className="h-full rounded-full bg-indigo-500 transition-all duration-300"
                            style={{ width: `${uploadProgress}%` }}
                          />
                        </div>
                        <p className="text-xs text-indigo-500">{uploadProgress}% uploaded</p>
                      </div>
                    )}
                    {(uploadSizeMb <= 5 || uploadProgress === 0) && (
                      <p className="text-xs text-indigo-400">
                        {uploadSizeMb > 5 ? "Large file — splitting into chunks…" : "Sending to server…"}
                      </p>
                    )}
                    <p className="text-[0.6875rem] text-slate-400">
                      {videoSegmentIndex > 1 ? `Uploading segment ${videoSegmentIndex} of ${videoSegmentIndex} · ` : ""}Frame extraction + transcription run in background
                    </p>
                  </div>
                )}

                {/* Video recordings list */}
                {(() => {
                  const videoRecs = serverRecordings.filter(r => r.source === "video");
                  if (!videoRecs.length) return null;
                  return (
                    <div className="rounded-xl border border-violet-200 bg-violet-50/40 overflow-hidden">
                      <div className="px-3 py-2 flex items-center justify-between">
                        <span className="text-xs font-semibold text-violet-700 flex items-center gap-1.5">
                          <Video className="h-3.5 w-3.5" />
                          {videoRecs.length} video recording{videoRecs.length > 1 ? "s" : ""}
                        </span>
                        <span className="text-[0.6875rem] text-violet-400">
                          {videoRecs.reduce((s, r) => s + (r.whisper_tokens || 0), 0).toLocaleString()} tokens used
                        </span>
                      </div>
                      <div className="border-t border-violet-100 divide-y divide-violet-100">
                        {videoRecs.map((rec) => (
                          <RecordingRow
                            key={rec.audio_id}
                            recording={rec}
                            onDelete={async () => {
                              await api.deleteAudio(sessionId, rec.audio_id);
                              mutateAudio();
                            }}
                            onRetry={async () => {
                              await api.retryTranscription(sessionId, rec.audio_id);
                              mutateAudio();
                            }}
                          />
                        ))}
                      </div>
                      <div className="border-t border-violet-100 px-3 py-2.5">
                        <Link
                          href={`/sessions/${sessionId}/class-analysis`}
                          className="inline-flex items-center gap-1.5 text-xs font-semibold text-violet-700 hover:text-violet-900 transition-colors"
                        >
                          View Class Analysis <ChevronRight className="h-3.5 w-3.5" />
                        </Link>
                      </div>
                    </div>
                  );
                })()}

                <div className="rounded-lg bg-amber-50 border border-amber-100 px-3 py-2 text-xs text-amber-700 space-y-0.5">
                  <p className="font-semibold">Tips</p>
                  <p>Hold phone steady · ensure board is well-lit · speak clearly near the mic</p>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <div
                  onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={onDrop}
                  onClick={() => document.getElementById("aci-file-input")?.click()}
                  className={cn(
                    "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-10 transition-colors",
                    dragOver
                      ? "border-indigo-400 bg-indigo-50"
                      : "border-slate-200 bg-slate-50 hover:border-indigo-300 hover:bg-indigo-50/40",
                  )}
                >
                  {preview ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={preview} alt="Preview" className="max-h-48 rounded-lg object-contain shadow" />
                  ) : (
                    <>
                      <ImagePlus className="h-10 w-10 text-slate-300" />
                      <div className="text-center">
                        <p className="text-sm font-medium text-slate-700">Drop image or click to browse</p>
                        <p className="mt-1 text-xs text-slate-400">JPEG or PNG · max 10 MB</p>
                      </div>
                    </>
                  )}
                </div>
                <input
                  id="aci-file-input"
                  type="file"
                  accept="image/jpeg,image/png,image/jpg"
                  className="hidden"
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
                />
                {file && (
                  <div className="flex items-center gap-2 rounded-lg bg-slate-50 p-3 text-sm">
                    <FileImage className="h-4 w-4 shrink-0 text-indigo-500" />
                    <span className="truncate text-slate-700">{file.name}</span>
                    <span className="ml-auto shrink-0 text-slate-400">{(file.size / 1024).toFixed(0)} KB</span>
                  </div>
                )}
                <Button onClick={handleFileUpload} loading={isFileUploading} disabled={!file} className="w-full">
                  <Upload className="h-4 w-4" />
                  {isFileUploading ? "Processing…" : "Upload Frame"}
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Right: Frame thumbnail grid */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <CardTitle>Captured Frames</CardTitle>
              {localFrames.length > 0 && (
                <span className="text-sm text-slate-400">{localFrames.length} total</span>
              )}
            </div>
            {/* Legend */}
            <div className="flex items-center gap-3 text-[0.625rem] text-slate-400">
              <span className="flex items-center gap-1">
                <ShieldCheck className="h-3 w-3 text-green-500" /> Privacy OK
              </span>
              <span className="flex items-center gap-1">
                <Shield className="h-3 w-3 text-slate-300" /> Scanning
              </span>
            </div>
          </CardHeader>
          <CardContent>
            <ThumbnailStrip
              localFrames={localFrames}
              serverFrameMap={serverFrameMap}
              sessionId={sessionId}
              onSelect={setLightboxFrame}
            />

            {/* Offline info banner */}
            {!isOnline && localFrames.length > 0 && (
              <div className="mt-4 flex items-center gap-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2.5 text-xs text-amber-700">
                <WifiOff className="h-4 w-4 shrink-0" />
                <span>
                  <strong>{queueCount} frame{queueCount !== 1 ? "s" : ""}</strong> saved locally.
                  All photos are stored on this device and will upload automatically when WiFi reconnects.
                </span>
              </div>
            )}
          </CardContent>
        </Card>

      </div>

      {/* Camera requirements info */}
      <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
        <p className="text-xs font-semibold text-slate-600 mb-1">📷 Camera Requirements</p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs text-slate-500">
          <span>✓ Min 2 MP (1080p preferred)</span>
          <span>✓ Fixed mount works best</span>
          <span>✓ Even lighting, no glare</span>
          <span>✓ 0.5–4 m from board</span>
        </div>
      </div>

    </div>
  );
}
 
