/**
 * Sharpness ranking for unattended (auto-interval) camera captures.
 *
 * A manual shutter tap has a human in the loop who sees the preview and can
 * retake a blurry shot. Auto-capture doesn't — the timer fires regardless of
 * whether a notebook is mid-flip or the camera is mid-adjustment, and a
 * single blind snapshot at that instant has a real chance of being
 * motion-blurred and unreadable by OCR/vision (confirmed via real captures
 * on the Pi, 2026-09-15: several consecutive auto-captures came back too
 * blurry to read while a manual capture moments earlier was sharp).
 *
 * Rather than a hard "reject if too blurry" threshold — which would need
 * calibrating an absolute cutoff for this downsampled, hand-rolled measure
 * (not the same scale as the backend's cv2.Laplacian check in
 * image_preprocessor.py, and mis-calibrating it risks silently dropping a
 * whole capture interval's worth of a fast-moving classroom) — this grabs a
 * short burst of frames a few ms apart and keeps the sharpest one. That
 * sidesteps calibration entirely: it always produces a frame for the
 * interval, just a better one, and directly targets "camera/subject moved
 * right as the timer fired" rather than any particular blur severity.
 */

/**
 * Cheap 4-neighbor Laplacian variance on a downsampled copy of `source`.
 * Not meant to match any absolute "blurry" scale — only to RANK a handful
 * of near-simultaneous frames from the same camera against each other.
 */
function sharpnessScore(source: CanvasImageSource, sourceW: number, sourceH: number, maxDim = 240): number {
  const scale = Math.min(1, maxDim / Math.max(sourceW, sourceH));
  const w = Math.max(1, Math.round(sourceW * scale));
  const h = Math.max(1, Math.round(sourceH * scale));

  const off = document.createElement("canvas");
  off.width = w;
  off.height = h;
  const ctx = off.getContext("2d", { willReadFrequently: true });
  if (!ctx) return 0; // can't measure — treat as neutral, never blocks capture

  ctx.drawImage(source, 0, 0, w, h);
  const { data } = ctx.getImageData(0, 0, w, h);

  const gray = new Float32Array(w * h);
  for (let i = 0, p = 0; i < data.length; i += 4, p++) {
    gray[p] = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
  }

  let sum = 0;
  let sumSq = 0;
  let n = 0;
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const idx = y * w + x;
      const lap = 4 * gray[idx] - gray[idx - 1] - gray[idx + 1] - gray[idx - w] - gray[idx + w];
      sum += lap;
      sumSq += lap * lap;
      n++;
    }
  }
  if (n === 0) return 0;
  const mean = sum / n;
  return sumSq / n - mean * mean;
}

/**
 * Draws `burstSize` frames from `video` onto fresh canvases a few ms apart
 * (via `draw`, so the caller controls sizing/mirroring) and returns the
 * sharpest one, ready for `.toBlob()`.
 */
export async function captureSharpestFrame(
  video: HTMLVideoElement,
  draw: (canvas: HTMLCanvasElement, video: HTMLVideoElement) => void,
  burstSize = 3,
  gapMs = 90,
): Promise<HTMLCanvasElement> {
  let best: HTMLCanvasElement | null = null;
  let bestScore = -Infinity;

  for (let i = 0; i < burstSize; i++) {
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth || 1280;
    canvas.height = video.videoHeight || 960;
    draw(canvas, video);

    const score = sharpnessScore(canvas, canvas.width, canvas.height);
    if (score > bestScore) {
      bestScore = score;
      best = canvas;
    }
    if (i < burstSize - 1) await new Promise((r) => setTimeout(r, gapMs));
  }

  return best!;
}
