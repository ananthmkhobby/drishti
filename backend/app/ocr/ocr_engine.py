"""
OCR engine wrapper: PaddleOCR (primary) + Tesseract (fallback).

Confidence routing (from OCR_PIPELINE.md):
  paddleocr_conf >= 0.75       → use PaddleOCR result as-is
  paddleocr_conf 0.50–0.74     → also run Tesseract, pick higher confidence
  paddleocr_conf < 0.50        → use best available, set needs_review=True

Both engines are loaded lazily — the app starts without them installed.
Install instructions:
  pip install paddlepaddle paddleocr            # PaddleOCR
  pip install pytesseract Pillow               # Tesseract wrapper
  brew install tesseract                        # macOS binary
  apt-get install tesseract-ocr                 # Ubuntu/Debian

Region type heuristics:
  formula  — contains math operators + short (< 12 words)
  heading  — taller than 1.5× median bbox height + short (< 10 words)
  list     — starts with digit. or bullet character
  diagram  — very low text density relative to bbox area
  text     — default fallback
"""

from __future__ import annotations

import re
import time
import logging
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Confidence thresholds
# ---------------------------------------------------------------------------

CONF_HIGH = 0.75    # PaddleOCR result accepted without Tesseract fallback
CONF_LOW = 0.50     # Below this: needs_review flag set

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TextRegion:
    type: str                   # text | heading | formula | list | diagram
    content: str | None         # None for diagram regions
    bbox: list[float]           # [x1, y1, x2, y2] in pixels
    confidence: float | None    # 0–1 normalised; None for diagrams
    engine: str | None = None   # paddleocr | tesseract


@dataclass
class FrameOCRResult:
    frame_id: str
    engine_used: str            # paddleocr | tesseract | openai | none
    confidence: float           # mean across all detected regions
    regions: list[TextRegion]
    raw_text: str               # plain concatenated text, newline-separated
    needs_review: bool = False  # True when confidence < CONF_LOW
    processing_ms: int = 0
    error: str | None = None    # set on hard failure (both engines unavailable)
    privacy_blurred: int = 0             # number of face/body regions blurred for privacy
    blurred_image_bytes: bytes | None = None  # re-encoded JPEG of blurred frame (None if no people)
    # Board detection metadata (set by process_frame in ocr_service.py)
    board_type: str = "chalkboard"        # effective board type used for preprocessing
    board_confidence: float = 0.0         # board detection confidence 0–1
    board_detection_method: str = "fallback"  # calibrated|vision|yolo|contour|fallback
    # Cropped diagram images + correctness validation (populated by
    # crop_and_validate_diagrams() in ocr_service.py's process_frame()).
    # Each entry: {"description": str, "image_bytes": bytes, "validation": dict}
    diagrams: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Lazy engine singletons
# ---------------------------------------------------------------------------

_paddle_instance: Any = None
_paddle_available: bool | None = None
_tesseract_available: bool | None = None


def _get_paddle() -> Any:
    """Initialise PaddleOCR once and cache. Returns None when not installed."""
    global _paddle_instance, _paddle_available
    if _paddle_available is not None:
        return _paddle_instance if _paddle_available else None
    try:
        from paddleocr import PaddleOCR  # type: ignore
        # use_angle_cls=True corrects upside-down / rotated text regions
        # show_log=False suppresses the very verbose PaddlePaddle startup
        # use_gpu=False → CPU-only; override at deploy time if GPU available
        _paddle_instance = PaddleOCR(
            use_angle_cls=True,
            lang="en",
            show_log=False,
            use_gpu=False,
        )
        _paddle_available = True
        logger.info("PaddleOCR initialised successfully")
    except Exception as exc:
        logger.warning("PaddleOCR not available: %s", exc)
        _paddle_available = False
    return _paddle_instance if _paddle_available else None


def _is_tesseract_available() -> bool:
    """Check Tesseract availability once and cache."""
    global _tesseract_available
    if _tesseract_available is not None:
        return _tesseract_available
    try:
        import pytesseract  # type: ignore
        pytesseract.get_tesseract_version()
        _tesseract_available = True
        logger.info("Tesseract available")
    except Exception:
        _tesseract_available = False
        logger.warning("Tesseract not available — fallback disabled")
    return _tesseract_available


# ---------------------------------------------------------------------------
# Region classification
# ---------------------------------------------------------------------------

# Matches: =, +, -, ×, ÷, ∫, ∑, √, <, >, ≤, ≥, ∈, ∩, π, Δ, ^, ², ³
_MATH_RE = re.compile(r"[=+\-×÷∫∑√<>≤≥∈∉∩∪πΔ^²³/]")
# Numbered list (1. / 1) / 1:) or bullet (• - * –)
_LIST_RE = re.compile(r"^\s*(\d+[.):\s]+|[•\-\*–]\s+)")


def _classify_region(text: str, bbox: list[float], median_height: float) -> str:
    """
    Classify a detected text block into one of:
    formula | heading | list | diagram | text

    diagram is only assigned here when text density is extremely low
    (the main diagram detector lives in board_detector + post-processing;
    this catches cases where OCR picks up a sparse region).
    """
    if not text or not text.strip():
        return "text"

    stripped = text.strip()
    words = stripped.split()

    # 1. List item first — a leading bullet/number must not be hijacked by the
    #    formula check (a `-` bullet would otherwise match _MATH_RE).
    if _LIST_RE.match(stripped):
        return "list"

    # 2. Formula — math operators in a non-list context, short line.
    if _MATH_RE.search(stripped) and len(words) < 12:
        return "formula"

    # 3. Heading — noticeably taller bbox than the median, short but multi-word text.
    #    Require ≥ 2 words so single-character labels don't get promoted to headings.
    bbox_h = bbox[3] - bbox[1]
    if median_height > 0 and bbox_h > 1.5 * median_height and 2 <= len(words) < 10:
        return "heading"

    # 4. Diagram detection is NOT done here for word-level OCR output.
    #    Tesseract returns one bounding box per *word*, so a short word like "Yu"
    #    in a large bbox will always have very low char_density — falsely labelled
    #    as a diagram. Real diagram regions are handled by board_detector upstream;
    #    OCR engines won't return meaningful text for them anyway.

    return "text"


# ---------------------------------------------------------------------------
# PaddleOCR parsing
# ---------------------------------------------------------------------------

