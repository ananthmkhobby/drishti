#!/usr/bin/env python3
"""
ACI OCR Test Harness
====================

Runs the full OCR pipeline against six test categories, prints per-image
diagnostics, and saves a multi-stage debug image for each.

Usage
-----
  # Run all six synthetic categories (no extra files needed)
  python scripts/test_ocr_local.py

  # Run specific categories
  python scripts/test_ocr_local.py --categories blackboard greenboard

  # Test a real image
  python scripts/test_ocr_local.py --image ../sample_images/whiteboard/photo.jpg \
      --board-type whiteboard

  # Save debug output to a custom directory
  python scripts/test_ocr_local.py --save-debug ./my_debug

  # Skip image generation, use only real images from sample_images/
  python scripts/test_ocr_local.py --no-synthetic

  # Quiet mode: only show the summary table
  python scripts/test_ocr_local.py --quiet

  # Disable colour (for CI / log files)
  python scripts/test_ocr_local.py --no-color

Run from backend/:
  cd /path/to/ACI/backend
  .venv/bin/python scripts/test_ocr_local.py

Categories
----------
  blackboard        Black chalkboard, white/yellow chalk
  greenboard        Green chalkboard, pale-yellow chalk (triggers LAB path)
  whiteboard        Light board, dark marker (glare suppression path)
  messy_handwriting Irregular font sizes, noisy background
  tilted_board      ~30° perspective tilt (tests warpPerspective correction)
  low_light         Underexposed — EXPECTED validation rejection
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

# ── Path setup ────────────────────────────────────────────────────────────────
# Works whether called from backend/ or from the repo root.
_HERE = Path(__file__).resolve().parent          # backend/scripts/
_BACKEND = _HERE.parent                           # backend/
_REPO = _BACKEND.parent                           # ACI/
_SAMPLE_IMAGES = _REPO / "sample_images"

if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# ── ANSI colours ──────────────────────────────────────────────────────────────

_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_DIM    = "\033[2m"
_RED    = "\033[31m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_BLUE   = "\033[34m"
_CYAN   = "\033[36m"
_WHITE  = "\033[37m"

_USE_COLOR = True   # overridden by --no-color


def _c(*args: str) -> str:
    """Concatenate ANSI codes + text + reset, or return bare text when colour off."""
    if not _USE_COLOR:
        return args[-1]
    codes = args[:-1]
    text  = args[-1]
    return "".join(codes) + text + _RESET


def _conf_colour(conf: float) -> str:
    if conf >= 0.75:
        return _GREEN
    if conf >= 0.50:
        return _YELLOW
    return _RED


# ── Category definitions ──────────────────────────────────────────────────────

@dataclass
class CategorySpec:
    name: str
    board_type: str           # chalkboard | whiteboard | smartboard
    expected_valid: bool      # False → pipeline should reject the frame
    description: str
    hint: str                 # one-line tip for real-image captures


CATEGORIES: dict[str, CategorySpec] = {
    "blackboard": CategorySpec(
        name="blackboard",
        board_type="chalkboard",
        expected_valid=True,
        description="Black chalkboard with white/yellow chalk text",
        hint="Dark bg (near-black), white chalk. Physics or maths content ideal.",
    ),
    "greenboard": CategorySpec(
        name="greenboard",
        board_type="chalkboard",
        expected_valid=True,
        description="Green chalkboard — triggers LAB L-channel inversion path",
        hint="HSV hue 35–85° must cover > 30% of the border strip.",
    ),
    "whiteboard": CategorySpec(
        name="whiteboard",
        board_type="whiteboard",
        expected_valid=True,
        description="White/light board with dark marker, glare suppression active",
        hint="Capture at slight angle to expose specular glare hotspot.",
    ),
    "messy_handwriting": CategorySpec(
        name="messy_handwriting",
        board_type="chalkboard",
        expected_valid=True,
        description="Irregular font sizes and noisy background",
        hint="Mix print and cursive. Expect confidence 0.45–0.70.",
    ),
    "tilted_board": CategorySpec(
        name="tilted_board",
        board_type="chalkboard",
        expected_valid=True,
        description="~30° off-axis perspective — tests warpPerspective correction",
        hint="Full board rectangle must be visible; cover > 30% of frame.",
    ),
    "low_light": CategorySpec(
        name="low_light",
        board_type="chalkboard",
        expected_valid=False,   # ← should be rejected by validate_frame()
        description="Underexposed frame — expected pipeline rejection",
        hint="Mean brightness < 30. This category should always be REJECTED.",
    ),
}

ALL_CATEGORY_NAMES = list(CATEGORIES.keys())


# ── Test result ───────────────────────────────────────────────────────────────

@dataclass
class StageTimings:
    validation_ms:   int = 0
    detection_ms:    int = 0
    preprocess_ms:   int = 0
    ocr_ms:          int = 0

    @property
    def total_ms(self) -> int:
        return self.validation_ms + self.detection_ms + self.preprocess_ms + self.ocr_ms


@dataclass
class TestResult:
    category:        str
    image_path:      Path
    board_type:      str
    synthetic:       bool           # True when image was auto-generated

    # Validation
    is_valid:        bool
    reject_reason:   str | None
    blur_score:      float
    brightness:      float
    image_size:      tuple[int, int]  # (w, h)

    # Board detection
    board_found:     bool
    board_bbox:      tuple[int, int, int, int] | None
    warped_size:     tuple[int, int] | None

    # OCR
    engine_used:     str
    confidence:      float
    needs_review:    bool
    region_count:    int
    raw_text:        str
    ocr_error:       str | None
    regions:         list[Any] = field(default_factory=list)

    # Timing
    timings:         StageTimings = field(default_factory=StageTimings)

    # Expected behaviour
    expected_valid:  bool = True

    @property
    def passed(self) -> bool:
        """True when the outcome matches the expected behaviour."""
        if not self.expected_valid:
            # Expected rejection — pass only if actually rejected
            return not self.is_valid
        # Expected valid — pass if valid AND no hard OCR error (engine missing is OK)
        if not self.is_valid:
            return False
        if self.ocr_error and "No OCR engine" not in self.ocr_error:
            return False
        return True

    @property
    def outcome_label(self) -> str:
        if not self.expected_valid and not self.is_valid:
            return "EXPECTED REJECTION"
        if not self.is_valid:
            return f"REJECTED ({self.reject_reason})"
        if self.ocr_error:
            if "No OCR engine" in self.ocr_error:
                return "NO ENGINE"
            return f"OCR ERROR"
        return "OK"


# ── Synthetic image generators ────────────────────────────────────────────────

def _board_canvas(
    h: int = 520,
    w: int = 720,
    bg_bgr: tuple[int, int, int] = (20, 20, 20),
    border_bgr: tuple[int, int, int] | None = (55, 55, 55),
    border_px: int = 12,
) -> np.ndarray:
    """Create a blank board-style canvas with an optional subtle border."""
    img = np.full((h, w, 3), bg_bgr, dtype=np.uint8)
    if border_bgr:
        cv2.rectangle(img, (border_px, border_px),
                      (w - border_px, h - border_px), border_bgr, 2)
    return img


def _put_lines(
    img: np.ndarray,
    lines: list[str],
    start_y: int = 60,
    line_gap: int = 48,
    default_scale: float = 0.85,
    default_color: tuple[int, int, int] = (215, 215, 215),
    default_thickness: int = 2,
) -> None:
    """Render a list of text strings onto `img` using cv2.putText."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    y = start_y
    for line in lines:
        if not line:
            y += line_gap // 2
            continue
        # Leading '#' → heading (larger, bolder)
        if line.startswith("# "):
            text = line[2:]
            scale, thick = default_scale * 1.35, default_thickness + 1
        elif line.startswith("  "):
            text = line
            scale, thick = default_scale * 0.80, max(1, default_thickness - 1)
        else:
            text = line
            scale, thick = default_scale, default_thickness
        cv2.putText(img, text, (30, y), font, scale, default_color, thick, cv2.LINE_AA)
        y += line_gap


