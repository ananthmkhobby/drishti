"""
Frame validation and board-type-specific image preprocessing.

Pipeline per frame:
  validate_frame()      → reject blurry / dark / undersized frames
  to_ocr_ready()        → board-type enhancement + optional low-light fix

Board type preprocessing paths:
  whiteboard  — coloured or black marker on white/light board
                → low-light enhance → saturation+luminance merge → CLAHE →
                  glare suppression → bilateral filter → upscale ≥ 900 px
  greenboard  — green chalk/marker board
                → low-light enhance → LAB L-channel invert → CLAHE →
                  denoise → sharpen
  blackboard  — very dark board with chalk
                → low-light enhance → grayscale invert → strong CLAHE →
                  denoise → sharpen → upscale ≥ 800 px
  chalkboard  — catch-all dark board (default for black/unknown dark boards)
                → green detection → correct path → CLAHE → denoise →
                  morphological dust removal
  smartboard  — projected digital content
                → light CLAHE only (already high-contrast)

Low-light enhancements (applied before board-specific processing):
  low_light_enhance()  — auto-gamma correction (brightens dark frames)
  denoise_frame()      — fast non-local means denoising (reduces noise grain)
  unsharp_mask()       — sharpens weak/blurry text strokes
"""

from __future__ import annotations

import cv2
import numpy as np
from dataclasses import dataclass


# ── Validation thresholds ──────────────────────────────────────────────────────

MIN_HEIGHT_PX          = 320
MIN_WIDTH_PX           = 480
MIN_LAPLACIAN_VARIANCE = 3.0    # lower = accept webcam/phone motion blur
MIN_MEAN_BRIGHTNESS    = 15.0   # below this = severely underexposed


@dataclass
class ValidationResult:
    is_valid: bool
    reason: str | None = None        # None when valid
    blur_score: float = 0.0
    brightness: float = 0.0


# ── Frame validation ───────────────────────────────────────────────────────────

def validate_frame(image: np.ndarray) -> ValidationResult:
    """
    Reject frames that are too small, too blurry, or too dark.

    Args:
        image: BGR or grayscale ndarray.
    Returns:
        ValidationResult with is_valid=True when the frame can be OCR'd.
    """
    h, w = image.shape[:2]
    if h < MIN_HEIGHT_PX or w < MIN_WIDTH_PX:
        return ValidationResult(False, "too_small", 0.0, 0.0)

    gray = _to_gray(image)

    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if blur_score < MIN_LAPLACIAN_VARIANCE:
        return ValidationResult(False, "too_blurry", blur_score, float(gray.mean()))

    brightness = float(gray.mean())
    if brightness < MIN_MEAN_BRIGHTNESS:
        return ValidationResult(False, "too_dark", blur_score, brightness)

    return ValidationResult(True, None, blur_score, brightness)


# ── Low-light enhancement primitives ─────────────────────────────────────────

def low_light_enhance(bgr: np.ndarray) -> np.ndarray:
    """
    Auto-gamma correction for dim classroom frames.

    Uses the LAB colour space L-channel so brightness is boosted without
    shifting hue (important for colour-ink detection on whiteboards).

    Gamma applied:
      mean_L < 60  → gamma 1.8  (significantly dark room)
      mean_L < 90  → gamma 1.35 (slightly underexposed)
      mean_L >= 90 → no change

    Returns BGR (same type as input).
    """
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l_ch = lab[:, :, 0].astype(np.float32)
    mean_l = float(l_ch.mean())

    if mean_l >= 90.0:
        return bgr  # bright enough, nothing to do

    gamma = 1.80 if mean_l < 60.0 else 1.35

    # Build look-up table
    inv_gamma = 1.0 / gamma
    lut = (np.arange(256, dtype=np.float32) / 255.0) ** inv_gamma * 255.0
    lut = np.clip(lut, 0, 255).astype(np.uint8)

    lab[:, :, 0] = lut[lab[:, :, 0]]
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def denoise_frame(gray: np.ndarray) -> np.ndarray:
    """
    Fast non-local means denoising for grayscale board images.

    Reduces sensor grain that appears in low-light captures and helps OCR
    engines produce cleaner segmentations.

    h=8 is moderate — strong enough to remove grain while keeping strokes.
    """
    return cv2.fastNlMeansDenoising(
        gray,
        h=8,
        templateWindowSize=7,
        searchWindowSize=21,
    )