def _run_paddle(image_bgr: np.ndarray, frame_id: str) -> tuple[list[TextRegion], float]:
    """
    Run PaddleOCR on `image_bgr` and return (regions, mean_confidence).
    Returns ([], 0.0) on any error.
    """
    paddle = _get_paddle()
    if paddle is None:
        return [], 0.0

    try:
        result = paddle.ocr(image_bgr, cls=True)
    except Exception as exc:
        logger.warning("PaddleOCR inference failed for frame %s: %s", frame_id, exc)
        return [], 0.0

    if not result or not result[0]:
        return [], 0.0

    lines = result[0]

    # First pass: collect heights for heading detection
    heights: list[float] = []
    for line in lines:
        pts, _ = line
        y_coords = [p[1] for p in pts]
        heights.append(max(y_coords) - min(y_coords))
    median_h = float(np.median(heights)) if heights else 0.0

    regions: list[TextRegion] = []
    confidences: list[float] = []

    for line in lines:
        pts, (text, conf) = line
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        bbox: list[float] = [min(xs), min(ys), max(xs), max(ys)]
        region_type = _classify_region(text.strip(), bbox, median_h)
        regions.append(TextRegion(
            type=region_type,
            content=text.strip() or None,
            bbox=bbox,
            confidence=round(float(conf), 4),
            engine="paddleocr",
        ))
        confidences.append(conf)

    mean_conf = float(np.mean(confidences)) if confidences else 0.0
    return regions, mean_conf


# ---------------------------------------------------------------------------
# Tesseract preprocessing
# ---------------------------------------------------------------------------

def _preprocess_for_tesseract(image_bgr: np.ndarray) -> "Any":
    """
    Adaptive Tesseract preprocessing.

    Instead of a fixed 2× upscale, we target a minimum image width of 2400 px
    so that Tesseract's LSTM always receives adequately-sized characters.
    At 1 m the board crop may already be 1200 px (→ 2×). At 30 ft it might
    be 150 px (→ 16×).  The iterative approach avoids the severe blur that
    a single large INTER_CUBIC produces.

    Steps:
      1. Grayscale
      2. Iterative 2× upscale steps until width ≥ 2400 px
    """
    from PIL import Image as PILImage  # type: ignore

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY) if len(image_bgr.shape) == 3 else image_bgr.copy()

    h, w = gray.shape[:2]
    logger.debug("_preprocess_for_tesseract: input %dx%d mean=%.1f", w, h, float(np.mean(gray)))

    # Iterative 2× upscale — better quality than single large resize
    target_w = 2400
    while w < target_w:
        step = min(2.0, target_w / max(w, 1))
        new_w, new_h = int(w * step), int(h * step)
        gray = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
        w, h = new_w, new_h

    logger.debug("_preprocess_for_tesseract: final size %dx%d", w, h)
    return PILImage.fromarray(gray)


# ---------------------------------------------------------------------------
# Tesseract parsing
# ---------------------------------------------------------------------------

def _run_tesseract(image_bgr: np.ndarray, frame_id: str) -> tuple[list[TextRegion], float, str]:
    """
    Run Tesseract on `image_bgr`.
    Returns (regions, mean_confidence, full_text). Returns empty on error.

    Tesseract config:
      --psm 11  : sparse text — find as much text as possible (best for boards
                  where content is scattered, not a single uniform block)
      --oem 1   : LSTM engine only (more accurate than combined mode 3)
      --dpi 150 : hint so Tesseract can infer approximate font sizes
    """
    if not _is_tesseract_available():
        return [], 0.0, ""

    try:
        import pytesseract  # type: ignore
    except ImportError:
        return [], 0.0, ""

    try:
        pil_img = _preprocess_for_tesseract(image_bgr)

        tess_config = "--psm 11 --oem 1 --dpi 150"

        data = pytesseract.image_to_data(
            pil_img,
            config=tess_config,
            output_type=pytesseract.Output.DICT,
        )

        heights: list[int] = []
        for i, text in enumerate(data["text"]):
            if data["conf"][i] > 0 and text.strip():
                heights.append(data["height"][i])
        median_h = float(np.median(heights)) if heights else 0.0

        regions: list[TextRegion] = []
        confidences: list[float] = []

        for i, text in enumerate(data["text"]):
            conf_raw = data["conf"][i]
            # Tesseract uses -1 as a sentinel for block/line-level rows (no word).
            # Accept any positive confidence, even low — real text on boards
            # often scores 10-40%.
            if conf_raw <= 0 or not text.strip():
                continue
            x = data["left"][i]
            y = data["top"][i]
            bw = data["width"][i]
            bh = data["height"][i]
            bbox: list[float] = [float(x), float(y), float(x + bw), float(y + bh)]
            norm_conf = conf_raw / 100.0
            region_type = _classify_region(text.strip(), bbox, median_h)
            regions.append(TextRegion(
                type=region_type,
                content=text.strip(),
                bbox=bbox,
                confidence=round(norm_conf, 4),
                engine="tesseract",
            ))
            confidences.append(norm_conf)

        mean_conf = float(np.mean(confidences)) if confidences else 0.0
        full_text = pytesseract.image_to_string(pil_img, config=tess_config).strip()
        logger.info(
            "Tesseract frame=%s words_total=%d words_accepted=%d conf=%.3f full_text_len=%d",
            frame_id, len(data["text"]), len(regions), mean_conf, len(full_text),
        )
        if full_text:
            logger.info("Tesseract raw text (first 200 chars): %r", full_text[:200])
        return regions, mean_conf, full_text

    except Exception as exc:
        logger.warning("Tesseract inference failed for frame %s: %s", frame_id, exc)
        return [], 0.0, ""


# ---------------------------------------------------------------------------
# OpenAI Vision OCR — Crop-and-Zoom two-pass pipeline
# ---------------------------------------------------------------------------
#
# Problem: LLM vision models downsample large images before processing.
# Far-away / tiny text (e.g. a board at 3 m) gets blurred before the model
# even sees it, causing hallucination or missed content.
#
# Solution — two passes per frame:
#   Pass 1  Layout detection   — full image, detail="low"
#           Ask GPT-4o-mini to return bounding boxes (0–999 space) for every
#           text zone. Fast and cheap; spatial layout survives downscaling.
#
#   Pass 2  Zone extraction    — per crop, detail="high"
#           Crop each zone from the ORIGINAL full-resolution image.
#           Upscale small crops (far-away text) to ≥ 512 px before sending.
#           Extract text with detail="high" so the model sees full resolution.
#
# Falls back to a single-pass extraction if the layout pass finds no zones.
# ---------------------------------------------------------------------------