def _add_chalk_dust(img: np.ndarray, density: int = 120) -> None:
    """Scatter white-ish specks onto a dark board (simulates chalk residue)."""
    h, w = img.shape[:2]
    for _ in range(density):
        x = int(np.random.randint(10, w - 10))
        y = int(np.random.randint(10, h - 10))
        r = int(np.random.randint(1, 3))
        brightness = int(np.random.randint(160, 240))
        cv2.circle(img, (x, y), r, (brightness, brightness, brightness), -1)


def _add_noise(img: np.ndarray, sigma: int = 8) -> np.ndarray:
    """Add Gaussian noise to an image."""
    noise = np.random.normal(0, sigma, img.shape).astype(np.int16)
    return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def synthesize_blackboard() -> np.ndarray:
    # bg=(40,40,40): real chalkboards reflect ambient light; too close to 0 fails brightness check
    img = _board_canvas(bg_bgr=(40, 40, 40))
    _put_lines(img, [
        "# Newton's Laws of Motion",
        "",
        "1st Law:  Object at rest stays at rest",
        "  (unless acted upon by net force)",
        "",
        "2nd Law:  F = m * a",
        "  Force = Mass x Acceleration",
        "",
        "3rd Law:  Action = -Reaction",
        "",
        "Example:  F = 5 kg * 2 m/s^2 = 10 N",
    ], default_color=(215, 215, 215))
    _add_chalk_dust(img, density=180)
    return img


def synthesize_greenboard() -> np.ndarray:
    # Dominant green background — must pass _is_green_chalkboard() hue check
    img = _board_canvas(bg_bgr=(20, 105, 28), border_bgr=(15, 75, 20))
    _put_lines(img, [
        "# Photosynthesis",
        "",
        "6CO2 + 6H2O -> C6H12O6 + 6O2",
        "",
        "Reactants:",
        "  Carbon dioxide (CO2)",
        "  Water (H2O)",
        "",
        "Products:",
        "  Glucose (C6H12O6)",
        "  Oxygen (O2)",
        "",
        "Energy source: Sunlight + Chlorophyll",
    ], default_color=(240, 240, 180), default_thickness=2)
    _add_chalk_dust(img, density=100)
    return img