def unsharp_mask(
    gray: np.ndarray,
    sigma: float = 1.2,
    strength: float = 1.2,
) -> np.ndarray:
    """
    Sharpen handwriting strokes using an unsharp mask.

    Result = clip(original + strength × (original − blurred), 0, 255)

    Works as a mild deblurring pass — recovers soft edges caused by:
      - slightly out-of-focus captures
      - motion blur from handheld cameras
      - upscaling artefacts
    """
    blurred = cv2.GaussianBlur(gray, (0, 0), sigmaX=sigma)
    sharpened = cv2.addWeighted(gray, 1.0 + strength, blurred, -strength, 0)
    return np.clip(sharpened, 0, 255).astype(np.uint8)


# ── Low-level building blocks ─────────────────────────────────────────────────

def apply_clahe(
    gray: np.ndarray,
    clip_limit: float = 2.0,
    tile_size: int = 8,
) -> np.ndarray:
    """Contrast Limited Adaptive Histogram Equalization."""
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile_size, tile_size))
    return clahe.apply(gray)


def remove_chalk_dust(gray: np.ndarray) -> np.ndarray:
    """
    Morphological opening to erase isolated chalk-dust specks,
    followed by a gentle Gaussian blur.
    """
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    opened = cv2.morphologyEx(gray, cv2.MORPH_OPEN, kernel, iterations=1)
    return cv2.GaussianBlur(opened, (3, 3), sigmaX=0)


def remove_glare(gray: np.ndarray, threshold: int = 240) -> np.ndarray:
    """
    Inpaint specular glare zones on whiteboards.
    Pixels brighter than `threshold` are reconstructed from surrounding context.
    """
    glare_mask = (gray > threshold).astype(np.uint8) * 255
    if glare_mask.any():
        return cv2.inpaint(gray, glare_mask, inpaintRadius=5, flags=cv2.INPAINT_TELEA)
    return gray