_DIRECT_EXTRACT_PROMPT = (
    "You are a classroom transcription assistant.\n"
    "Your ONLY job is to copy text that is PHYSICALLY VISIBLE AND CLEARLY LEGIBLE in this image —\n"
    "whether it's written on a board (chalkboard/whiteboard) OR printed/handwritten on paper\n"
    "(a textbook, worksheet, notebook, or poster held up or propped in frame).\n\n"

    "MARKER COLOURS — IMPORTANT:\n"
    "  Text may be written in ANY colour: black, red, blue, green, purple, orange, etc.\n"
    "  Transcribe ALL visible text regardless of ink colour.\n"
    "  Red text on a white board is very common in Indian classrooms — do NOT skip or downgrade\n"
    "  confidence for coloured ink. Read it exactly as you would black ink.\n"
    "  Colour does NOT affect your confidence score — only legibility matters.\n\n"

    "VERIFICATION WARNING: The teacher will compare your output against the original image.\n"
    "Any word you report that is not actually present in the image will be caught immediately\n"
    "and will destroy trust in this tool. It is far better to return EMPTY than to invent text.\n\n"

    "ABSOLUTE RULES — violating any of these is an error:\n"
    "  1. NEVER guess, invent, or infer text. If you cannot clearly see a word, do NOT write it.\n"
    "  2. NEVER use your knowledge of the subject to fill in text you cannot actually see.\n"
    "     Example: if you see 'H2S' written down, do NOT write 'H2SO4' because chemistry tells you\n"
    "     sulfuric acid has that formula — only write exactly what you see.\n"
    "  3. If the image is blurry, dark, too far away, or the text is too small to read clearly\n"
    "     → return EXACTLY: {\"regions\": [], \"raw_text\": \"\"}\n"
    "  4. If there is no board/page in view, or no writing on it, or you are not certain any\n"
    "     text is present → return EXACTLY: {\"regions\": [], \"raw_text\": \"\"}\n"
    "  5. Copy text character-for-character as written — preserve spelling, capitalisation, symbols.\n"
    "  6. Only use [unclear] for a word that is MOSTLY visible but one or two characters are uncertain.\n"
    "     Do NOT use [unclear] as a placeholder for text you think should be there.\n"
    "  7. Do NOT describe the image, the room, or what you think the lesson is about.\n"
    "  8. A word that appears because of a background texture, shadow, or smudge is NOT real text.\n"
    "     Only include text that was deliberately written or printed by a human hand or press.\n\n"

    "CONFIDENCE SCORE — mandatory for every region:\n"
    "  Add a 'confidence' integer (0–100) to each region measuring how certain you are that\n"
    "  the text is genuinely written there and you have read every character correctly.\n"
    "  Scoring guide:\n"
    "    100 = every character crystal-clear, no ambiguity at all\n"
    "     80 = clearly written but one or two characters slightly uncertain\n"
    "     60 = readable but lighting or angle makes some characters hard\n"
    "    < 60 = do NOT include this region — omit it entirely\n"
    "  If your confidence in a region is below 60, leave it out rather than guessing.\n\n"

    "DIAGRAMS AND LABELLED FIGURES (important):\n"
    "  When you see a drawn diagram, chart, or labelled figure on the board:\n"
    "  a) Create ONE region with type=\"diagram\".\n"
    "  b) In 'content', write: 'Diagram: [what it shows]' followed by '| Labels: ' then\n"
    "     EVERY visible label, arrow annotation, and part name separated by commas.\n"
    "     Example: 'Diagram: human heart cross-section | Labels: aorta, left ventricle,\n"
    "               right atrium, pulmonary artery, mitral valve'\n"
    "  c) Also add EACH label/part name as a separate text region so it appears in raw_text.\n"
    "  d) If any equation or formula appears inside the diagram, add it as a formula region.\n"
    "  e) Only include labels you can actually read — do NOT invent anatomical/technical labels.\n"
    "  f) Add a 'bbox' field: [x1, y1, x2, y2] giving the diagram's bounding box in a 0-1000\n"
    "     normalized coordinate space (0,0 = top-left of the image, 1000,1000 = bottom-right).\n"
    "     Draw it as tightly as possible around the diagram's drawn lines/shapes only — do not\n"
    "     include surrounding body text. This field is ONLY needed for diagram-type regions.\n\n"

    "QUALITY SELF-CHECK before responding:\n"
    "  For each word you are about to write, ask: 'Can I see EVERY letter of this word clearly?'\n"
    "  If the answer is NO → either mark it [unclear] or drop it entirely.\n"
    "  Returning fewer words is always better than returning invented words.\n\n"

    "Return ONLY valid JSON (no markdown, no explanation):\n"
    "{\"regions\": [{\"type\": \"heading|text|formula|list|diagram\", \"content\": \"...\", \"confidence\": 95, "
    "\"bbox\": [120, 300, 560, 700]}], "
    "\"raw_text\": \"all text joined by newlines including all diagram labels\"}\n\n"
    "  (omit 'bbox' for every type except diagram)\n\n"
    "  heading  — title or header clearly written in larger text\n"
    "  text     — body text, notes, sentences\n"
    "  formula  — equation or math expression (e.g. F = ma)\n"
    "  list     — bullet or numbered item\n"
    "  diagram  — drawing or chart with labels (see DIAGRAMS section above)\n"
)

# Quick binary legibility check — sent before the full OCR prompt to avoid
# spending tokens on an image the model cannot actually read.
#
# Worded specifically as "board (chalkboard, whiteboard, etc.)" — shown a
# notebook page and asked that question, the model has a perfectly correct
# reading of "no, this isn't a board" and answers NO regardless of whether
# the handwriting itself is legible, silently killing notebook-mode OCR
# before the real extraction pass ever runs. Needs its own wording per
# surface rather than one prompt for both.
_LEGIBILITY_CHECK_PROMPT = (
    "Look at this image carefully.\n"
    "Is there text written on a board (chalkboard, whiteboard, etc.) that you can clearly read — "
    "meaning individual letters are sharp enough to distinguish?\n\n"
    "IMPORTANT: Text may be written in any colour (red, blue, green, black, etc.).\n"
    "Red marker on a white board is very common — answer YES if such text is clearly visible.\n\n"
    "Answer with ONLY one word: YES or NO.\n"
    "Answer NO if: the image is blurry, the text is too small, the board is empty, "
    "or you would have to guess what the text says."
)

_LEGIBILITY_CHECK_PROMPT_NOTEBOOK = (
    "Look at this image carefully.\n"
    "Is there handwritten or printed text on paper (a notebook, journal, or worksheet page) "
    "that you can clearly read — meaning individual letters are sharp enough to distinguish?\n\n"
    "IMPORTANT: Text may be written in any colour of pen or pencil (blue, black, red, etc.).\n"
    "Blue or black ballpoint pen is very common — answer YES if such text is clearly visible.\n\n"
    "Answer with ONLY one word: YES or NO.\n"
    "Answer NO if: the image is blurry, the text is too small, the page is blank, "
    "or you would have to guess what the text says."
)