def synthesize_whiteboard() -> np.ndarray:
    img = _board_canvas(bg_bgr=(245, 245, 245), border_bgr=(200, 200, 200))
    # Add subtle glare hotspot (top-right quadrant)
    gx, gy = img.shape[1] * 3 // 4, img.shape[0] // 4
    cv2.circle(img, (gx, gy), 60, (255, 255, 255), -1)
    cv2.GaussianBlur(img[gy - 70:gy + 70, gx - 70:gx + 70], (41, 41), 15,
                     dst=img[gy - 70:gy + 70, gx - 70:gx + 70])
    _put_lines(img, [
        "# Sprint Planning",
        "",
        "1. Review backlog items",
        "2. Estimate story points",
        "3. Assign to team members",
        "",
        "Velocity:  28 pts / sprint",
        "Capacity:  3 engineers * 5 days",
        "",
        "Goal: Ship login feature by Friday",
    ], default_color=(15, 15, 155), default_thickness=2)
    return img


def synthesize_messy_handwriting() -> np.ndarray:
    """
    Simulate messy handwriting: irregular font scales, rotated lines,
    crowded spacing, and added background noise.
    """
    img = _board_canvas(bg_bgr=(42, 42, 42))
    font = cv2.FONT_HERSHEY_COMPLEX_SMALL  # slightly more irregular than SIMPLEX
    rng = np.random.default_rng(42)

    lines = [
        "States of Matter",
        "Solid   Liquid   Gas",
        "Fixed vol + shape",
        "vol fixed shape variable",
        "No fixed vol or shape",
        "Melting Pt = 0 C (ice->water)",
        "Boiling Pt = 100 C",
        "Evaporation vs Condensation",
    ]
    y = 55
    for line in lines:
        if not line:
            y += 25
            continue
        scale  = float(rng.uniform(0.60, 1.10))
        thick  = int(rng.integers(1, 3))
        color  = tuple(int(c) for c in rng.integers(170, 235, 3).tolist())
        x_off  = int(rng.integers(-8, 25))
        angle  = float(rng.uniform(-4.0, 4.0))

        # Render text to a temporary canvas, rotate it, paste back
        tmp = np.zeros_like(img)
        cv2.putText(tmp, line, (30 + x_off, y), font, scale,
                    color, thick, cv2.LINE_AA)
        # Small rotation around the text start point
        M = cv2.getRotationMatrix2D((30 + x_off, y), angle, 1.0)
        rotated = cv2.warpAffine(tmp, M, (img.shape[1], img.shape[0]))
        # Blend: max so rotated text doesn't erase existing content
        img = np.maximum(img, rotated)
        y += int(rng.integers(42, 56))

    img = _add_noise(img, sigma=12)
    _add_chalk_dust(img, density=250)
    return img