def _is_green_chalkboard(bgr: np.ndarray) -> bool:
    """
    Heuristic: True when the dominant background hue is in the green range.
    Samples the border region where background (not text) dominates.
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, w = bgr.shape[:2]
    margin_y, margin_x = max(h // 10, 10), max(w // 10, 10)
    border_mask = np.zeros((h, w), dtype=np.uint8)
    border_mask[:margin_y, :] = 255
    border_mask[-margin_y:, :] = 255
    border_mask[:, :margin_x] = 255
    border_mask[:, -margin_x:] = 255

    hue_channel = hsv[:, :, 0]
    border_hues = hue_channel[border_mask > 0]
    if len(border_hues) == 0:
        return False
    # Green hue in OpenCV HSV: ~35–85 (70–170° standard)
    green_fraction = float(np.sum((border_hues >= 35) & (border_hues <= 85))) / len(border_hues)
    return green_fraction > 0.28


def _upscale_if_small(gray: np.ndarray, min_short_edge: int = 900) -> np.ndarray:
    """Legacy wrapper — prefer _adaptive_upscale for new call-sites."""
    return _adaptive_upscale(gray, target_short_edge=min_short_edge)


def _adaptive_upscale(gray: np.ndarray, target_short_edge: int = 1800) -> np.ndarray:
    """
    Upscale the short edge to at least `target_short_edge` px using an
    iterative 2× strategy that preserves stroke sharpness better than a
    single large resize.

    Why iterative?
      A single 6× LANCZOS4 from a 150 px board crop produces a blurry
      result — the algorithm has too little source information.  Doubling
      with a sharpen pass between each step progressively restores stroke
      edges at every scale level, giving the OCR engine significantly
      cleaner input.

    Strategy:
      • While short edge < target AND scale factor remaining > 1.3:
          – 2× LANCZOS4 resize
          – CLAHE to recover local contrast after interpolation
          – Unsharp mask to re-crisp letter strokes
      • Final single LANCZOS4 step if target not quite reached.
    """
    cur_min = min(gray.shape[:2])
    if cur_min >= target_short_edge:
        return gray

    total_scale = target_short_edge / cur_min
    result = gray.copy()

    # Iterative 2× steps while remaining scale > 1.3
    while True:
        cur_min_now = min(result.shape[:2])
        remaining = target_short_edge / cur_min_now
        if remaining <= 1.05:
            break

        # Use 2× per step, or the exact remaining scale if < 2
        step_scale = min(2.0, remaining)
        new_w = int(result.shape[1] * step_scale)
        new_h = int(result.shape[0] * step_scale)
        result = cv2.resize(result, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

        # Re-apply contrast and sharpening at each scale level
        # (Only when we're still more than halfway to target — avoids
        #  over-processing the final step)
        if step_scale > 1.3:
            result = apply_clahe(result, clip_limit=2.0, tile_size=8)
            result = unsharp_mask(result, sigma=0.8, strength=0.7)

    return result


# ── Per-board-type preprocessing paths ───────────────────────────────────────

def _preprocess_chalkboard(bgr: np.ndarray) -> np.ndarray:
    """
    Chalkboard path (black or green background, white/yellow chalk).

    Steps:
      1. Low-light enhance    — brighten dim rooms
      2. Detect green vs black board → choose inversion source
         green:  LAB L-channel invert (better lightness separation)
         black:  standard grayscale invert
      3. CLAHE clip=3.5       — high clip; chalk has low inherent contrast
      4. Denoise              — remove chalk dust noise
      5. Unsharp mask         — sharpen stroke edges
      6. Adaptive upscale ≥ 1800 px — critical for cameras > 3 m away
    """
    bgr = low_light_enhance(bgr)
    gray = _to_gray(bgr)

    if _is_green_chalkboard(bgr):
        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
        l_channel = lab[:, :, 0]
        inverted = cv2.bitwise_not(l_channel)
    else:
        inverted = cv2.bitwise_not(gray)

    enhanced = apply_clahe(inverted, clip_limit=3.5, tile_size=8)
    denoised = denoise_frame(enhanced)
    sharpened = unsharp_mask(denoised, sigma=1.0, strength=0.8)
    return _adaptive_upscale(sharpened, target_short_edge=1800)


def _preprocess_blackboard(bgr: np.ndarray) -> np.ndarray:
    """
    Blackboard path (very dark — near-black — background with chalk).

    Similar to chalkboard but with stronger CLAHE and upscaling since
    very dark boards have extremely low contrast before enhancement.

    Steps:
      1. Low-light enhance (gamma 1.8 for very dark boards)
      2. Grayscale invert
      3. CLAHE clip=4.0       — strongest setting
      4. Denoise
      5. Unsharp mask (stronger)
      6. Adaptive upscale ≥ 1800 px
    """
    bgr = low_light_enhance(bgr)
    inverted = cv2.bitwise_not(_to_gray(bgr))
    enhanced = apply_clahe(inverted, clip_limit=4.0, tile_size=8)
    denoised = denoise_frame(enhanced)
    sharpened = unsharp_mask(denoised, sigma=1.0, strength=1.0)
    return _adaptive_upscale(sharpened, target_short_edge=1800)


def _preprocess_greenboard(bgr: np.ndarray) -> np.ndarray:
    """
    Greenboard path (green-painted surface with white/yellow chalk).

    Uses LAB L-channel for better separation of white chalk from the
    green background than standard grayscale.

    Steps:
      1. Low-light enhance
      2. LAB L-channel invert
      3. CLAHE clip=3.0
      4. Denoise
      5. Unsharp mask
      6. Adaptive upscale ≥ 1800 px — critical for cameras > 3 m away
    """
    bgr = low_light_enhance(bgr)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    inverted = cv2.bitwise_not(lab[:, :, 0])
    enhanced = apply_clahe(inverted, clip_limit=3.0, tile_size=8)
    denoised = denoise_frame(enhanced)
    sharpened = unsharp_mask(denoised, sigma=1.0, strength=0.8)
    return _adaptive_upscale(sharpened, target_short_edge=1800)


def _preprocess_whiteboard(bgr: np.ndarray) -> np.ndarray:
    """
    Whiteboard path — handles ANY ink colour on a white/light board.

    Why standard grayscale fails for coloured markers:
      Luminance formula: 0.587·G + 0.299·R + 0.114·B
      • Green ink  (BGR 0,200,0)  → ~117/255  (medium grey, poor contrast)
      • Blue marker(BGR 200,0,0)  → ~23/255   (dark, fine)
      • Black marker → ~0/255     (perfect)
      At 3 m green ink (~46% contrast) is frequently missed by OCR.

    Better approach — dual channel merge:
      a) HSV Saturation (inverted): coloured ink HIGH sat → inverted = dark.
         Catches green, blue, red, purple.
      b) Standard grayscale: catches black/dark ink.
      Taking the MINIMUM means whichever channel detects darker "wins".

    Pipeline:
      1. Low-light enhance    — dim classroom correction
      2. Saturation ink detect (coloured markers)
      3. Grayscale ink detect  (dark markers)
      4. Merge: minimum(sat_inv, gray)
      5. CLAHE clip=3.0
      6. Glare suppression (whiteboard specular reflections)
      7. Bilateral filter     (smooths noise, keeps edges)
      8. Upscale to ≥ 900 px  (critical for text at 3 m)
      9. Denoise + Sharpen
    """
    # ── 1. Low-light correction ───────────────────────────────────────────────
    bgr = low_light_enhance(bgr)

    # ── 2. Saturation channel (coloured ink detector) ─────────────────────────
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]           # 0=white/grey, 255=vivid colour
    ink_from_sat = cv2.bitwise_not(sat)  # coloured ink → dark, white board → bright

    # ── 3. Grayscale (dark-ink detector) ─────────────────────────────────────
    gray = _to_gray(bgr)         # black marker → dark, white background → bright

    # ── 4. Red-ink explicit channel (handles partially-dried / low-saturation red)
    # Red dominance: R channel significantly exceeds both G and B.
    # This catches dry-erase red markers that may have moderate saturation (~100–180)
    # but still have clear R >> G/B channel dominance.
    b_ch = bgr[:, :, 0].astype(np.float32)
    g_ch = bgr[:, :, 1].astype(np.float32)
    r_ch = bgr[:, :, 2].astype(np.float32)
    red_dom = np.clip(r_ch - np.maximum(g_ch, b_ch), 0, 255).astype(np.uint8)
    red_ink_dark = cv2.bitwise_not(red_dom)  # red ink → dark, non-red areas → bright

    # ── 5. Merge: minimum across all detectors → all ink dark, background bright
    combined = np.minimum(np.minimum(ink_from_sat, gray), red_ink_dark)

    # ── 5. Contrast + noise ───────────────────────────────────────────────────
    enhanced = apply_clahe(combined, clip_limit=3.0, tile_size=8)

    # ── 6. Glare suppression ──────────────────────────────────────────────────
    deglared = remove_glare(enhanced, threshold=240)

    # ── 7. Bilateral filter (smooth noise, preserve ink edges) ───────────────
    smoothed = cv2.bilateralFilter(deglared, d=9, sigmaColor=75, sigmaSpace=75)

    # ── 8. Adaptive upscale for distant text (≥ 1800 px short edge) ────────
    upscaled = _adaptive_upscale(smoothed, target_short_edge=1800)

    # ── 9. Final denoise + sharpen ────────────────────────────────────────────
    denoised = denoise_frame(upscaled)
    return unsharp_mask(denoised, sigma=1.0, strength=0.9)


def _preprocess_smartboard(bgr: np.ndarray) -> np.ndarray:
    """
    Smartboard / projected-display path (high-contrast digital content).
    Light CLAHE only — avoid aggressive transforms that introduce artefacts.
    """
    gray = _to_gray(bgr)
    return apply_clahe(gray, clip_limit=1.5, tile_size=8)


# ── Public interface ──────────────────────────────────────────────────────────

def preprocess_for_board(bgr: np.ndarray, board_type: str) -> np.ndarray:
    """
    Dispatch to the correct preprocessing path based on board_type.

    Supports the full set of auto-detected + session-specified types:
      "whiteboard"  — marker board
      "greenboard"  — green chalk board
      "blackboard"  — very dark chalk board
      "chalkboard"  — generic dark board (handles black and green variants)
      "smartboard"  — projected digital display
      "notebook"    — pen/pencil on paper (same light-background polarity as
                       a whiteboard, so reuses that path rather than a
                       dedicated one)

    Args:
        bgr:        BGR image (after board detection + perspective correction).
        board_type: Detected or session-specified type (case-insensitive).

    Returns:
        Enhanced grayscale image ready for OCR.
    """
    bt = (board_type or "chalkboard").lower().strip()

    if bt == "whiteboard" or bt == "notebook":
        return _preprocess_whiteboard(bgr)
    if bt == "greenboard":
        return _preprocess_greenboard(bgr)
    if bt == "blackboard":
        return _preprocess_blackboard(bgr)
    if bt == "smartboard":
        return _preprocess_smartboard(bgr)

    # Default: chalkboard (handles black and green variants via _is_green_chalkboard)
    return _preprocess_chalkboard(bgr)


def to_ocr_ready(bgr: np.ndarray, board_type: str) -> tuple[np.ndarray, np.ndarray]:
    """
    Full preprocessing pipeline: BGR input → (raw_gray, ocr_ready_gray).

    Returns:
        raw_gray   — plain grayscale (for debugging / save)
        ocr_ready  — enhanced grayscale optimised for OCR
    """
    raw_gray  = _to_gray(bgr)
    ocr_ready = preprocess_for_board(bgr, board_type)
    return raw_gray, ocr_ready


# ── Internal helpers ──────────────────────────────────────────────────────────

def _to_gray(image: np.ndarray) -> np.ndarray:
    if len(image.shape) == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