# (Legacy two-pass prompts removed — replaced by _DIRECT_EXTRACT_PROMPT above)

# ---------------------------------------------------------------------------
# Hallucination detection — filter model descriptions masquerading as content
# ---------------------------------------------------------------------------

_HALLUCINATION_RE = re.compile(
    # Model describing the image rather than transcribing board text
    r"\bthis (?:appears?|seems?) to be\b"
    r"|\bi (?:can see|notice|observe|detect)\b"
    r"|\bthe (?:board|image|photo|picture|chalkboard|whiteboard) (?:shows?|contains?|appears?)\b"
    r"|\btypically (?:contains?|shows?)\b"
    r"|\beducational content\b"
    r"|\bblank\b.*\bboard\b"
    r"|\bno (?:text|content|writing) (?:is |are )?visible\b"
    r"|\bnothing (?:is |are )?(?:written|visible|present)\b"
    # Model describing room / physical environment instead of reading the board
    r"|\broom setup\b"
    r"|\b(?:in|of) the (?:image|photo|picture|room|background|foreground)\b"
    r"|\bthe image (?:shows?|depicts?|features?|contains?)\b"
    r"|\bthe photo (?:shows?|depicts?|features?|contains?)\b"
    r"|\bfeaturing .{0,30}(?:bed|chair|desk|table|sofa|couch|mattress|furniture)\b"
    r"|\b(?:bunk|twin|double|single) bed\b"
    r"|\bfabric[- ]covered\b"
    r"|\b(?:gray|grey|white|black|blue|green) (?:fabric|cloth|material|upholstered)\b"
    r"|\bsetup featuring\b"
    r"|\bvisible in the\b"
    r"|\b(?:two|three|four|several|multiple) .{0,20}(?:visible|present|can be seen)\b",
    re.IGNORECASE,
)


def _looks_hallucinated(content: str) -> bool:
    """
    Return True when content looks like a model description of the image
    rather than an actual transcription of text written on the board.
    """
    return bool(_HALLUCINATION_RE.search(content))


def _board_crop_is_legible(gray: np.ndarray) -> tuple[bool, str]:
    """
    Quick local quality gate for the raw (pre-upscale) board crop.

    Returns (is_legible, reason).
    Saves an API call when the crop is obviously unreadable.

    Thresholds are intentionally loose — we prefer false-positives
    (sending a borderline image to Vision) over false-negatives
    (rejecting a legitimate board shot).
    """
    h, w = gray.shape[:2]

    # Absolute minimum size — below this, no OCR engine can extract anything
    if w < 60 or h < 30:
        return False, f"board_crop_too_tiny:{w}x{h}"

    # Brightness: extremely dark boards have no visible chalk/marker strokes
    mean_brightness = float(gray.mean())
    if mean_brightness < 8.0:
        return False, f"board_too_dark:{mean_brightness:.1f}"

    # Sharpness: Laplacian variance on the raw crop.
    # A blank/empty board has ~0 variance; any writing at all gives > 1.
    # Very blurry boards from 10 m+ have 0.1–2.0.
    # We only reject at an extremely low threshold to avoid killing valid shots.
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if lap_var < 0.3:
        return False, f"board_no_detail:{lap_var:.2f}"

    return True, "ok"


def _strip_fences(text: str) -> str:
    """Remove optional markdown code fences that the model may add."""
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$",       "", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Vision helpers
# ---------------------------------------------------------------------------

