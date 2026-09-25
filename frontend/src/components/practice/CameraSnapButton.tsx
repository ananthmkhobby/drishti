"use client";

/**
 * A "Capture" button that opens a real live-camera preview (getUserMedia)
 * and takes a single photo — NOT a file input.
 *
 * Why this exists: <input type="file" capture="environment"> only launches
 * the native camera app on mobile browsers. On desktop (where this app is
 * routinely tested — see the guided-practice manual-capture spot-check),
 * that attribute is silently ignored and the input just opens a plain file
 * browser, which reads as "clicking Capture asks me to browse files"
 * instead of showing a camera. This opens an actual camera preview on
 * both desktop (webcam) and mobile, with "Choose a photo instead" kept as
 * an explicit fallback for machines with no camera at all.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Camera, RotateCcw, Check, X, Upload, Loader2, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/Button";

type ModalState = "requesting" | "live" | "captured" | "error";

// A kiosk browser with no camera permission pre-granted (or none plugged
// in) can leave getUserMedia's promise simply never settling instead of
// rejecting — reported as the modal "just hanging" with nothing to do but
// force-close it. This bounds the wait so it always lands somewhere.
const CAMERA_REQUEST_TIMEOUT_MS = 10_000;

export function CameraSnapButton({
  onCapture, label = "Capture", size = "sm", disabled = false, wide = false,
}: {
  onCapture: (blob: Blob) => void | Promise<void>;
  label?: string;
  size?: "sm" | "md" | "lg";
  disabled?: boolean;
  /**
   * A much larger, wider preview — for framing several students' notebooks
   * side by side in one shot (batch-scan) rather than a single close-up
   * page, where the normal compact modal makes it too hard to see whether
   * everyone's actually in frame before snapping.
   */
  wide?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<ModalState>("requesting");
  const [errorMsg, setErrorMsg] = useState("");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const blobRef = useRef<Blob | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const timedOutRef = useRef(false);
  const requestTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearRequestTimeout = useCallback(() => {
    if (requestTimeoutRef.current) {
      clearTimeout(requestTimeoutRef.current);
      requestTimeoutRef.current = null;
    }
  }, []);

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  const startCamera = useCallback(async () => {
    setState("requesting");
    setErrorMsg("");
    timedOutRef.current = false;
    clearRequestTimeout();
    requestTimeoutRef.current = setTimeout(() => {
      timedOutRef.current = true;
      setState("error");
      setErrorMsg("Camera didn't respond — check that this device allows camera access, or choose a photo instead.");
    }, CAMERA_REQUEST_TIMEOUT_MS);

    try {
      // frameRate: same fix as CameraCapture.tsx — an unconstrained live
      // preview decodes at the camera's max fps (often 30) continuously,
      // real sustained CPU load on the Pi that a still-photo capture never
      // benefits from. `ideal` so a camera that can't hit 15 just falls
      // back to its own default instead of failing to start.
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment", width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal: 15 } },
        audio: false,
      });
      clearRequestTimeout();
      if (timedOutRef.current) {
        // The timeout already moved the UI on — don't resurrect a camera
        // feed the person has already been told to give up on.
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => {});
      }
      setState("live");
    } catch (err) {
      clearRequestTimeout();
      if (timedOutRef.current) return;
      setState("error");
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMsg(/Permission|NotAllowed|denied/i.test(msg)
        ? "Camera permission denied — allow camera access, or choose a photo instead."
        : "No camera available — choose a photo instead.");
    }
  }, [clearRequestTimeout]);

  function openModal() {
    setOpen(true);
    startCamera();
  }

  function closeModal() {
    clearRequestTimeout();
    stopStream();
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    blobRef.current = null;
    setOpen(false);
  }

  useEffect(() => () => { clearRequestTimeout(); stopStream(); }, [clearRequestTimeout, stopStream]);

  function snap() {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || state !== "live") return;
    canvas.width = video.videoWidth || 1280;
    canvas.height = video.videoHeight || 960;
    canvas.getContext("2d")!.drawImage(video, 0, 0);
    canvas.toBlob((blob) => {
      if (!blob) return;
      blobRef.current = blob;
      setPreviewUrl(URL.createObjectURL(blob));
      stopStream();
      setState("captured");
    }, "image/jpeg", 0.9);
  }

  function retake() {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    blobRef.current = null;
    startCamera();
  }

  async function confirm() {
    if (!blobRef.current) return;
    setSubmitting(true);
    try {
      await onCapture(blobRef.current);
      closeModal();
    } finally {
      setSubmitting(false);
    }
  }

  async function handleFileFallback(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setSubmitting(true);
    try {
      await onCapture(file);
      closeModal();
    } finally {
      setSubmitting(false);
    }
  }

  const modalTitle = state === "captured" ? "Review photo" : state === "error" ? "Camera unavailable" : "Take a photo";

  return (
    <>
      <Button size={size} onClick={openModal} disabled={disabled}>
        <Camera className="h-3.5 w-3.5" /> {label}
      </Button>

      {/* Portaled to document.body — confirmed live 2026-09-21: this button
          is normally rendered inside a `cc-rise`-animated ancestor (see the
          guided-practice hero/cards), and `cc-rise`'s `animation-fill-mode:
          both` leaves `transform: translateY(0)` on that element forever
          after the animation settles. A transform on ANY ancestor creates a
          new containing block for `position: fixed` descendants — so this
          modal was never actually covering the real viewport, just the
          nearest transformed ancestor's box, which is why it looked cramped
          (especially obvious once `wide` made the card bigger than that
          box). Rendering outside the whole tree via a portal sidesteps this
          regardless of which ancestor(s) a future caller wraps it in. */}
      {open && createPortal(
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className={`flex max-h-full w-full flex-col overflow-y-auto rounded-2xl bg-white shadow-xl ${wide ? "max-w-5xl" : "max-w-md"}`}>
            <div className="flex shrink-0 items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
              <p className="text-sm font-semibold text-slate-800">{modalTitle}</p>
              <button
                onClick={closeModal}
                className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-slate-500 hover:bg-slate-100"
              >
                <X className="h-3.5 w-3.5" /> Cancel
              </button>
            </div>

            <div className={`relative shrink-0 bg-black ${wide ? "aspect-video" : "aspect-[4/3]"}`}>
              {state === "captured" && previewUrl ? (
                <img src={previewUrl} alt="captured" className="h-full w-full object-cover" />
              ) : (
                <video ref={videoRef} playsInline muted className="h-full w-full object-cover" />
              )}
              <canvas ref={canvasRef} className="hidden" />

              {state === "requesting" && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-white/70">
                  <Loader2 className="h-6 w-6 animate-spin" />
                  <p className="text-xs">Requesting camera…</p>
                </div>
              )}
              {state === "error" && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-center px-6 text-white/80">
                  <AlertTriangle className="h-6 w-6 text-amber-400" />
                  <p className="text-xs">{errorMsg}</p>
                </div>
              )}
            </div>

            <div className="flex shrink-0 flex-wrap items-center justify-center gap-2 p-3">
              <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={handleFileFallback} />

              {state === "live" && (
                <button
                  onClick={snap}
                  aria-label="Take photo"
                  className="flex h-14 w-14 items-center justify-center rounded-full bg-indigo-600 text-white hover:bg-indigo-700"
                >
                  <Camera className="h-5 w-5" />
                </button>
              )}
              {state === "captured" && (
                <div className="flex items-center gap-2">
                  <Button size="sm" variant="secondary" onClick={retake}>
                    <RotateCcw className="h-3.5 w-3.5" /> Retake
                  </Button>
                  <Button size="sm" loading={submitting} onClick={confirm}>
                    <Check className="h-3.5 w-3.5" /> Use photo
                  </Button>
                </div>
              )}
              {state === "error" && (
                <Button size="sm" variant="secondary" onClick={startCamera}>
                  <RotateCcw className="h-3.5 w-3.5" /> Try again
                </Button>
              )}

              <button
                onClick={() => fileRef.current?.click()}
                className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium text-slate-500 hover:bg-slate-100"
                title="Choose a photo instead"
              >
                <Upload className="h-3.5 w-3.5" /> Choose a photo
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