def synthesize_tilted_board() -> np.ndarray:
    """
    Generate a clean board then apply a 4-point perspective warp to simulate
    a ~30° off-axis camera angle (trapezoidal distortion).
    """
    base = _board_canvas(h=480, w=640, bg_bgr=(18, 18, 18))
    _put_lines(base, [
        "# Quadratic Equations",
        "",
        "ax^2 + bx + c = 0",
        "",
        "x = (-b +/- sqrt(b^2 - 4ac)) / 2a",
        "",
        "Discriminant D = b^2 - 4ac",
        "  D > 0 : two real roots",
        "  D = 0 : one real root",
        "  D < 0 : no real roots",
    ], default_color=(215, 215, 215))
    _add_chalk_dust(base, density=120)

    h, w = base.shape[:2]

    # Source: full board rectangle (TL, TR, BR, BL)
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])

    # Destination: trapezoid simulating ~30° left-tilt of the camera
    # Right side is compressed; left side is expanded
    skew_x = int(w * 0.18)
    skew_y = int(h * 0.10)
    dst = np.float32([
        [skew_x,          skew_y],          # TL shifted right+down
        [w - 5,           0],               # TR stays near top-right
        [w - skew_x // 2, h - 5],           # BR stays near bottom-right
        [0,               h - skew_y],      # BL stays near bottom-left
    ])

    # Place the warped board on a larger canvas (simulating the full photo frame).
    # Canvas bg at (62, 52, 42) keeps mean brightness above the 30.0 threshold
    # while still looking like a dim classroom wall/floor surround.
    canvas_h, canvas_w = int(h * 1.25), int(w * 1.20)
    canvas = np.full((canvas_h, canvas_w, 3), (62, 52, 42), dtype=np.uint8)

    # Offset destination into canvas centre
    pad_x, pad_y = (canvas_w - w) // 2, (canvas_h - h) // 2
    dst_offset = dst + np.float32([pad_x, pad_y])
    src_full = np.float32([[0, 0], [w, 0], [w, h], [0, h]])

    M = cv2.getPerspectiveTransform(src_full, dst_offset)
    cv2.warpPerspective(base, M, (canvas_w, canvas_h), dst=canvas,
                        flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_TRANSPARENT)
    return canvas


def synthesize_low_light() -> np.ndarray:
    """
    Create an image that will be rejected by validate_frame() due to low brightness.
    Mean brightness must be < 30.0 (MIN_MEAN_BRIGHTNESS).
    """
    img = np.full((520, 720, 3), (8, 8, 8), dtype=np.uint8)
    # Faint text — barely visible, brightness still < threshold
    _put_lines(img, [
        "# Ohm's Law",
        "",
        "V = I * R",
        "Voltage = Current * Resistance",
        "",
        "Unit: Volt = Ampere * Ohm",
    ], default_color=(28, 28, 28), default_thickness=1)
    return img


_SYNTHESIZERS = {
    "blackboard":       synthesize_blackboard,
    "greenboard":       synthesize_greenboard,
    "whiteboard":       synthesize_whiteboard,
    "messy_handwriting": synthesize_messy_handwriting,
    "tilted_board":     synthesize_tilted_board,
    "low_light":        synthesize_low_light,
}


# ── Pipeline wrappers ─────────────────────────────────────────────────────────

def _import_ocr_pipeline():
    """Import OCR modules, exit cleanly if cv2/numpy not installed."""
    try:
        from app.ocr.image_preprocessor import validate_frame, to_ocr_ready
        from app.ocr.board_detector import detect_board, draw_board_outline
        from app.ocr.ocr_service import process_frame
        return validate_frame, to_ocr_ready, detect_board, draw_board_outline, process_frame
    except ImportError as exc:
        print(f"\nERROR: Could not import app.ocr — {exc}")
        print("  Run from backend/: cd ACI/backend && .venv/bin/python scripts/test_ocr_local.py")
        sys.exit(1)


def run_pipeline_on_image(
    image_bgr: np.ndarray,
    image_path: Path,
    spec: CategorySpec,
    frame_id: str,
) -> tuple[TestResult, np.ndarray, np.ndarray, np.ndarray]:
    """
    Run the full OCR pipeline on a BGR image.

    Returns:
        (TestResult, warped_bgr, ocr_ready_gray, outline_bgr)
        The extra images are used for debug composite generation.
    """
    validate_frame, to_ocr_ready, detect_board, draw_board_outline, process_frame = _import_ocr_pipeline()
    h, w = image_bgr.shape[:2]

    # Stage 1: Validation
    t0 = time.monotonic()
    vr = validate_frame(image_bgr)
    val_ms = int((time.monotonic() - t0) * 1000)

    if not vr.is_valid:
        timings = StageTimings(validation_ms=val_ms)
        return (
            TestResult(
                category=spec.name, image_path=image_path, board_type=spec.board_type,
                synthetic=False, is_valid=False, reject_reason=vr.reason,
                blur_score=vr.blur_score, brightness=vr.brightness, image_size=(w, h),
                board_found=False, board_bbox=None, warped_size=None,
                engine_used="none", confidence=0.0, needs_review=False,
                region_count=0, raw_text="", ocr_error=None,
                timings=timings, expected_valid=spec.expected_valid,
            ),
            image_bgr.copy(), np.zeros((h, w), dtype=np.uint8), image_bgr.copy(),
        )

    # Stage 2: Board detection
    t1 = time.monotonic()
    board = detect_board(image_bgr)
    det_ms = int((time.monotonic() - t1) * 1000)
    outline_bgr = draw_board_outline(image_bgr, board)

    # Stage 3: Preprocessing
    t2 = time.monotonic()
    _, ocr_ready = to_ocr_ready(board.warped, spec.board_type)
    pre_ms = int((time.monotonic() - t2) * 1000)
    hw, ww = board.warped.shape[:2]

    # Stage 4: OCR (via full process_frame which re-runs internally)
    t3 = time.monotonic()
    image_bytes = cv2.imencode(".jpg", image_bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()
    result = process_frame(image_bytes, frame_id=frame_id, board_type=spec.board_type)
    ocr_ms = int((time.monotonic() - t3) * 1000)

    timings = StageTimings(
        validation_ms=val_ms, detection_ms=det_ms,
        preprocess_ms=pre_ms, ocr_ms=ocr_ms,
    )

    return (
        TestResult(
            category=spec.name, image_path=image_path, board_type=spec.board_type,
            synthetic=False, is_valid=True, reject_reason=None,
            blur_score=vr.blur_score, brightness=vr.brightness, image_size=(w, h),
            board_found=board.found, board_bbox=board.original_bbox,
            warped_size=(ww, hw),
            engine_used=result.engine_used,
            confidence=result.confidence, needs_review=result.needs_review,
            region_count=len(result.regions), raw_text=result.raw_text,
            ocr_error=result.error, regions=result.regions,
            timings=timings, expected_valid=spec.expected_valid,
        ),
        board.warped, ocr_ready, outline_bgr,
    )


# ── Debug image helpers ───────────────────────────────────────────────────────

# BGR colours per region type (for box outlines on the OCR overlay)
_REGION_COLORS: dict[str, tuple[int, int, int]] = {
    "heading":  (80,  220, 80),    # green
    "formula":  (60,  180, 240),   # sky-blue
    "list":     (240, 200, 60),    # yellow
    "text":     (200, 200, 200),   # light grey
    "diagram":  (160, 80,  220),   # purple
}


def _draw_ocr_overlay(image_bgr: np.ndarray, result: Any) -> np.ndarray:
    """
    Draw bounding boxes and labels from OCR regions onto the image.

    Box colour   = region type
    Box opacity  = confidence (thicker border for higher conf)
    Label        = type + confidence score
    """
    vis = image_bgr.copy()
    if not result or not hasattr(result, "regions") or not result.regions:
        return vis
    for r in result.regions:
        if not r.bbox or len(r.bbox) < 4:
            continue
        x1, y1, x2, y2 = (int(v) for v in r.bbox[:4])
        color = _REGION_COLORS.get(r.type, (200, 200, 200))
        conf  = r.confidence or 0.0
        thick = 3 if conf >= 0.75 else (2 if conf >= 0.50 else 1)
        cv2.rectangle(vis, (x1, y1), (x2, y2), color, thick)
        label = f"{r.type[:3]} {conf:.2f}"
        # Tiny background pill behind the label
        (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.38, 1)
        cv2.rectangle(vis, (x1, y1 - lh - 4), (x1 + lw + 4, y1), color, -1)
        cv2.putText(vis, label, (x1 + 2, y1 - 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 0, 0), 1, cv2.LINE_AA)
    return vis


def _panel(img: np.ndarray, label: str, target_w: int = 360, target_h: int = 270) -> np.ndarray:
    """
    Resize `img` to (target_w × target_h), add a labelled header bar.
    Handles both grayscale and BGR input.
    """
    if len(img.shape) == 2:                          # grayscale → BGR
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    resized = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_AREA)

    # Header bar (dark strip above the image)
    bar_h = 22
    header = np.full((bar_h, target_w, 3), (30, 30, 30), dtype=np.uint8)
    cv2.putText(header, label, (6, 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 200), 1, cv2.LINE_AA)
    return np.vstack([header, resized])


def make_composite(
    original:   np.ndarray,
    outline:    np.ndarray,
    warped:     np.ndarray,
    preprocessed: np.ndarray,
    ocr_overlay: np.ndarray,
    category:   str,
    result:     TestResult,
) -> np.ndarray:
    """
    Build a 2×3 composite showing all pipeline stages.

    Row 1: Original | Board outline | Warped (perspective-corrected)
    Row 2: Preprocessed | OCR overlay | Stats panel
    """
    pw, ph = 360, 270  # panel width × height (excluding header bar)

    p1 = _panel(original,     "1. Original input",            pw, ph)
    p2 = _panel(outline,      "2. Board detection",           pw, ph)
    p3 = _panel(warped,       "3. Perspective correction",    pw, ph)
    p4 = _panel(preprocessed, "4. Preprocessed (OCR-ready)",  pw, ph)
    p5 = _panel(ocr_overlay,  "5. OCR overlay (boxes+conf)",  pw, ph)

    # Panel 6: text stats
    bar_h = p1.shape[0] - ph
    stats_img = np.full((ph + bar_h, pw, 3), (20, 20, 20), dtype=np.uint8)
    cv2.putText(stats_img, "6. Results", (6, 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 200), 1, cv2.LINE_AA)

    lines_info = [
        f"Category:  {category}",
        f"Board:     {result.board_type}",
        f"Status:    {result.outcome_label}",
        f"Engine:    {result.engine_used}",
        f"Conf:      {result.confidence:.3f}",
        f"Regions:   {result.region_count}",
        f"Blur:      {result.blur_score:.1f}",
        f"Bright:    {result.brightness:.1f}",
        f"Total ms:  {result.timings.total_ms}",
        f"  valid:   {result.timings.validation_ms}ms",
        f"  detect:  {result.timings.detection_ms}ms",
        f"  preproc: {result.timings.preprocess_ms}ms",
        f"  ocr:     {result.timings.ocr_ms}ms",
    ]
    for i, line in enumerate(lines_info):
        y = bar_h + 22 + i * 17
        color = (180, 220, 180) if i == 2 and result.passed else \
                (220, 100, 100) if i == 2 and not result.passed else \
                (180, 180, 180)
        cv2.putText(stats_img, line, (8, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, color, 1, cv2.LINE_AA)

    row1 = np.hstack([p1, p2, p3])
    row2 = np.hstack([p4, p5, stats_img])
    return np.vstack([row1, row2])


# ── Save debug output ─────────────────────────────────────────────────────────

def save_debug_images(
    category:     str,
    original:     np.ndarray,
    outline:      np.ndarray,
    warped:       np.ndarray,
    preprocessed: np.ndarray,
    result:       TestResult,
    save_dir:     Path,
) -> Path:
    """
    Save per-stage images + composite to `save_dir/category/`.

    Files written:
      00_synthetic_input.jpg   (only when synthetic)
      01_original.jpg
      02_board_outline.jpg
      03_warped.jpg
      04_preprocessed.jpg
      05_ocr_overlay.jpg
      06_composite.jpg
    """
    out = save_dir / category
    out.mkdir(parents=True, exist_ok=True)

    q = [cv2.IMWRITE_JPEG_QUALITY, 92]

    cv2.imwrite(str(out / "01_original.jpg"), original, q)
    cv2.imwrite(str(out / "02_board_outline.jpg"), outline, q)
    cv2.imwrite(str(out / "03_warped.jpg"), warped, q)
    cv2.imwrite(str(out / "04_preprocessed.jpg"), preprocessed, q)

    ocr_overlay = _draw_ocr_overlay(warped if result.board_found else original, result)
    cv2.imwrite(str(out / "05_ocr_overlay.jpg"), ocr_overlay, q)

    composite = make_composite(original, outline, warped, preprocessed,
                               ocr_overlay, category, result)
    cv2.imwrite(str(out / "06_composite.jpg"), composite, q)

    return out


# ── Per-category test runner ──────────────────────────────────────────────────

def run_category(
    spec:        CategorySpec,
    save_dir:    Path | None,
    use_synthetic: bool,
    quiet:       bool,
) -> TestResult:
    """Run one category: pick or generate an image, run pipeline, save debug."""
    # 1. Resolve image -------------------------------------------------------
    real_images: list[Path] = []
    sample_dir = _SAMPLE_IMAGES / spec.name
    if sample_dir.is_dir():
        real_images = sorted(
            p for p in sample_dir.iterdir()
            if p.suffix.lower() in {".jpg", ".jpeg", ".png"} and p.name != ".gitkeep"
        )

    if real_images and not use_synthetic:
        image_path = real_images[0]
        image_bgr  = cv2.imread(str(image_path))
        is_synthetic = False
    else:
        # Generate synthetic
        synthesize = _SYNTHESIZERS[spec.name]
        image_bgr  = synthesize()
        stem        = f"{spec.name}_synthetic"
        if save_dir:
            save_dir.mkdir(parents=True, exist_ok=True)
            synth_path = save_dir / spec.name / "00_synthetic_input.jpg"
            synth_path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(synth_path), image_bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
            image_path = synth_path
        else:
            image_path = Path(f"<synthetic:{stem}>")
        is_synthetic = True

    if image_bgr is None:
        print(_c(_RED, f"  ERROR: Cannot read {image_path}"))
        # Return a dummy failed result
        return TestResult(
            category=spec.name, image_path=image_path, board_type=spec.board_type,
            synthetic=is_synthetic, is_valid=False, reject_reason="unreadable",
            blur_score=0.0, brightness=0.0, image_size=(0, 0),
            board_found=False, board_bbox=None, warped_size=None,
            engine_used="none", confidence=0.0, needs_review=False,
            region_count=0, raw_text="", ocr_error="unreadable",
            expected_valid=spec.expected_valid,
        )

    frame_id = str(uuid.uuid4())

    # 2. Run pipeline --------------------------------------------------------
    result, warped, preprocessed, outline = run_pipeline_on_image(
        image_bgr, image_path, spec, frame_id
    )
    result.synthetic = is_synthetic

    # 3. Print per-image report ----------------------------------------------
    if not quiet:
        _print_image_report(result, spec, image_path, is_synthetic)

    # 4. Save debug images ---------------------------------------------------
    if save_dir:
        save_debug_images(
            category=spec.name,
            original=image_bgr,
            outline=outline,
            warped=warped,
            preprocessed=preprocessed,
            result=result,
            save_dir=save_dir,
        )

    return result


# ── Printing ──────────────────────────────────────────────────────────────────

_RULER = "─" * 72


def _print_image_report(
    result: TestResult,
    spec: CategorySpec,
    image_path: Path,
    is_synthetic: bool,
) -> None:
    src_tag = _c(_DIM, "[synthetic]") if is_synthetic else _c(_DIM, f"[{image_path.name}]")
    print(f"\n{_c(_DIM, _RULER)}")
    print(
        _c(_BOLD, _CYAN, f"  {spec.name.upper():<22}")
        + f"  {spec.description}  {src_tag}"
    )
    print()

    # ── Validation ──
    print(_c(_BOLD, "  VALIDATION"))
    w, h = result.image_size
    print(f"    Size:       {w}×{h} px")
    print(f"    Blur score: {result.blur_score:.1f}  "
          + _c(_DIM, "(threshold: 50.0)"))
    print(f"    Brightness: {result.brightness:.1f}  "
          + _c(_DIM, "(threshold: 30.0)"))
    if result.is_valid:
        print(f"    Result:     {_c(_GREEN, 'VALID')}")
    else:
        print(f"    Result:     {_c(_RED, 'REJECTED')} — {result.reject_reason}")
        if not spec.expected_valid:
            print(f"    {_c(_GREEN, '✓ Expected rejection (low_light category)')}")
        return

    # ── Board detection ──
    print(_c(_BOLD, "\n  BOARD DETECTION"))
    if result.board_found:
        bb = result.board_bbox
        print(f"    Found at:   ({bb[0]},{bb[1]}) {bb[2]}×{bb[3]} px  "
              + _c(_GREEN, "✓"))
        ww, wh = result.warped_size
        print(f"    Warped to:  {ww}×{wh} px")
    else:
        print(f"    {_c(_YELLOW, 'No clear rectangle detected — using full frame')}")

    # ── Preprocessing ──
    print(_c(_BOLD, "\n  PREPROCESSING"))
    pp_map = {
        "chalkboard": "invert → CLAHE(clip=3.0) → chalk-dust removal",
        "whiteboard": "CLAHE(clip=2.0) → glare suppression → bilateral filter",
        "smartboard": "CLAHE(clip=1.5)",
    }
    print(f"    Path:  {pp_map.get(result.board_type, result.board_type)}")
    print(f"    Time:  {result.timings.preprocess_ms} ms")

    # ── OCR ──
    print(_c(_BOLD, "\n  OCR"))
    if result.ocr_error:
        if "No OCR engine" in result.ocr_error:
            print(f"    {_c(_YELLOW, 'No engine installed — placeholder result')}")
            print(f"    {_c(_DIM, 'Install: pip install paddlepaddle paddleocr  OR  pytesseract')}")
        else:
            print(f"    {_c(_RED, 'Error:')} {result.ocr_error}")
        return

    cc = _conf_colour(result.confidence)
    print(f"    Engine:     {result.engine_used}")
    print(f"    Confidence: {_c(cc, f'{result.confidence:.3f}')}"
          + ("  " + _c(_YELLOW, "⚠ needs review") if result.needs_review else ""))
    print(f"    Regions:    {result.region_count}")
    print(f"    Time:       {result.timings.ocr_ms} ms")

    # ── Timing breakdown ──
    t = result.timings
    print(_c(_BOLD, "\n  TIMING"))
    print(f"    Validate: {t.validation_ms:>4} ms   Detect:   {t.detection_ms:>4} ms")
    print(f"    Preproc:  {t.preprocess_ms:>4} ms   OCR:      {t.ocr_ms:>4} ms")
    print(f"    Total:    {t.total_ms:>4} ms")

    # ── Region table ──
    if result.regions:
        print(_c(_BOLD, "\n  REGIONS"))
        type_col = {
            "heading": _BOLD,
            "formula": _YELLOW,
            "list":    _CYAN,
            "text":    _WHITE,
            "diagram": _DIM,
        }
        for i, r in enumerate(result.regions, 1):
            cc2 = _conf_colour(r.confidence or 0.0)
            tc  = type_col.get(r.type, _WHITE)
            preview = (r.content or "(diagram)")[:70]
            if r.content and len(r.content) > 70:
                preview += "…"
            conf_str = f"{r.confidence:.2f}" if r.confidence is not None else "n/a "
            print(
                f"    {i:2}. {_c(tc, f'{r.type:<10}')}"
                f"  {_c(cc2, conf_str)}"
                f"  {preview}"
            )

    # ── Raw text preview ──
    if result.raw_text:
        print(_c(_BOLD, "\n  EXTRACTED TEXT"))
        lines = result.raw_text.strip().split("\n")
        for line in lines[:15]:
            print(f"    {line}")
        if len(lines) > 15:
            print(_c(_DIM, f"    … ({len(lines) - 15} more lines)"))


def print_summary_table(results: list[TestResult], save_dir: Path | None) -> None:
    """Print the final summary table across all tested categories."""
    print(f"\n{_c(_DIM, _RULER)}")
    print(_c(_BOLD, _CYAN, "  SUMMARY"))
    print(_c(_DIM, _RULER))

    header = (
        f"  {'Category':<22} {'Status':<20} {'Engine':<12}"
        f"{'Conf':>6}  {'Reg':>4}  {'Total ms':>9}  {'Pass'}"
    )
    print(_c(_BOLD, header))
    print(_c(_DIM, "  " + "─" * 70))

    passed = 0
    for r in results:
        status_str = r.outcome_label
        sc = _GREEN if r.passed else (_YELLOW if "NO ENGINE" in status_str else _RED)
        cc = _conf_colour(r.confidence)
        pass_icon = _c(_GREEN, "✓") if r.passed else _c(_RED, "✗")

        print(
            f"  {r.category:<22} "
            f"{_c(sc, f'{status_str:<20}')} "
            f"{r.engine_used:<12}"
            f"{_c(cc, f'{r.confidence:>6.3f}')}  "
            f"{r.region_count:>4}  "
            f"{r.timings.total_ms:>9}  "
            f"{pass_icon}"
        )
        if r.passed:
            passed += 1

    print(_c(_DIM, "  " + "─" * 70))
    total = len(results)
    pc = _GREEN if passed == total else (_YELLOW if passed > total // 2 else _RED)
    print(f"  {_c(_BOLD, 'Result:')} {_c(pc, f'{passed}/{total} passed')}")

    if save_dir:
        print(f"\n  Debug images saved to: {_c(_CYAN, str(save_dir))}")
        print(f"  Each category has: 01_original  02_board_outline  03_warped")
        print(f"                     04_preprocessed  05_ocr_overlay  06_composite")

    print()


# ── Single-image mode ─────────────────────────────────────────────────────────

def run_single_image(
    image_path: Path,
    board_type: str,
    save_debug: Path | None,
    quiet: bool,
) -> None:
    """Run the harness on one user-supplied image (not a predefined category)."""
    spec = CategorySpec(
        name=image_path.stem,
        board_type=board_type,
        expected_valid=True,
        description=f"User-supplied image ({board_type})",
        hint="",
    )
    image_bgr = cv2.imread(str(image_path))
    if image_bgr is None:
        print(_c(_RED, f"ERROR: Cannot read {image_path}"))
        sys.exit(1)

    frame_id = str(uuid.uuid4())
    result, warped, preprocessed, outline = run_pipeline_on_image(
        image_bgr, image_path, spec, frame_id
    )
    result.synthetic = False

    if not quiet:
        _print_image_report(result, spec, image_path, False)

    if save_debug:
        out = save_debug_images(
            category=image_path.stem,
            original=image_bgr,
            outline=outline,
            warped=warped,
            preprocessed=preprocessed,
            result=result,
            save_dir=save_debug,
        )
        print(f"\n  Debug images saved to: {_c(_CYAN, str(out))}")

    print_summary_table([result], save_debug)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    global _USE_COLOR

    parser = argparse.ArgumentParser(
        description="ACI OCR test harness — runs all six board categories.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--image", metavar="PATH",
        help="Test a single real image (skips category generation).",
    )
    parser.add_argument(
        "--board-type", default="chalkboard",
        choices=["chalkboard", "whiteboard", "smartboard"],
        help="Board type for --image mode (default: chalkboard).",
    )
    parser.add_argument(
        "--categories", nargs="+", metavar="CAT",
        choices=ALL_CATEGORY_NAMES + ["all"],
        default=["all"],
        help="Categories to run (default: all). E.g. --categories blackboard whiteboard",
    )
    parser.add_argument(
        "--save-debug", metavar="DIR", default="./debug_out",
        help="Directory for debug images (default: ./debug_out).",
    )
    parser.add_argument(
        "--no-save", action="store_true",
        help="Do not save any debug images.",
    )
    parser.add_argument(
        "--no-synthetic", action="store_true",
        help="Skip categories with no real images (don't generate synthetic ones).",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Only print the summary table (suppress per-image detail).",
    )
    parser.add_argument(
        "--no-color", action="store_true",
        help="Disable ANSI colour output.",
    )
    args = parser.parse_args()

    _USE_COLOR = not args.no_color and sys.stdout.isatty()
    save_dir = None if args.no_save else Path(args.save_debug)

    # ── Single-image mode ────────────────────────────────────────────────────
    if args.image:
        run_single_image(Path(args.image), args.board_type, save_dir, args.quiet)
        return

    # ── Category batch mode ──────────────────────────────────────────────────
    cats = ALL_CATEGORY_NAMES if "all" in args.categories else args.categories

    print(
        _c(_BOLD, _CYAN, "\n  ACI OCR Test Harness")
        + _c(_DIM, f"  ({len(cats)} categories)")
    )
    if not args.quiet:
        print(_c(_DIM, f"  Sample images: {_SAMPLE_IMAGES}"))
        print(_c(_DIM, f"  Debug output:  {save_dir or 'disabled'}"))

    results: list[TestResult] = []
    for cat_name in cats:
        spec = CATEGORIES[cat_name]
        # Check whether real images exist
        real_dir = _SAMPLE_IMAGES / cat_name
        has_real = real_dir.is_dir() and any(
            p.suffix.lower() in {".jpg", ".jpeg", ".png"}
            for p in real_dir.iterdir()
            if p.name != ".gitkeep"
        )

        if args.no_synthetic and not has_real:
            print(_c(_DIM, f"\n  Skipping {cat_name} (no real images, --no-synthetic set)"))
            continue

        result = run_category(
            spec=spec,
            save_dir=save_dir,
            use_synthetic=not has_real,
            quiet=args.quiet,
        )
        results.append(result)

    if results:
        print_summary_table(results, save_dir)


if __name__ == "__main__":
    main()