def _encode_for_vision(img: np.ndarray, target_min_dim: int = 1024) -> str:
    """
    Encode an image to base64 JPEG for the Vision API.

    Small board crops (distant shots) are upscaled iteratively to
    `target_min_dim` on the short edge so GPT-4o's 512-px tiles actually
    contain readable characters.  Capped at 2048 px long edge.
    """
    import base64

    h, w = img.shape[:2]
    cur_min = min(h, w)

    # Upscale iteratively — avoids the blur of a single large resize
    result = img.copy()
    rh, rw = h, w
    while min(rh, rw) < target_min_dim:
        step = min(2.0, target_min_dim / max(min(rh, rw), 1))
        rw2, rh2 = int(rw * step), int(rh * step)
        result = cv2.resize(result, (rw2, rh2), interpolation=cv2.INTER_LANCZOS4)
        rh, rw = rh2, rw2

    # Cap at 2048 px long edge — avoids excessive token cost
    if max(rh, rw) > 2048:
        sc = 2048 / max(rh, rw)
        result = cv2.resize(result, (int(rw * sc), int(rh * sc)),
                            interpolation=cv2.INTER_AREA)

    ok, buf = cv2.imencode(".jpg", result, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("cv2.imencode failed for vision encoding")
    return base64.b64encode(buf.tobytes()).decode("utf-8")


def _parse_vision_json(
    raw: str,
    orig_w: int,
    orig_h: int,
    frame_id: str,
    allow_diagram_bbox: bool = True,
) -> tuple[list[TextRegion], str]:
    """Parse a Vision API JSON string into (regions, raw_text)."""
    import json as _json

    try:
        data = _json.loads(raw)
    except Exception:
        logger.warning("Vision non-JSON frame=%s: %.120s", frame_id, raw)
        return [], ""

    raw_text = (data.get("raw_text") or "").strip()
    regions: list[TextRegion] = []
    texts: list[str] = []

    # Minimum model-reported confidence to accept a region (0–100 scale).
    # Regions where the model itself rates certainty below this threshold are
    # dropped — the model is essentially admitting it's guessing.
    _MIN_MODEL_CONFIDENCE = 60

    for r in data.get("regions", []):
        content_val = (r.get("content") or "").strip()
        if not content_val:
            continue

        # Drop regions the model flagged as low-confidence
        model_conf = r.get("confidence")
        if model_conf is not None:
            try:
                model_conf_int = int(model_conf)
            except (TypeError, ValueError):
                model_conf_int = 100  # treat missing/bad value as confident
            if model_conf_int < _MIN_MODEL_CONFIDENCE:
                logger.info(
                    "Vision frame=%s dropping low-confidence region (conf=%d): %r",
                    frame_id, model_conf_int, content_val[:60],
                )
                continue

        if _looks_hallucinated(content_val):
            logger.warning("Vision hallucination frame=%s: %r", frame_id, content_val[:80])
            continue
        rtype = r.get("type", "text")
        if rtype not in ("heading", "formula", "list", "text", "diagram"):
            rtype = "text"
        # Normalise model confidence to 0–1 for the TextRegion field
        norm_conf = (model_conf_int / 100.0) if model_conf is not None else 0.85

        # Diagram regions: use the model-reported bbox (0-1000 normalized space)
        # so the crop can be extracted later. Falls back to full-image bbox if
        # the model omitted it, gave malformed data, or this call can't supply
        # a reliable bbox (e.g. a horizontal-strip pass — see allow_diagram_bbox).
        bbox = [0.0, 0.0, float(orig_w), float(orig_h)]
        if rtype == "diagram" and allow_diagram_bbox:
            raw_bbox = r.get("bbox")
            if isinstance(raw_bbox, list) and len(raw_bbox) == 4:
                try:
                    nx1, ny1, nx2, ny2 = (float(v) for v in raw_bbox)
                    x1 = max(0.0, min(float(orig_w), nx1 / 1000.0 * orig_w))
                    y1 = max(0.0, min(float(orig_h), ny1 / 1000.0 * orig_h))
                    x2 = max(0.0, min(float(orig_w), nx2 / 1000.0 * orig_w))
                    y2 = max(0.0, min(float(orig_h), ny2 / 1000.0 * orig_h))
                    if x2 > x1 and y2 > y1:
                        bbox = [x1, y1, x2, y2]
                except (TypeError, ValueError):
                    pass

        regions.append(TextRegion(
            type=rtype,
            content=content_val,
            bbox=bbox,
            confidence=round(norm_conf, 4),
            engine="openai",
        ))
        # Include diagram content in texts — labels after "| Labels:" are
        # valuable curriculum signal for AI generation downstream.
        texts.append(content_val)

    if raw_text and _looks_hallucinated(raw_text):
        logger.warning("Vision raw_text hallucination frame=%s — dropped", frame_id)
        raw_text = ""

    if not regions and raw_text:
        regions.append(TextRegion(
            type="text",
            content=raw_text,
            bbox=[0.0, 0.0, float(orig_w), float(orig_h)],
            confidence=0.75,
            engine="openai",
        ))

    return regions, raw_text or "\n".join(texts)


# ---------------------------------------------------------------------------
# OpenAI Vision OCR — near + distant shot strategies
# ---------------------------------------------------------------------------

def _run_openai_vision(
    image_bgr: np.ndarray, frame_id: str, api_key: str, board_type: str = "chalkboard",
) -> tuple[list[TextRegion], float, str, bool]:
    """
    OCR using GPT-4o-mini vision with hallucination-safe quality gates.

    Quality gates (run in order before spending tokens on OCR):
      1. Local sharpness gate  — Laplacian variance on raw crop; rejects
         completely featureless/blank boards without any API call.
      2. API legibility check  — cheap single-word YES/NO call using
         _LEGIBILITY_CHECK_PROMPT at detail="low".  Catches blurry or
         too-distant images before the expensive OCR call runs.
         Applied to ALL shots, not just distant ones.
      3. Post-response sanity  — after OCR, if the source image was very
         small (distant shot) and the response word-count is suspiciously
         high, reject the result as likely hallucinated.

    Near shot  (board crop long-edge ≥ 600 px):
        Single OCR pass at detail="high".

    Distant shot  (board crop long-edge < 600 px):
        Pre-upscale to ≥ 1024 px short-edge + CLAHE + sharpen, then
        full-board pass + 3 horizontal strip passes (20 % overlap), merged.

    Returns (regions, mean_confidence, raw_text).  Empty on hard error or
    when quality gates determine the image is not readable.
    """
    import asyncio

    h, w = image_bgr.shape[:2]
    is_distant = max(h, w) < 600

    logger.info("Vision frame=%s input=%dx%d distant=%s", frame_id, w, h, is_distant)

    # ── Gate 1: Local sharpness / quality check (no API cost) ────────────────
    gray_orig = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY) if len(image_bgr.shape) == 3 \
        else image_bgr.copy()
    legible_local, reject_reason = _board_crop_is_legible(gray_orig)
    if not legible_local:
        logger.info(
            "Vision frame=%s SKIPPED (local quality gate: %s)",
            frame_id, reject_reason,
        )
        # api_ok=True: we didn't call the API; the board is genuinely blank/unreadable
        return [], 0.0, "", True

    # ── Pre-upscale for distant shots ─────────────────────────────────────────
    if is_distant:
        work = image_bgr.copy()
        wh, ww = h, w
        target_min = 1024
        while min(wh, ww) < target_min:
            step = min(2.0, target_min / max(min(wh, ww), 1))
            ww2, wh2 = int(ww * step), int(wh * step)
            work = cv2.resize(work, (ww2, wh2), interpolation=cv2.INTER_LANCZOS4)
            wh, ww = wh2, ww2
        # Enhance contrast + sharpness at the enlarged size
        g = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY) if len(work.shape) == 3 else work.copy()
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        g = clahe.apply(g)
        blurred = cv2.GaussianBlur(g, (0, 0), sigmaX=1.0)
        g = np.clip(cv2.addWeighted(g, 1.8, blurred, -0.8, 0), 0, 255).astype(np.uint8)
        work = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    else:
        work = image_bgr

    wh, ww = work.shape[:2]

    # ── Async helpers ─────────────────────────────────────────────────────────

    async def _ask_legibility(img: np.ndarray, prompt: str, tag: str) -> bool:
        try:
            b64_low = _encode_for_vision(img, target_min_dim=512)
        except Exception:
            return True  # encoding failed — assume legible, let OCR try
        try:
            from openai import AsyncOpenAI
        except ImportError:
            return True
        client = AsyncOpenAI(api_key=api_key)
        try:
            resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=5,
                temperature=0,
                timeout=15,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64_low}", "detail": "low"},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }],
            )
        except Exception as exc:
            logger.warning("Legibility check API error frame=%s: %s", frame_id, exc)
            return True  # assume legible on error — don't block OCR
        answer = (resp.choices[0].message.content or "").strip().upper()
        legible = answer.startswith("YES")
        logger.info(
            "Legibility check(%s) frame=%s answer=%r legible=%s",
            tag, frame_id, answer[:20], legible,
        )
        return legible

    async def _legibility_check(img: np.ndarray) -> bool:
        """
        Gate 2: cheap YES/NO API call to confirm the model can actually read
        text in this image.  Uses detail="low" and max_tokens=5.
        Returns True = proceed with OCR.  False = skip, return empty.

        Tries the prompt matching the session's board_type first, then falls
        back to the OTHER surface's prompt if that says NO. Needed because a
        "board" session can still have a printed poster/textbook page held up
        in frame (and vice versa) — each prompt asks specifically about ITS
        surface ("text written on a board" / "text on paper"), so a real,
        sharp, legible page still gets a correct-per-instructions NO from the
        wrong one alone. Confirmed 2026-09-15: a clearly readable printed
        poster next to a whiteboard failed both the crop AND full-frame
        board-prompt checks, killing OCR before extraction ever ran — the
        content was never actually blurry or unreadable, just not literally
        board writing. Only ever a second cheap YES/NO call, and only when
        the first one already said NO, so this never adds cost to the
        already-working case.
        """
        is_notebook = board_type == "notebook"
        primary = _LEGIBILITY_CHECK_PROMPT_NOTEBOOK if is_notebook else _LEGIBILITY_CHECK_PROMPT
        if await _ask_legibility(img, primary, "primary"):
            return True
        fallback = _LEGIBILITY_CHECK_PROMPT if is_notebook else _LEGIBILITY_CHECK_PROMPT_NOTEBOOK
        return await _ask_legibility(img, fallback, "fallback")

    async def _api_call(img: np.ndarray, tag: str) -> tuple[list[TextRegion], str, bool]:
        """One OCR Vision API call → (regions, raw_text, api_ok).
        api_ok=False means the API itself failed (quota/rate-limit/network).
        api_ok=True means the API responded — even if it returned empty content.
        """
        try:
            b64 = _encode_for_vision(img)
        except Exception as exc:
            logger.warning("Vision encode error frame=%s tag=%s: %s", frame_id, tag, exc)
            return [], "", False
        try:
            from openai import AsyncOpenAI
        except ImportError:
            return [], "", False
        client = AsyncOpenAI(api_key=api_key)
        try:
            resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=2000,
                temperature=0,   # deterministic — eliminates creative variation that causes hallucination
                timeout=60,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64}",
                                "detail": "high",
                            },
                        },
                        {"type": "text", "text": _DIRECT_EXTRACT_PROMPT},
                    ],
                }],
            )
        except Exception as exc:
            logger.warning("Vision API error frame=%s tag=%s: %s", frame_id, tag, exc)
            return [], "", False
        raw = _strip_fences(resp.choices[0].message.content or "")
        # Strip passes see a cropped slice of the image, so a bbox the model
        # reports there is relative to the slice, not the full frame — only
        # the "full" pass's bbox can be safely mapped back to original pixels.
        regs, txt = _parse_vision_json(raw, w, h, frame_id, allow_diagram_bbox=(tag == "full"))
        logger.info("Vision frame=%s tag=%s regions=%d", frame_id, tag, len(regs))
        return regs, txt, True

    async def _run_distant() -> tuple[list[TextRegion], float, str, bool]:
        """
        Legibility check → full-board pass + 3 horizontal strip passes, merged.
        Strips only run if the full-board pass already found at least one region
        (avoids 3 extra API calls on a truly empty/unreadable board).
        Returns 4-tuple (regions, conf, text, api_ok).
        """
        # Gate 2: legibility API check before spending tokens on OCR
        if not await _legibility_check(work):
            logger.info("Vision frame=%s distant: legibility check failed — returning empty", frame_id)
            return [], 0.0, "", True  # no API call made; board genuinely unreadable

        full_regs, full_text, full_api_ok = await _api_call(work, "full")

        if not full_api_ok:
            return [], 0.0, "", False  # API quota/error — propagate failure

        # Gate 3: post-response sanity check
        # If the source was very small and the model returned a lot of text,
        # it's almost certainly hallucinating generic educational content.
        orig_px = max(h, w)
        result_words = len(full_text.split()) if full_text else 0
        # Threshold: boards < 200px original long edge with > 30 words are suspicious
        if orig_px < 200 and result_words > 30:
            logger.warning(
                "Vision frame=%s distant: source tiny (%dpx) but %d words returned "
                "— likely hallucination, discarding",
                frame_id, orig_px, result_words,
            )
            return [], 0.0, "", True  # API responded fine; we intentionally discard

        # Only run strips if the full-board pass found something real
        if not full_regs:
            return [], 0.0, "", True  # API responded fine; board genuinely empty

        # Horizontal strips with 20% overlap
        overlap_px = int(wh * 0.20)
        third = wh // 3
        strips = [
            (0,                              third + overlap_px),
            (max(0, third - overlap_px),     2 * third + overlap_px),
            (max(0, 2 * third - overlap_px), wh),
        ]
        strip_regs: list[TextRegion] = []
        strip_texts: list[str] = []
        for i, (y1, y2) in enumerate(strips):
            sl = work[y1:y2, :]
            if sl.shape[0] < 30:
                continue
            s_regs, s_txt, s_ok = await _api_call(sl, f"strip{i}")
            if not s_ok:
                continue  # skip failed strip; full-board result still valid
            strip_regs.extend(s_regs)
            if s_txt:
                strip_texts.append(s_txt)

        # Merge: keep full-board results; add strip results not yet captured
        seen: list[str] = [r.content for r in full_regs if r.content]
        merged = list(full_regs)
        for r in strip_regs:
            if not r.content:
                continue
            tn = set(r.content.lower().split())
            dup = any(
                len(tn & set(s.lower().split())) /
                max(len(tn | set(s.lower().split())), 1) >= 0.75
                for s in seen
            )
            if not dup:
                merged.append(r)
                seen.append(r.content)

        merged_text = full_text
        for t in strip_texts:
            if t and t not in merged_text:
                merged_text = (merged_text + "\n" + t).strip() if merged_text else t

        conf = 0.85 if merged else 0.0
        logger.info(
            "Vision frame=%s distant merge: full=%d strips=%d total=%d",
            frame_id, len(full_regs), len(strip_regs), len(merged),
        )
        return merged, conf, merged_text, True

    async def _run_near() -> tuple[list[TextRegion], float, str, bool]:
        """Legibility check → single OCR pass for nearby shots."""
        if not await _legibility_check(work):
            logger.info("Vision frame=%s near: legibility check failed — returning empty", frame_id)
            return [], 0.0, "", True
        regs, txt, api_ok = await _api_call(work, "full")
        return regs, (0.85 if regs else 0.0), txt, api_ok

    async def _run() -> tuple[list[TextRegion], float, str, bool]:
        return await (_run_distant() if is_distant else _run_near())

    # ── Async-to-sync bridge ──────────────────────────────────────────────────
    try:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is not None and running_loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                regions, conf, raw_text, api_ok = pool.submit(asyncio.run, _run()).result(timeout=180)
        else:
            regions, conf, raw_text, api_ok = asyncio.run(_run())

        logger.info(
            "Vision frame=%s FINAL regions=%d conf=%.2f text_len=%d api_ok=%s",
            frame_id, len(regions), conf, len(raw_text), api_ok,
        )
        return regions, conf, raw_text, api_ok

    except Exception as exc:
        logger.warning("OpenAI Vision runner error frame=%s: %s", frame_id, exc)
        return [], 0.0, "", False


