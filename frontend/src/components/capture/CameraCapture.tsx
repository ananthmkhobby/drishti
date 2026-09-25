"use client";

/**
 * CameraCapture — PWA-compatible mobile-first camera capture component.
 *
 * ## Flow
 *
 *   idle ──► requesting ──► active ──► [shutter] ──► captured
 *                                          ▲          │         │
 *                                          └──retake──┘   confirm
 *                                                               │
 *                                                         onCapture(blob)
 *                                                               │
 *                                                          back to active
 *
 * ## Responsibilities
 *
 *  • Open rear camera by default; front/rear toggle
 *  • Flash feedback on shutter press
 *  • Full-screen preview after capture; Retake / Use Photo choice
 *  • Offline indicator badge in viewfinder (driven by `isOnline` prop)
 *  • Upload status bar after confirmation (driven by `uploadStatus` prop)
 *  • Clear per-step permission-denied instructions for Android Chrome
 *  • Auto-capture mode (time-based sessions) — bypasses preview
 *  • Object URL memory management (revoke on replace/unmount)
 *
 * ## Contract
 *
 *  `onCapture(blob)` fires only when the user taps "Use Photo", never on
 *  shutter press.  The parent handles IDB storage, compression, and upload;
 *  this component is purely capture UX.
 *
 * Android native replacement note:
 *  Replace with CameraX; keep the `onCapture(blob)` signature and the
 *  `UploadStatus` prop so the parent capture page needs no changes.
 */

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import {
  Camera, CameraOff, RefreshCcw,
  Timer, TimerOff,
  Check, RotateCcw,
  Wifi, WifiOff,
  Upload, Loader2,
  AlertCircle, ScanLine, Usb,
  Maximize2, Minimize2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { captureSharpestFrame } from "@/lib/imageQuality";

// ── Types ─────────────────────────────────────────────────────────────────────

type CamState = "idle" | "requesting" | "active" | "flash" | "captured" | "error";

/**
 * Upload lifecycle state reported back from the parent.
 * Drives the status bar shown below the viewfinder after each capture.
 */
export type UploadStatus = "idle" | "saving" | "uploading" | "done" | "error";

export interface CameraCaptureProps {
  /** Fired with the confirmed photo blob — parent is responsible for upload. */
  onCapture: (blob: Blob) => void;
  /**
   * Upload state for the most-recently confirmed photo.
   * Passed down from the parent so the component can show post-capture feedback.
   */
  uploadStatus?: UploadStatus;
  /** Compressed size in KB shown alongside the "Uploaded" confirmation. */
  uploadedKb?: number;
  /** Whether the device currently has network access. */
  isOnline?: boolean;
  /** Enables auto-capture toggle when set (interval in seconds). */
  intervalSec?: number;
  /**
   * Auto-capture will stop automatically after this many minutes (0 = no limit).
   * Only active when auto-mode is running.
   */
  stopAfterMinutes?: number;
  /**
   * Fired when auto-capture stops because the time limit was reached.
   * Parent can use this to show a banner or navigate away.
   */
  onAutoCaptureStopped?: () => void;
  disabled?: boolean;
  className?: string;
  /**
   * Start the camera itself the moment this mounts, skipping the manual
   * "Start Camera" tap — used by the dashboard's "Capture board" shortcut
   * (?autostart=camera) so it lands already primed. Fires once; doesn't
   * re-trigger if the person later stops the camera themselves.
   */
  autoStart?: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const JPEG_QUALITY = 0.92; // at-capture quality; sync engine re-compresses for upload

/**
 * getUserMedia support is a static browser capability (never changes for
 * the life of the page), so there's nothing to subscribe to — but the
 * check itself can only run client-side, and useSyncExternalStore is the
 * React-sanctioned way to read a value that legitimately differs between
 * the server snapshot and the client snapshot without a hydration
 * mismatch (see the `camSupported` usage below).
 */
function subscribeToCamSupport(): () => void {
  return () => {};
}

function getCamSupportSnapshot(): boolean {
  return (
    typeof navigator !== "undefined" &&
    typeof navigator.mediaDevices !== "undefined" &&
    typeof navigator.mediaDevices.getUserMedia === "function"
  );
}

function getCamSupportServerSnapshot(): boolean | null {
  return null;
}

/**
 * Classify a camera label for display.
 * Returns a short tag shown in the device picker alongside the device name.
 */
function deviceTag(label: string): { tag: string; icon: "usb" | "builtin" | "unknown" } {
  if (!label) return { tag: "Camera", icon: "unknown" };
  if (/usb|external|logitech|brio|c\d{3}|c\d{4}|streamcam|mx brio|facecam|razer|elgato|obsbot|insta360|hollyland|dji/i.test(label))
    return { tag: "USB", icon: "usb" };
  if (/facetime|built.?in|integrated|internal|ir camera|apple/i.test(label))
    return { tag: "Built-in", icon: "builtin" };
  return { tag: "Camera", icon: "unknown" };
}

// ── Component ─────────────────────────────────────────────────────────────────

export function CameraCapture({
  onCapture,
  uploadStatus = "idle",
  uploadedKb,
  isOnline = true,
  intervalSec,
  stopAfterMinutes = 0,
  onAutoCaptureStopped,
  disabled,
  className,
  autoStart,
}: CameraCaptureProps) {

  // ── Refs ───────────────────────────────────────────────────────────────────

  const videoRef       = useRef<HTMLVideoElement>(null);
  const canvasRef      = useRef<HTMLCanvasElement>(null);
  const streamRef      = useRef<MediaStream | null>(null);
  const timerRef       = useRef<ReturnType<typeof setInterval> | null>(null);
  /** Tracks the current object URL so cleanup can revoke it on unmount. */
  const previewUrlRef  = useRef<string | null>(null);
  /**
   * Mirror of selectedDeviceId as a ref so startCamera can read the current
   * value without being in the useCallback dep array (avoids stale closure).
   */
  const selectedDeviceIdRef = useRef<string>("");

  // ── State ──────────────────────────────────────────────────────────────────

  const [camState,        setCamState]        = useState<CamState>("idle");
  const [facingBack,      setFacingBack]      = useState(true);
  const [autoMode,        setAutoMode]        = useState(false);
  const [isFullscreen,    setIsFullscreen]    = useState(false);
  const [countdown,       setCountdown]       = useState<number | null>(null);
  /** Remaining seconds for the session duration limit (null = no limit or not started). */
  const [sessionSecsLeft, setSessionSecsLeft] = useState<number | null>(null);
  const sessionTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  /** Last-seen `autoMode`, used to detect the on→off edge during render (see below). */
  const [prevAutoModeForSession, setPrevAutoModeForSession] = useState(autoMode);
  const [errorCode,    setErrorCode]    = useState<string>("");
  const [errorDetail,  setErrorDetail]  = useState<string>("");
  const [captureCount, setCaptureCount] = useState(0);

  // Device picker
  const [videoDevices,     setVideoDevices]     = useState<MediaDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>("");
  const [scanningDevices,  setScanningDevices]  = useState(false);

  // Preview
  const [previewUrl,   setPreviewUrl]   = useState<string | null>(null);
  const [capturedBlob, setCapturedBlob] = useState<Blob | null>(null);
  /** Pixel size of the captured frame, for the resolution chip on the preview screen. */
  const [canvasDims, setCanvasDims] = useState<{ w: number; h: number } | null>(null);

  /**
   * null  = not yet checked (SSR / before first client paint) → render nothing
   * true  = getUserMedia available → show camera UI
   * false = unavailable → show the "not supported" message
   *
   * Server snapshot is always null so the server never renders "Camera not
   * available", which would cause a React 19 hydration mismatch and freeze
   * the UI in the server-rendered state even when the browser actually
   * supports the camera. Once hydrated, React re-evaluates the client
   * snapshot and re-renders with the real value.
   */
  const camSupported = useSyncExternalStore(
    subscribeToCamSupport,
    getCamSupportSnapshot,
    getCamSupportServerSnapshot,
  );

  // ── Keep selectedDeviceIdRef in sync (fixes stale-closure in startCamera) ──

  useEffect(() => {
    selectedDeviceIdRef.current = selectedDeviceId;
  }, [selectedDeviceId]);

  // ── Camera enumeration ────────────────────────────────────────────────────

  const enumerateCameras = useCallback(async (autoSelect = false) => {
    if (typeof navigator === "undefined" || !navigator.mediaDevices) return;
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const cams = devices.filter((d) => d.kind === "videoinput");
      setVideoDevices(cams);
      if (autoSelect || !selectedDeviceIdRef.current) {
        // Prefer environment/rear on phones; prefer external/USB on desktops
        const envCam = cams.find((d) => /back|rear|environment/i.test(d.label));
        const usbCam = cams.find((d) => /usb|logitech|brio|c\d{3}|c\d{4}|streamcam|facecam|razer|elgato|obsbot/i.test(d.label));
        const chosen = envCam ?? usbCam ?? cams[0];
        if (chosen) {
          setSelectedDeviceId(chosen.deviceId);
          selectedDeviceIdRef.current = chosen.deviceId;
        }
      }
    } catch { /* IDB not available or permission denied */ }
  }, []);

  useEffect(() => {
    if (!camSupported) return;

    // enumerateCameras is async — its setState calls happen after
    // `enumerateDevices()` resolves, not synchronously within this effect
    // body, but the linter can't see across the `await` and flags the call
    // site itself.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    enumerateCameras(true);

    // Re-enumerate when a USB camera is plugged/unplugged
    const onDeviceChange = () => enumerateCameras(false);
    navigator.mediaDevices.addEventListener("devicechange", onDeviceChange);
    return () => navigator.mediaDevices.removeEventListener("devicechange", onDeviceChange);
  }, [camSupported, enumerateCameras]);

  // ── Preview URL helpers (always revoke before replacing) ───────────────────

  const revokePrevPreview = useCallback(() => {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = null;
    }
  }, []);

  const setPreview = useCallback((blob: Blob | null) => {
    revokePrevPreview();
    if (!blob) {
      setPreviewUrl(null);
      setCapturedBlob(null);
      return;
    }
    const url = URL.createObjectURL(blob);
    previewUrlRef.current = url;
    setPreviewUrl(url);
    setCapturedBlob(blob);
  }, [revokePrevPreview]);

  // ── Camera lifecycle ───────────────────────────────────────────────────────

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    setAutoMode(false);
    setCountdown(null);
  }, []);

  const startCamera = useCallback(async (back: boolean) => {
    setCamState("requesting");
    setErrorCode("");
    setErrorDetail("");
    stopStream();

    try {
      // Read from ref — avoids stale closure when called from device-change effect.
      // Prefer explicit deviceId (USB webcam / smartboard cam / built-in picker).
      // Fall back to facingMode on phones where deviceId is unreliable.
      const deviceId = selectedDeviceIdRef.current;
      // frameRate was previously unconstrained — the browser/camera driver
      // defaults to its max (often 30fps), meaning this Pi continuously
      // decodes a live 1920x1080 stream at full framerate for as long as
      // the camera page is open, whether or not auto-capture is even
      // running. That's real, sustained CPU load competing with everything
      // else on modest hardware — reported 2026-09-22 as the airmouse
      // cursor sticking/lagging and scrolling running slow specifically on
      // pages with a live camera preview. A capture only ever grabs a
      // single still frame regardless of how many frames/sec were
      // decoded, so this doesn't touch captured-photo resolution/quality
      // at all — `ideal` (not `exact`/`min`) so a camera that can't hit 15
      // just uses its own default instead of failing to start.
      const videoConstraint: MediaTrackConstraints = deviceId
        ? { deviceId: { exact: deviceId }, width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal: 15 } }
        : { facingMode: back ? "environment" : "user", width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal: 15 } };

      const stream = await navigator.mediaDevices.getUserMedia({
        video: videoConstraint,
        audio: false,
      });

      // After first successful stream, labels become available — re-enumerate to
      // populate picker with real names (e.g. "Logitech BRIO 4K" instead of "Camera 1").
      enumerateCameras(false);

      streamRef.current = stream;

      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => {});
      }

      setCamState("active");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);

      if (/Permission|NotAllowed|denied/i.test(msg)) {
        setErrorCode("permission_denied");
      } else if (/NotFound|DevicesNotFound|Requested device not found/i.test(msg)) {
        setErrorCode("no_camera");
      } else if (/OverconstrainedError|Overconstrained/i.test(msg)) {
        // Exact deviceId rejected — clear it and fall back to any available camera
        selectedDeviceIdRef.current = "";
        try {
          const fallback = await navigator.mediaDevices.getUserMedia({
            video: true, audio: false,
          });
          streamRef.current = fallback;
          if (videoRef.current) {
            videoRef.current.srcObject = fallback;
            await videoRef.current.play().catch(() => {});
          }
          setCamState("active");
          return;
        } catch {
          setErrorCode("constraint");
          setErrorDetail("Camera configuration not supported on this device.");
        }
      } else {
        setErrorCode("unknown");
        setErrorDetail(msg || "Camera unavailable.");
      }

      setCamState("error");
    }
  }, [stopStream, enumerateCameras]);

  const handleStop = useCallback(() => {
    stopStream();
    setCamState("idle");
  }, [stopStream]);

  // ── Auto-restart when user picks a different camera device ────────────────
  // Only fires when the camera is already running — selecting while idle is
  // handled by startCamera reading from selectedDeviceIdRef at call time.

  const camStateRef = useRef<CamState>("idle");
  useEffect(() => { camStateRef.current = camState; }, [camState]);

  useEffect(() => {
    if (!selectedDeviceId) return;
    if (camStateRef.current === "active" || camStateRef.current === "flash") {
      startCamera(facingBack);
    }
    // We intentionally only react to device ID changes here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDeviceId]);

  // ── Auto-enable auto-capture the instant the camera comes on ──────────────
  // Previously, getting auto-capture running took Start Camera → Auto →
  // (often) one more manual shutter press just to get a frame right away —
  // 3-4 taps for something that should be one. If an interval was already
  // picked before "Start Camera" was pressed, that already says "I want
  // auto-capture" — so turn it on automatically rather than making that a
  // separate tap. Pure manual capture is untouched: with no interval
  // selected (intervalSec undefined), this never fires.
  const wasActiveRef = useRef(false);
  useEffect(() => {
    if (camState === "active" && !wasActiveRef.current && intervalSec) {
      setAutoMode(true);
    }
    wasActiveRef.current = camState === "active";
  }, [camState, intervalSec]);

  // ── Shutter press ──────────────────────────────────────────────────────────

  const capture = useCallback(() => {
    const video  = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || camState !== "active") return;

    setCamState("flash");

    const drawFrame = (targetCanvas: HTMLCanvasElement, sourceVideo: HTMLVideoElement) => {
      const ctx = targetCanvas.getContext("2d")!;
      if (!facingBack) {
        // Un-mirror front camera before saving
        ctx.translate(targetCanvas.width, 0);
        ctx.scale(-1, 1);
      }
      ctx.drawImage(sourceVideo, 0, 0);
    };

    if (autoMode) {
      // Auto-capture has no human in the loop to notice and retake a
      // blurry shot — the timer can fire mid-motion (a notebook being
      // repositioned, a hand still moving). Burst a few frames a beat
      // apart and keep the sharpest instead of blindly grabbing whatever
      // happens to be on screen at that instant.
      captureSharpestFrame(video, drawFrame)
        .then((bestCanvas) => {
          bestCanvas.toBlob((blob) => {
            if (!blob) { setCamState("active"); return; }
            onCapture(blob);
            setCaptureCount((n) => n + 1);
            setCamState("active");
          }, "image/jpeg", JPEG_QUALITY);
        })
        .catch(() => {
          // Without this, any failure here (a transient canvas/video read
          // error mid-burst) leaves camState stuck at "flash" forever —
          // the auto-capture timer effect requires camState === "active"
          // to run at all, so one bad tick silently killed every future
          // auto-capture for the rest of the session with no visible
          // error (reported 2026-09-17: "auto capture every 10s/20s not
          // working" — shorter intervals hit this sooner simply by
          // attempting more captures per minute). Recover by skipping
          // this tick, same as a failed toBlob() already did above.
          setCamState("active");
        });
      return;
    }

    canvas.width  = video.videoWidth  || 1280;
    canvas.height = video.videoHeight || 960;
    setCanvasDims({ w: canvas.width, h: canvas.height });
    drawFrame(canvas, video);

    canvas.toBlob((blob) => {
      if (!blob) { setCamState("active"); return; }
      // Manual capture: show preview for confirmation
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
      setPreview(blob);
      setCamState("captured");
    }, "image/jpeg", JPEG_QUALITY);
  }, [camState, facingBack, autoMode, onCapture, setPreview]);

  // Voice-triggered capture ("take a photo of the board") — the
  // ClassroomBrain assistant is mounted globally and has no direct access
  // to this component's state, so it dispatches a plain DOM event instead.
  // This fires the exact same `capture()` a physical shutter press would —
  // same preview/confirm behaviour in manual mode, same direct-fire in auto
  // mode — so voice capture never bypasses the existing confirm-before-
  // upload safeguard.
  useEffect(() => {
    const handler = () => capture();
    window.addEventListener("classroom-brain:capture_frame", handler);
    return () => window.removeEventListener("classroom-brain:capture_frame", handler);
  }, [capture]);

  // Same bridge, for turning the camera itself on/off — capture_frame above
  // assumes the camera is already active; these two are what get it there.
  useEffect(() => {
    const startHandler = () => { if (camStateRef.current === "idle" || camStateRef.current === "error") startCamera(facingBack); };
    const stopHandler = () => stopStream();
    window.addEventListener("classroom-brain:start_camera", startHandler);
    window.addEventListener("classroom-brain:stop_camera", stopHandler);
    return () => {
      window.removeEventListener("classroom-brain:start_camera", startHandler);
      window.removeEventListener("classroom-brain:stop_camera", stopHandler);
    };
  }, [startCamera, stopStream, facingBack]);

  // autoStart is this component's own mount-time equivalent of the listener
  // above — called directly (not via the DOM-event bridge) since there's no
  // cross-component race to avoid when it's already the component starting
  // itself. Guarded so it only ever fires once, even if camState later
  // returns to "idle" after the person manually stops the camera.
  const autoStartFiredRef = useRef(false);
  useEffect(() => {
    if (!autoStart || autoStartFiredRef.current || camState !== "idle") return;
    autoStartFiredRef.current = true;
    startCamera(facingBack);
  }, [autoStart, camState, startCamera, facingBack]);

  // Broadcasts to ClassroomBrain (mounted globally, possibly waiting on a
  // voice-triggered "take a photo" that navigated here — see its
  // "classroom-brain:camera_ready" listener) that the camera is actually
  // live. getUserMedia is async, so the moment autoStart/startCamera is
  // *called* isn't enough — the shutter needs camState === "active" or
  // capture() just no-ops. Fired on every transition to "active", not only
  // voice-triggered ones; harmless since the listener only acts on it when
  // it has a pending capture queued.
  useEffect(() => {
    if (camState === "active") {
      window.dispatchEvent(new CustomEvent("classroom-brain:camera_ready"));
    }
  }, [camState]);

  // ── Preview: confirm ───────────────────────────────────────────────────────

  const confirmCapture = useCallback(() => {
    if (!capturedBlob) return;
    onCapture(capturedBlob);
    setCaptureCount((n) => n + 1);
    setPreview(null);       // also revokes URL
    setCamState("active");
    setIsFullscreen(false); // return to normal view after confirming photo
  }, [capturedBlob, onCapture, setPreview]);

  // ── Preview: retake ────────────────────────────────────────────────────────

  const retake = useCallback(() => {
    setPreview(null);       // also revokes URL
    setCamState("active");
  }, [setPreview]);

  // ── Fire the first auto-capture shot immediately ───────────────────────────
  // Without this, turning auto-capture on (whether by tapping Auto, or via
  // the auto-enable above) sits silently for the whole first interval
  // before anything happens — which is exactly what made teachers add an
  // extra manual shutter press "just to get something". Keyed on the
  // autoMode false→true edge (not the timer effect below, which re-runs on
  // every capture's camState churn) so this only fires once per genuine
  // auto-capture start, never on every tick.
  const autoModeWasOnRef = useRef(false);
  useEffect(() => {
    if (autoMode && !autoModeWasOnRef.current) {
      capture();
    }
    autoModeWasOnRef.current = autoMode;
  }, [autoMode, capture]);

  // ── Auto-capture interval timer ────────────────────────────────────────────

  useEffect(() => {
    if (!autoMode || !intervalSec || camState !== "active") {
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
      return;
    }

    let remaining = intervalSec;
    // Prime the displayed value for the instant before the first tick below
    // fires; every subsequent update comes from the interval callback.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCountdown(remaining);

    timerRef.current = setInterval(() => {
      remaining -= 1;
      setCountdown(remaining);
      if (remaining <= 0) {
        capture();
        remaining = intervalSec;
        setCountdown(intervalSec);
      }
    }, 1000);

    return () => {
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
      setCountdown(null);
    };
  }, [autoMode, intervalSec, camState, capture]);

  // ── Session duration countdown (stop-after-N-minutes) ──────────────────────

  useEffect(() => {
    // Only runs when auto-mode is active and a limit is configured
    if (!autoMode || !stopAfterMinutes || stopAfterMinutes <= 0 || camState !== "active") {
      if (sessionTimerRef.current) { clearInterval(sessionTimerRef.current); sessionTimerRef.current = null; }
      return;
    }

    let secsLeft = stopAfterMinutes * 60;
    // Prime the displayed value for the instant before the first tick below
    // fires; every subsequent update comes from the interval callback.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSessionSecsLeft(secsLeft);

    sessionTimerRef.current = setInterval(() => {
      secsLeft -= 1;
      setSessionSecsLeft(secsLeft);
      if (secsLeft <= 0) {
        // Time's up — stop auto-capture
        if (sessionTimerRef.current) { clearInterval(sessionTimerRef.current); sessionTimerRef.current = null; }
        setAutoMode(false);
        setSessionSecsLeft(null);
        onAutoCaptureStopped?.();
      }
    }, 1000);

    return () => {
      if (sessionTimerRef.current) { clearInterval(sessionTimerRef.current); sessionTimerRef.current = null; }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoMode, stopAfterMinutes, camState]);

  // ── Cleanup on unmount ─────────────────────────────────────────────────────

  useEffect(() => {
    return () => {
      stopStream();
      revokePrevPreview();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Clear the session countdown once auto-mode turns off ───────────────────
  // The interval effect above only clears its own timer when auto-mode (or
  // camera state) stops — it deliberately leaves `sessionSecsLeft` alone on a
  // transient camState blip (e.g. the "flash" frame during a capture) so the
  // displayed countdown doesn't flicker mid-session. The actual "hide the
  // countdown" reset only belongs on the real autoMode on→off edge, detected
  // here by comparing against the last-seen autoMode stored in state — the
  // pattern React recommends for adjusting state during render instead of
  // from inside an effect body.
  // See https://react.dev/reference/react/useState#storing-information-from-previous-renders
  if (autoMode !== prevAutoModeForSession) {
    setPrevAutoModeForSession(autoMode);
    if (!autoMode) setSessionSecsLeft(null);
  }

  // ── Unsupported browser (client-only check — avoids SSR hydration mismatch) ─

  if (camSupported === null) return null; // still mounting — render nothing so server HTML matches

  // ── Native-input fallback (HTTP without the Chrome insecure-origins flag) ──
  // <input capture="environment"> opens the rear camera via the native camera
  // app — no HTTPS / getUserMedia needed.  Works on all Android & iOS browsers.
  if (!camSupported) return (
    <div className="flex flex-col items-center gap-4 rounded-2xl border border-slate-200 bg-slate-50 p-8 text-center">
      <Camera className="h-10 w-10 text-indigo-400" />
      <div>
        <p className="text-sm font-semibold text-slate-700">Take a Photo</p>
        <p className="mt-1 text-xs text-slate-400">
          Opens your device camera app
        </p>
      </div>

      {/* Native file-input — visually hidden, triggered by the button below */}
      <input
        id="native-camera-input"
        type="file"
        accept="image/*"
        capture="environment"
        className="sr-only"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          // Reset so the same file can be re-selected after retake
          e.target.value = "";
          if (autoMode) {
            // In auto mode skip preview and fire immediately
            onCapture(file);
          } else {
            // Show preview via the same flow as the viewfinder capture
            setPreview(file);
            setCamState("captured");
          }
        }}
      />
      <label
        htmlFor="native-camera-input"
        className="inline-flex cursor-pointer items-center gap-2 rounded-xl bg-indigo-600 px-6 py-3 text-sm font-semibold text-white shadow-md active:scale-95"
      >
        <Camera className="h-4 w-4" />
        Open Camera
      </label>

      {/* Show preview + confirm/retake when a photo was taken */}
      {previewUrl && (
        <div className="mt-2 flex w-full flex-col items-center gap-3">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={previewUrl} alt="Preview" className="w-full max-w-xs rounded-xl object-cover shadow" />
          <div className="flex gap-3">
            <button
              onClick={() => { setPreview(null); setCamState("idle"); }}
              className="flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm active:scale-95"
            >
              <RotateCcw className="h-4 w-4" /> Retake
            </button>
            <button
              onClick={() => { if (capturedBlob) { onCapture(capturedBlob); setPreview(null); setCamState("idle"); } }}
              className="flex items-center gap-1 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow active:scale-95"
            >
              <Check className="h-4 w-4" /> Use Photo
            </button>
          </div>
        </div>
      )}

      {/* Dev hint */}
      {process.env.NODE_ENV === "development" && (
        <p className="rounded bg-yellow-50 px-2 py-1 font-mono text-[0.625rem] text-yellow-700">
          {`protocol=${location.protocol} — set chrome://flags/#unsafely-treat-insecure-origin-as-secure → ${location.origin} for live viewfinder`}
        </p>
      )}
    </div>
  );

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className={cn(
      isFullscreen
        ? "fixed inset-0 z-50 flex flex-col gap-2 bg-black p-3 overflow-auto"
        : "flex flex-col gap-3",
      !isFullscreen && className,
    )}>

      {/* ────────────────────────── Viewfinder ───────────────────────────── */}
      <div
        className={cn(
          "relative w-full overflow-hidden bg-black",
          isFullscreen ? "flex-1 rounded-xl" : "rounded-2xl",
        )}
        style={isFullscreen ? undefined : { aspectRatio: "4/3" }}
      >

        {/* Live video feed */}
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className={cn(
            "h-full w-full object-cover transition-[filter,opacity] duration-150",
            !facingBack && "scale-x-[-1]",
            // Dim the live feed while showing the preview overlay
            camState === "captured" && "opacity-10 blur-sm",
          )}
        />

        {/* Off-screen capture canvas */}
        <canvas ref={canvasRef} className="hidden" />

        {/* ── Preview overlay (captured state) ── */}
        {camState === "captured" && previewUrl && (
          <div className="absolute inset-0 flex flex-col">
            {/* Photo */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={previewUrl}
              alt="Captured photo preview"
              className="h-full w-full object-contain"
            />

            {/* Resolution chip + fullscreen exit */}
            <div className="absolute left-3 right-3 top-3 flex items-center justify-between">
              {canvasDims && (
                <div className="rounded-full bg-black/50 px-2.5 py-0.5 text-[0.625rem] font-medium text-white">
                  {canvasDims.w}×{canvasDims.h}
                </div>
              )}
              {isFullscreen && (
                <button
                  onClick={() => setIsFullscreen(false)}
                  aria-label="Exit fullscreen"
                  className="flex h-8 w-8 touch-manipulation items-center justify-center rounded-full bg-black/50 text-white backdrop-blur-sm active:scale-90 hover:bg-black/70"
                >
                  <Minimize2 className="h-4 w-4" />
                </button>
              )}
            </div>

            {/* Retake / Use Photo bar */}
            <div className="absolute inset-x-0 bottom-0 flex items-center justify-between gap-3 bg-gradient-to-t from-black/80 via-black/40 to-transparent px-5 pb-6 pt-14">
              <button
                onClick={retake}
                className="flex touch-manipulation items-center gap-2 rounded-xl bg-white/20 px-5 py-3.5 text-sm font-semibold text-white backdrop-blur-sm transition-all active:scale-95 hover:bg-white/30"
              >
                <RotateCcw className="h-4 w-4" />
                Retake
              </button>

              <button
                onClick={confirmCapture}
                className="flex touch-manipulation items-center gap-2 rounded-xl bg-indigo-600 px-6 py-3.5 text-sm font-semibold text-white shadow-lg transition-all active:scale-95 hover:bg-indigo-700"
              >
                <Check className="h-4 w-4" />
                Use Photo
              </button>
            </div>
          </div>
        )}

        {/* ── Flash overlay ── */}
        {camState === "flash" && (
          <div className="pointer-events-none absolute inset-0 bg-white/70 transition-opacity duration-150" />
        )}

        {/* ── Idle / requesting / error overlay ── */}
        {(camState === "idle" || camState === "requesting" || camState === "error") && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-slate-900/95 px-6 text-center text-white">

            {camState === "requesting" && (
              <>
                <Loader2 className="h-10 w-10 animate-spin text-white/60" />
                <p className="text-sm text-slate-400">Starting camera…</p>
              </>
            )}

            {camState === "idle" && (
              <>
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-white/10">
                  <Camera className="h-8 w-8 text-white/60" />
                </div>
                <p className="text-sm text-slate-400">Camera not started</p>
              </>
            )}

            {camState === "error" && errorCode === "permission_denied" && (
              <div className="flex max-w-xs flex-col gap-4">
                <CameraOff className="mx-auto h-8 w-8 text-red-400" />
                <p className="text-sm font-semibold text-red-300">Camera access blocked</p>
                <ol className="list-none space-y-2 text-left text-xs text-slate-300">
                  <li className="flex gap-2">
                    <span className="shrink-0 font-bold text-indigo-400">1.</span>
                    Tap the lock / ⓘ icon in Chrome&apos;s address bar
                  </li>
                  <li className="flex gap-2">
                    <span className="shrink-0 font-bold text-indigo-400">2.</span>
                    Tap <strong className="text-white">Permissions → Camera</strong>
                  </li>
                  <li className="flex gap-2">
                    <span className="shrink-0 font-bold text-indigo-400">3.</span>
                    Set to <strong className="text-white">Allow</strong>, then reload
                  </li>
                </ol>
                <div className="flex flex-col gap-2">
                  <button
                    onClick={() => window.location.reload()}
                    className="touch-manipulation rounded-xl bg-indigo-600 px-4 py-2.5 text-xs font-semibold hover:bg-indigo-700"
                  >
                    Reload page
                  </button>
                  <p className="text-[0.625rem] text-slate-500">
                    On Android: Settings → Apps → Chrome → Permissions → Camera → Allow
                  </p>
                </div>
              </div>
            )}

            {camState === "error" && errorCode === "no_camera" && (
              <>
                <CameraOff className="h-8 w-8 text-slate-400" />
                <p className="text-sm text-slate-300">No camera found on this device.</p>
                <p className="text-xs text-slate-500">Use the File Upload tab instead.</p>
              </>
            )}

            {camState === "error" && errorCode !== "permission_denied" && errorCode !== "no_camera" && (
              <>
                <AlertCircle className="h-8 w-8 text-red-400" />
                <p className="text-sm text-red-300">{errorDetail || "Camera unavailable."}</p>
                <button
                  onClick={() => startCamera(facingBack)}
                  className="touch-manipulation rounded-xl bg-white/10 px-4 py-2.5 text-xs font-medium hover:bg-white/20"
                >
                  Try again
                </button>
              </>
            )}
          </div>
        )}

        {/* ── Top status bar (active state only) ── */}
        {camState === "active" && (
          <div className="absolute inset-x-0 top-0 flex items-start justify-between px-3 pt-3">
            {/* Online / offline pill */}
            <span className={cn(
              "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[0.6875rem] font-medium backdrop-blur-sm",
              isOnline
                ? "bg-black/40 text-white/90"
                : "bg-amber-500 text-white shadow-sm",
            )}>
              {isOnline
                ? <Wifi    className="h-3 w-3" />
                : <WifiOff className="h-3 w-3" />
              }
              {isOnline ? "Online" : "Offline — saved locally"}
            </span>

            <div className="flex items-center gap-2">
              {/* Capture count */}
              {captureCount > 0 && (
                <span className="rounded-full bg-black/50 px-2.5 py-1 text-[0.6875rem] font-semibold text-white backdrop-blur-sm">
                  {captureCount} captured
                </span>
              )}
              {/* Fullscreen toggle */}
              <button
                onClick={() => setIsFullscreen((v) => !v)}
                aria-label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
                className="flex h-8 w-8 touch-manipulation items-center justify-center rounded-full bg-black/50 text-white backdrop-blur-sm transition-transform active:scale-90 hover:bg-black/70"
              >
                {isFullscreen
                  ? <Minimize2 className="h-4 w-4" />
                  : <Maximize2 className="h-4 w-4" />
                }
              </button>
            </div>
          </div>
        )}

        {/* ── Auto-capture countdown ring ── */}
        {autoMode && intervalSec && countdown !== null && camState === "active" && (
          <div className="absolute right-3 top-3 flex h-12 w-12 items-center justify-center rounded-full bg-black/50 backdrop-blur-sm">
            <svg className="absolute inset-0 -rotate-90" width="48" height="48" aria-hidden>
              <circle cx="24" cy="24" r="20"
                fill="none" stroke="rgba(255,255,255,0.2)" strokeWidth="3" />
              <circle cx="24" cy="24" r="20"
                fill="none" stroke="white" strokeWidth="3"
                strokeLinecap="round"
                strokeDasharray={String(2 * Math.PI * 20)}
                strokeDashoffset={String(2 * Math.PI * 20 * (1 - countdown / intervalSec))}
                style={{ transition: "stroke-dashoffset 1s linear" }}
              />
            </svg>
            <span className="relative z-10 text-xs font-bold text-white">{countdown}</span>
          </div>
        )}

        {/* ── Camera flip (bottom-right, active state only) ── */}
        {camState === "active" && (
          <button
            onClick={() => {
              const next = !facingBack;
              setFacingBack(next);
              startCamera(next);
            }}
            aria-label="Flip camera"
            className="absolute bottom-4 right-4 flex h-11 w-11 touch-manipulation items-center justify-center rounded-full bg-black/50 text-white backdrop-blur-sm transition-transform active:scale-90 hover:bg-black/70"
          >
            <RefreshCcw className="h-5 w-5" />
          </button>
        )}
      </div>

      {/* ──────────────────── Camera device picker ───────────────────────── */}
      {videoDevices.length >= 1 && camState !== "captured" && (
        <div className="flex items-center gap-2">
          {/* Device dropdown */}
          <select
            value={selectedDeviceId}
            onChange={(e) => setSelectedDeviceId(e.target.value)}
            className="min-w-0 flex-1 truncate rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
          >
            {videoDevices.map((d, i) => {
              const { tag, icon } = deviceTag(d.label);
              const label = d.label || `Camera ${i + 1}`;
              const prefix = icon === "usb" ? "🔌 " : icon === "builtin" ? "💻 " : "📷 ";
              return (
                <option key={d.deviceId} value={d.deviceId}>
                  {prefix}{label}
                  {tag !== "Camera" ? ` [${tag}]` : ""}
                </option>
              );
            })}
          </select>

          {/* Re-scan button — useful when a USB webcam is plugged in after page load */}
          <button
            onClick={async () => {
              setScanningDevices(true);
              await enumerateCameras(false);
              setScanningDevices(false);
            }}
            disabled={scanningDevices}
            title="Scan for newly connected cameras"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 shadow-sm transition-colors hover:border-indigo-300 hover:text-indigo-600 disabled:opacity-40"
          >
            {scanningDevices
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
              : <ScanLine className="h-3.5 w-3.5" />
            }
          </button>

          {/* USB indicator badge (shown when a USB/external cam is selected) */}
          {(() => {
            const active = videoDevices.find(d => d.deviceId === selectedDeviceId);
            const { icon } = active ? deviceTag(active.label) : { icon: "unknown" };
            return icon === "usb" ? (
              <span className="flex shrink-0 items-center gap-1 rounded-full bg-indigo-50 px-2 py-1 text-[0.625rem] font-medium text-indigo-700">
                <Usb className="h-3 w-3" /> USB
              </span>
            ) : null;
          })()}
        </div>
      )}

      {/* ──────────────────── Controls (below viewfinder) ─────────────────── */}
      {camState !== "captured" && (
        <div className="flex items-center gap-3">

          {/* Start / requesting state */}
          {(camState === "idle" || camState === "error" || camState === "requesting") && (
            <button
              onClick={() => startCamera(facingBack)}
              disabled={disabled || camState === "requesting"}
              className="flex w-full touch-manipulation items-center justify-center gap-2 rounded-xl bg-indigo-600 py-4 text-sm font-semibold text-white transition-all active:scale-95 hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {camState === "requesting"
                ? <><Loader2 className="h-4 w-4 animate-spin" /> Starting…</>
                : <><Camera  className="h-4 w-4" /> Start Camera</>
              }
            </button>
          )}

          {/* Active controls */}
          {(camState === "active" || camState === "flash") && (
            <>
              {/* Auto-capture toggle (left) */}
              {intervalSec ? (
                <button
                  onClick={() => setAutoMode((v) => !v)}
                  aria-label={autoMode ? "Stop auto capture" : "Start auto capture"}
                  className={cn(
                    "flex h-16 w-16 shrink-0 touch-manipulation flex-col items-center justify-center gap-0.5 rounded-xl text-[0.625rem] font-medium transition-colors",
                    autoMode
                      ? "bg-indigo-600 text-white"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200",
                  )}
                >
                  {autoMode
                    ? <><TimerOff className="h-4 w-4" />Stop</>
                    : <><Timer    className="h-4 w-4" />Auto</>
                  }
                </button>
              ) : (
                <div className="w-16 shrink-0" /> /* spacer to keep shutter centred */
              )}

              {/* Shutter button (centre) — large for thumb reach */}
              <button
                onClick={capture}
                disabled={camState !== "active" || disabled}
                aria-label="Capture photo"
                className={cn(
                  "relative mx-auto flex h-20 w-20 shrink-0 touch-manipulation items-center justify-center rounded-full",
                  "border-4 border-white shadow-[0_0_0_3px] shadow-indigo-500",
                  "bg-white transition-transform active:scale-90 disabled:cursor-not-allowed disabled:opacity-40",
                  camState === "flash" && "bg-indigo-100",
                )}
              >
                <span className={cn(
                  "h-14 w-14 rounded-full transition-colors",
                  camState === "flash" ? "bg-indigo-400" : "bg-red-500",
                )} />
              </button>

              {/* Stop camera (right) */}
              <button
                onClick={handleStop}
                aria-label="Stop camera"
                className="flex h-16 w-16 shrink-0 touch-manipulation flex-col items-center justify-center gap-0.5 rounded-xl bg-slate-100 text-[0.625rem] font-medium text-slate-600 transition-colors hover:bg-slate-200"
              >
                <span className="h-4 w-4 rounded-sm bg-slate-400" />
                Stop
              </button>
            </>
          )}
        </div>
      )}

      {/* ──────────────────────── Upload status bar ───────────────────────── */}
      {uploadStatus !== "idle" && camState !== "captured" && (
        <div className={cn(
          "flex items-center gap-2.5 rounded-xl px-3.5 py-2.5 text-xs font-medium transition-all",
          uploadStatus === "saving"    && "bg-indigo-50 text-indigo-700",
          uploadStatus === "uploading" && "bg-blue-50   text-blue-700",
          uploadStatus === "done"      && "bg-green-50  text-green-700",
          uploadStatus === "error"     && "bg-red-50    text-red-600",
        )}>
          {uploadStatus === "saving"    && <Loader2      className="h-3.5 w-3.5 shrink-0 animate-spin" />}
          {uploadStatus === "uploading" && <Upload       className="h-3.5 w-3.5 shrink-0 animate-pulse" />}
          {uploadStatus === "done"      && <Check        className="h-3.5 w-3.5 shrink-0" />}
          {uploadStatus === "error"     && <AlertCircle  className="h-3.5 w-3.5 shrink-0" />}

          <span className="flex-1">
            {uploadStatus === "saving"    && "Saving to device…"}
            {uploadStatus === "uploading" && "Uploading to server…"}
            {uploadStatus === "done"      && (uploadedKb ? `Uploaded · ${uploadedKb} KB` : "Uploaded")}
            {uploadStatus === "error"     && "Upload failed — queued for retry"}
          </span>

          {/* Indeterminate progress rail */}
          {(uploadStatus === "saving" || uploadStatus === "uploading") && (
            <span className="h-1 w-20 shrink-0 overflow-hidden rounded-full bg-white/60">
              <span
                className={cn(
                  "block h-full w-1/2 rounded-full animate-pulse",
                  uploadStatus === "saving"    ? "bg-indigo-500" : "bg-blue-500",
                )}
              />
            </span>
          )}
        </div>
      )}

      {/* ───────────────────────────── Hint text ──────────────────────────── */}
      {camState === "active" && !autoMode && uploadStatus === "idle" && (
        <p className="text-center text-xs text-slate-400">
          Aim at the board and press the shutter
        </p>
      )}
      {camState === "active" && autoMode && (
        <div className="flex flex-col items-center gap-1">
          <p className="text-center text-xs font-medium text-indigo-600">
            Auto-capturing every {intervalSec}s — move to the next board section
          </p>
          {sessionSecsLeft !== null && (
            <p className="flex items-center gap-1 text-center text-xs text-slate-400">
              <Timer className="h-3 w-3" />
              Session stops in{" "}
              <span className={cn(
                "font-semibold tabular-nums",
                sessionSecsLeft <= 60 ? "text-orange-500" : "text-slate-500",
              )}>
                {sessionSecsLeft >= 60
                  ? `${Math.floor(sessionSecsLeft / 60)}m ${sessionSecsLeft % 60}s`
                  : `${sessionSecsLeft}s`}
              </span>
            </p>
          )}
        </div>
      )}
    </div>
  );
}