# ---------------------------------------------------------------------------
# Public OCR entry point
# ---------------------------------------------------------------------------

def run_ocr(
    image_bgr: np.ndarray,
    frame_id: str,
    board_type: str = "chalkboard",
    original_bgr: np.ndarray | None = None,
) -> FrameOCRResult:
    """
    Run OCR on a frame and return a structured FrameOCRResult.

    Engine priority:
      1. OpenAI Vision (GPT-4o-mini) — when OPENAI_API_KEY is set; best quality
      2. PaddleOCR — when installed; good for printed/typed board text
      3. Tesseract — fallback; works without ML dependencies

    Args:
        image_bgr:    Board-type-preprocessed BGR (for PaddleOCR).
        frame_id:     UUID string for this frame.
        board_type:   "chalkboard" | "whiteboard" | "smartboard".
        original_bgr: Original perspective-corrected BGR; used by Tesseract
                      and OpenAI Vision (avoids board-inversion artefacts).
    """
    t_start = time.monotonic()

    # ---- OpenAI Vision (highest priority when API key present) ----
    try:
        from app.config import get_settings
        _settings = get_settings()
        openai_key = _settings.openai_api_key
    except Exception:
        openai_key = ""

    if openai_key:
        vision_input = original_bgr if original_bgr is not None else image_bgr
        logger.info("OCR frame=%s using OpenAI Vision", frame_id)
        ov_regions, ov_conf, ov_text, ov_api_ok = _run_openai_vision(vision_input, frame_id, openai_key, board_type)
        processing_ms = int((time.monotonic() - t_start) * 1000)
        if ov_regions or ov_text:
            logger.info("OCR frame=%s engine=openai conf=%.3f regions=%d time=%dms",
                        frame_id, ov_conf, len(ov_regions), processing_ms)
            return FrameOCRResult(
                frame_id=frame_id,
                engine_used="openai",
                confidence=round(ov_conf, 4),
                regions=ov_regions,
                raw_text=ov_text,
                processing_ms=processing_ms,
            )
        if ov_api_ok:
            # Vision API responded successfully — model genuinely found no content.
            # Board is empty or unreadable; local engines would only hallucinate.
            logger.info(
                "OCR frame=%s OpenAI Vision found no content (board likely empty) "
                "— returning empty (time=%dms)",
                frame_id, processing_ms,
            )
            return FrameOCRResult(
                frame_id=frame_id,
                engine_used="openai",
                confidence=0.0,
                regions=[],
                raw_text="",
                processing_ms=processing_ms,
            )
        # Vision API failed (quota exceeded, rate limit, network error).
        # Fall through to PaddleOCR / Tesseract.
        logger.warning(
            "OCR frame=%s OpenAI Vision API failed — falling back to local OCR engines",
            frame_id,
        )

    paddle_ok = _get_paddle() is not None
    tess_ok = _is_tesseract_available()

    if not paddle_ok and not tess_ok:
        return FrameOCRResult(
            frame_id=frame_id,
            engine_used="none",
            confidence=0.0,
            regions=[],
            raw_text="",
            error="No OCR engine available. Install paddleocr or pytesseract.",
            processing_ms=int((time.monotonic() - t_start) * 1000),
        )

    # Tesseract receives the original image (not the board-inverted one) when available
    tess_input = original_bgr if original_bgr is not None else image_bgr

    # ---- Primary: PaddleOCR (uses board-preprocessed image) ----
    paddle_regions, paddle_conf = _run_paddle(image_bgr, frame_id) if paddle_ok else ([], 0.0)

    # ---- Routing logic ----
    final_regions: list[TextRegion]
    final_conf: float
    engine_used: str
    needs_review = False

    if paddle_conf >= CONF_HIGH:
        # High confidence — PaddleOCR wins
        final_regions = paddle_regions
        final_conf = paddle_conf
        engine_used = "paddleocr"

    elif CONF_LOW <= paddle_conf < CONF_HIGH and tess_ok:
        # Medium confidence — run Tesseract on original, pick better result
        tess_regions, tess_conf, _ = _run_tesseract(tess_input, frame_id)
        if tess_conf > paddle_conf:
            final_regions = tess_regions
            final_conf = tess_conf
            engine_used = "tesseract"
        else:
            final_regions = paddle_regions
            final_conf = paddle_conf
            engine_used = "paddleocr"

    else:
        # Low confidence or PaddleOCR not available — use best available + flag
        needs_review = True
        if tess_ok:
            tess_regions, tess_conf, _ = _run_tesseract(tess_input, frame_id)
            if tess_conf > paddle_conf:
                final_regions = tess_regions
                final_conf = tess_conf
                engine_used = "tesseract"
            else:
                final_regions = paddle_regions
                final_conf = paddle_conf
                engine_used = "paddleocr" if paddle_ok else "tesseract"
        else:
            final_regions = paddle_regions
            final_conf = paddle_conf
            engine_used = "paddleocr"

    # Build plain raw_text from non-diagram regions
    raw_text = "\n".join(
        r.content for r in final_regions
        if r.content and r.type != "diagram"
    )

    processing_ms = int((time.monotonic() - t_start) * 1000)
    logger.info(
        "OCR frame=%s engine=%s conf=%.3f regions=%d time=%dms review=%s",
        frame_id, engine_used, final_conf, len(final_regions), processing_ms, needs_review,
    )

    return FrameOCRResult(
        frame_id=frame_id,
        engine_used=engine_used,
        confidence=round(final_conf, 4),
        regions=final_regions,
        raw_text=raw_text,
        needs_review=needs_review,
        processing_ms=processing_ms,
    )


# ---------------------------------------------------------------------------
# Diagram cropping + correctness validation
# ---------------------------------------------------------------------------
#
# When the Vision OCR pass detects a "diagram" region with a real bounding box
# (see the "bbox" field added to _DIRECT_EXTRACT_PROMPT above), crop it out of
# the full-resolution frame and ask a subject-matter-expert vision prompt to
# check it for factual/technical correctness. Results are attached to
# FrameOCRResult.diagrams and surfaced in the Notes output's board_diagrams
# section so a teacher can see the actual drawing plus any errors flagged.
# ---------------------------------------------------------------------------

_DIAGRAM_VALIDATION_PROMPT_TMPL = (
    "You are a {subject} subject-matter expert reviewing a diagram drawn on a classroom "
    "board for {grade} students in India.\n\n"
    "The board's OCR system read this description of the diagram: \"{description}\"\n\n"
    "STEP 1 — visibility check (do this first, before anything else):\n"
    "  The crop was cut out automatically and may have missed the actual diagram — it might "
    "  show only blank board, a glare/reflection, board edge/frame, or unrelated content with "
    "  no real diagram in it.\n"
    "  If you cannot clearly see a diagram matching the description above, respond with EXACTLY:\n"
    "  {{\"diagram_visible\": false, \"diagram_type\": \"none\", \"is_correct\": null, \"errors\": []}}\n"
    "  Do NOT guess is_correct=true just because you can't find anything wrong — if there's "
    "  nothing to check, say so via diagram_visible=false instead.\n\n"
    "STEP 2 — only if a real diagram IS clearly visible:\n"
    "  1. Identify what it depicts in a short label (e.g. 'human heart cross-section').\n"
    "  2. Check it for factual or technical correctness appropriate to the {grade} curriculum: "
    "wrong or swapped labels, mislabeled parts, incorrect structure, wrong direction of "
    "arrows/flow, incorrect values, or anything a subject teacher would mark wrong.\n"
    "  3. Only flag something as an error if you can actually verify it from what's visible in "
    "the image — never invent an error you cannot see evidence for.\n"
    "  4. If everything shown is correct, set is_correct=true and leave errors empty.\n\n"
    "Return ONLY this JSON (no markdown fences, no explanation):\n"
    "{{\"diagram_visible\": true, \"diagram_type\": \"short label\", \"is_correct\": true, "
    "\"errors\": [{{\"issue\": \"what is wrong\", \"correct_version\": \"what it should be instead\"}}]}}"
)


def _validate_diagram_vision(
    crop_bgr: np.ndarray,
    description: str,
    subject: str,
    grade: str,
    api_key: str,
    frame_id: str,
) -> dict:
    """
    Ask GPT-4o-mini vision whether a cropped board diagram is factually/
    technically correct. Returns a dict with is_correct=None and
    unvalidated=True when the API call fails, rather than assuming correctness.
    """
    import asyncio
    import json as _json

    async def _call() -> dict | None:
        try:
            b64 = _encode_for_vision(crop_bgr, target_min_dim=512)
        except Exception:
            return None
        try:
            from openai import AsyncOpenAI
        except ImportError:
            return None
        client = AsyncOpenAI(api_key=api_key)
        prompt = _DIAGRAM_VALIDATION_PROMPT_TMPL.format(
            subject=subject, grade=grade, description=description[:300],
        )
        try:
            resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=500,
                temperature=0,
                timeout=45,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }],
            )
        except Exception as exc:
            logger.warning("Diagram validation API error frame=%s: %s", frame_id, exc)
            return None
        raw = _strip_fences(resp.choices[0].message.content or "")
        try:
            data = _json.loads(raw)
        except Exception:
            logger.warning("Diagram validation non-JSON frame=%s: %.150s", frame_id, raw)
            return None
        # The model itself reports when the crop didn't actually contain a
        # visible diagram (blank board, glare, wrong crop) — trust that over
        # guessing correctness on nothing.
        if data.get("diagram_visible") is False:
            logger.info("Diagram validation frame=%s: model reports no diagram visible in crop", frame_id)
            return {
                "diagram_type": "diagram", "is_correct": None, "errors": [],
                "unvalidated": True, "reason": "crop_unclear",
            }

        raw_errors = data.get("errors") or []
        clean_errors = [
            {
                "issue": str(e.get("issue", "")).strip(),
                "correct_version": str(e.get("correct_version", "")).strip(),
            }
            for e in raw_errors if isinstance(e, dict) and e.get("issue")
        ]
        return {
            "diagram_type": str(data.get("diagram_type", "")).strip() or "diagram",
            "is_correct": False if clean_errors else bool(data.get("is_correct", True)),
            "errors": clean_errors,
        }

    try:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is not None and running_loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(asyncio.run, _call()).result(timeout=60)
        else:
            result = asyncio.run(_call())
    except Exception as exc:
        logger.warning("Diagram validation bridge error frame=%s: %s", frame_id, exc)
        result = None

    if result is not None:
        return result
    return {"diagram_type": "diagram", "is_correct": None, "errors": [], "unvalidated": True}


def crop_and_validate_diagrams(
    regions: list[TextRegion],
    working_bgr: np.ndarray,
    subject: str,
    grade: str,
    api_key: str,
    frame_id: str,
) -> list[dict]:
    """
    For each diagram region with a real (non-full-image) bbox, crop it out of
    `working_bgr` and run correctness validation. Regions whose bbox fell back
    to the full-image sentinel (no real coordinates from the model) are
    skipped — nothing usable to crop.

    Returns a list of {"description": str, "image_bytes": bytes, "validation": dict}.
    """
    h, w = working_bgr.shape[:2]
    out: list[dict] = []

    for region in regions:
        if region.type != "diagram" or not region.content:
            continue
        x1, y1, x2, y2 = region.bbox
        # Full-image sentinel bbox → no real crop coordinates were available.
        if x1 <= 1.0 and y1 <= 1.0 and x2 >= w - 1.0 and y2 >= h - 1.0:
            continue

        # Vision LLMs are imprecise at spatial grounding for line art — a
        # reported box often clips most of the actual drawing (e.g. catching
        # only a label and a stroke, not the full shape). Rather than trust
        # the box's size verbatim, expand generously around its own center
        # with a sane minimum (35% of the frame's shorter dimension) so the
        # crop reliably shows the whole diagram, not just a corner of it.
        box_w, box_h = x2 - x1, y2 - y1
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        min_dim = min(w, h) * 0.35
        half_w = max(box_w, min_dim) * 0.60  # includes ~20% padding beyond the box/minimum
        half_h = max(box_h, min_dim) * 0.60
        cx1 = max(0, int(cx - half_w))
        cy1 = max(0, int(cy - half_h))
        cx2 = min(w, int(cx + half_w))
        cy2 = min(h, int(cy + half_h))
        if cx2 - cx1 < 20 or cy2 - cy1 < 20:
            continue

        crop = working_bgr[cy1:cy2, cx1:cx2]
        ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            continue

        validation = _validate_diagram_vision(crop, region.content, subject, grade, api_key, frame_id)
        out.append({
            "description": region.content,
            "image_bytes": buf.tobytes(),
            "validation": validation,
        })

    return out
