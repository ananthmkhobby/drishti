"""
Vision + deterministic-checking primitives for ThinkStep guided practice.

Gate A (capture quality)   -> reuses image_preprocessor.validate_frame
Gate B/C (step extraction) -> _run_step_extraction_vision (OpenAI vision)
Gate D (deterministic)     -> check_arithmetic_step (sympy)

Kept separate from app/ocr/ocr_engine.py: that module transcribes an entire
board for lecture capture; this one extracts ordered problem-solving steps
for ONE specific question and never needs the board-detection/diagram-crop
machinery lecture capture requires.
"""
from __future__ import annotations

import base64
import json
import logging
import re

import cv2
import numpy as np

from app.ocr.image_preprocessor import ValidationResult, validate_frame

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Gate A — capture quality (thin re-export so callers only import this module)
# ---------------------------------------------------------------------------

def check_capture_quality(image_bgr: np.ndarray) -> ValidationResult:
    return validate_frame(image_bgr)


# ---------------------------------------------------------------------------
# Orientation correction — a student holding the device sideways/upside-down
# relative to the page is a common real capture mistake (reported
# 2026-09-24: a photo tilted ~45/90 degrees wasn't being read correctly).
# Run before capture-quality checks or any vision call, on BOTH the graded-
# attempt path (process_attempt) and the AI Tutor's own frame (tutor_turn).
# ---------------------------------------------------------------------------

def auto_orient(image_bgr: np.ndarray) -> np.ndarray:
    """
    Corrects a photo shot rotated a cardinal 90/180/270 degrees from upright,
    using Tesseract's OSD (orientation & script detection) on the text
    itself — the same signal a person uses to tell a sideways page from a
    right-side-up one. Requires the OPTIONAL `pytesseract`/`Pillow` deps
    (see pyproject.toml) and the `tesseract-ocr` system binary; on any
    failure (not installed, no OSD language data, too little text to judge
    from) this is a no-op — returns the image unchanged rather than
    blocking the pipeline over a best-effort correction.

    Deliberately narrow scope: only the four cardinal rotations are
    corrected. An arbitrary in-between skew (a page photographed at a
    genuine angle, not a ~90-degree-multiple rotation) is NOT deskewed
    here — reliably estimating a continuous skew angle from a single
    handwritten photo (vs. a scanned document with clean margins) is a
    substantially harder, higher-risk problem, and a wrong correction there
    would make the photo worse, not better. GPT-4o's vision reading of a
    moderately skewed-but-right-side-up page is usually still workable
    without it.
    """
    try:
        import pytesseract
        from PIL import Image

        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        osd = pytesseract.image_to_osd(Image.fromarray(rgb), output_type=pytesseract.Output.DICT)
        rotate_deg = int(osd.get("rotate", 0) or 0) % 360
        conf = float(osd.get("orientation_conf", 0) or 0)
    except Exception as exc:
        logger.info("auto_orient: OSD unavailable or failed (%s) — leaving image as-is", exc)
        return image_bgr

    # Low confidence (near-blank page, too little/unclear text) — don't
    # guess; a wrong flip on a legible-but-hard page is worse than leaving
    # a genuinely upright photo untouched.
    if rotate_deg == 0 or conf < 1.0:
        return image_bgr

    logger.info("auto_orient: correcting a %d-degree rotation (OSD confidence %.1f)", rotate_deg, conf)
    # OSD's "rotate" is the angle to rotate the image CLOCKWISE to correct
    # it (empirically verified against known rotations, not assumed).
    if rotate_deg == 90:
        return cv2.rotate(image_bgr, cv2.ROTATE_90_CLOCKWISE)
    if rotate_deg == 180:
        return cv2.rotate(image_bgr, cv2.ROTATE_180)
    if rotate_deg == 270:
        return cv2.rotate(image_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return image_bgr


# ---------------------------------------------------------------------------
# Camera-mount correction — a DETERMINISTIC counterpart to auto_orient()
# above, for a specific, known physical setup: a camera fixed above the
# desk (e.g. clipped just below or above a laptop) looking straight DOWN
# at the notebook, rather than a normal front-facing camera propped up to
# face it. auto_orient()'s Tesseract-OSD guess is best-effort and can miss
# on a page with little text or low OSD confidence; a teacher who knows
# their station is desk-mounted can instead say so once (PracticeStation.
# camera_mount = "desk") and get the SAME correction applied every single
# capture, no guessing involved. The two are independent — apply_mount_
# correction, when its station is in desk mode, runs BEFORE auto_orient,
# since auto_orient's OSD reads more reliably once the gross rotation is
# already undone.
# ---------------------------------------------------------------------------

def apply_mount_correction(image_bgr: np.ndarray, camera_mount: str) -> np.ndarray:
    """
    "desk" mount: a plain 180° rotation, no mirror/flip — a ROTATION (turn
    the photo upside down) reads correctly once turned back the right way
    up, unlike a MIRROR (reflection), which never reads correctly no
    matter how you turn it. The first attempt at this (90° + a horizontal
    mirror) was wrong — corrected 2026-09-24 after live testing on the
    actual overhead-mounted setup confirmed a plain 180° is what's
    actually needed. (180° is direction-independent — rotating clockwise
    or counterclockwise by 180° lands on the identical result — so there's
    no direction ambiguity left to get wrong here, unlike the 90° case.)
    Any other value (including the default "front") is a no-op.
    """
    if camera_mount != "desk":
        return image_bgr
    return cv2.rotate(image_bgr, cv2.ROTATE_180)


# ---------------------------------------------------------------------------
# Bbox refinement — GPT-4o's own bbox estimate for "where on the page is
# this step" is frequently imprecise (vision-language models are good at
# WHAT is in an image, much weaker at exactly WHERE — a well-documented
# limitation, not a bug in the prompt), which is what actually produces the
# "marking isn't aligned with the writing" complaint (reported 2026-09-24).
# Ink-vs-paper contrast is a strong, reliable signal classical CV handles
# far better than an LLM's spatial guess, so snap the model's rough box to
# the actual dense-ink region found within a generous search window around
# it, instead of trusting the raw coordinates outright.
# ---------------------------------------------------------------------------

def refine_bbox(image_bgr: np.ndarray, bbox: list[float]) -> list[float]:
    """
    Tightens a [x1,y1,x2,y2] bbox (0-1000 normalized space) to the actual
    ink extent found near it. Falls back to the original bbox untouched on
    any failure or when nothing ink-like is found in the search window —
    this is a refinement, never a replacement the caller can't trust.
    """
    try:
        h, w = image_bgr.shape[:2]
        x1, y1, x2, y2 = bbox
        # Pixel-space box from the normalized coordinates.
        px1, py1 = x1 / 1000.0 * w, y1 / 1000.0 * h
        px2, py2 = x2 / 1000.0 * w, y2 / 1000.0 * h
        bw, bh = max(px2 - px1, 1.0), max(py2 - py1, 1.0)

        # Generous search window — the box only needs to be roughly right
        # for this to recover the real extent; padding much beyond the
        # model's guess would risk snapping onto a neighboring line instead.
        pad_x, pad_y = bw * 0.6, bh * 0.6
        sx1 = max(0, int(px1 - pad_x))
        sy1 = max(0, int(py1 - pad_y))
        sx2 = min(w, int(px2 + pad_x))
        sy2 = min(h, int(py2 + pad_y))
        if sx2 - sx1 < 4 or sy2 - sy1 < 4:
            return bbox

        window = image_bgr[sy1:sy2, sx1:sx2]
        gray = cv2.cvtColor(window, cv2.COLOR_BGR2GRAY) if window.ndim == 3 else window
        # Otsu picks the ink/background split automatically — works for
        # both dark pen on light paper and (after the same invert either
        # thresholding polarity would find) a photographed light-on-dark
        # crop; try the more common dark-ink-on-light-page polarity first.
        _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        ink_fraction = float(np.count_nonzero(mask)) / mask.size
        # A sane ink fraction for a line of handwriting in a padded window —
        # far outside this range means Otsu picked up the whole background
        # (near-0) or the whole window is dark (near-1, e.g. a shadow), not
        # actual text, so trust the model's original box instead.
        if ink_fraction < 0.01 or ink_fraction > 0.6:
            return bbox

        ys, xs = np.nonzero(mask)
        rx1, rx2 = int(xs.min()), int(xs.max())
        ry1, ry2 = int(ys.min()), int(ys.max())

        # Back to full-image pixel space, then to the normalized 0-1000
        # space the frontend already expects.
        fx1, fx2 = sx1 + rx1, sx1 + rx2
        fy1, fy2 = sy1 + ry1, sy1 + ry2
        return [
            round(fx1 / w * 1000, 1), round(fy1 / h * 1000, 1),
            round(fx2 / w * 1000, 1), round(fy2 / h * 1000, 1),
        ]
    except Exception as exc:
        logger.info("refine_bbox: failed (%s) — keeping the model's original box", exc)
        return bbox


# ---------------------------------------------------------------------------
# Column-level bbox targeting — given a step's already-detected region
# (typically already passed through refine_bbox above) PLUS a semantic
# place-value column name from Gate D/E-F's column_hint (see
# check_arithmetic_step/check_bare_expression_equality), finds the actual
# digit within that region for that specific column, instead of circling
# the whole line for a carry/borrow mistake that's really about one digit.
#
# Deliberately does NOT ask the vision model for per-digit coordinates —
# that just moves the "LLMs are weak at precise spatial localization"
# problem to a finer grain instead of solving it. The model only ever
# names WHICH column (a text/reasoning task it's actually reliable at);
# this function is what turns that into a real pixel position, the same
# division of labor refine_bbox already uses.
# ---------------------------------------------------------------------------

def _find_ink_column_runs(mask: np.ndarray, min_gap_px: int = 3, min_width_px: int = 3) -> list[tuple[int, int]]:
    """
    Vertical-projection digit segmentation: returns [(x_start, x_end), ...]
    left to right, one per contiguous run of ink-bearing columns in `mask`
    (a binary ink-vs-background image, ink = nonzero). Runs separated by
    fewer than `min_gap_px` blank columns are merged — avoids splitting one
    digit's own stroke gaps (the two humps of an '8', a dotted character)
    into multiple false columns. Runs narrower than `min_width_px` are
    dropped as noise (a stray speck, not a real digit).
    """
    col_has_ink = mask.any(axis=0)
    runs: list[tuple[int, int]] = []
    start = None
    gap = 0
    last_ink_x = -1
    for x, has_ink in enumerate(col_has_ink):
        if has_ink:
            if start is None:
                start = x
            last_ink_x = x
            gap = 0
        elif start is not None:
            gap += 1
            if gap > min_gap_px:
                runs.append((start, last_ink_x))
                start = None
    if start is not None:
        runs.append((start, last_ink_x))
    return [(s, e) for s, e in runs if (e - s + 1) >= min_width_px]


def locate_arithmetic_column(image_bgr: np.ndarray, step_bbox: list[float], column: str) -> list[float] | None:
    """
    Given a step's region (bbox, 0-1000 normalized) known to be a single
    line of column-aligned digits (an addition/subtraction row), finds the
    specific digit cluster for the named place-value `column`
    ("ones"/"tens"/"hundreds"/"thousands"/"ten_thousands" — see
    _PLACE_VALUE_NAMES) and returns ITS bbox.

    Digits are assumed read right-to-left starting from "ones" — standard
    place-value order for a plain integer line. Decimal points aren't
    handled in this version (a "tenths"/"hundredths" column always
    returns None here — the semantic reasoning can still name them, just
    without a precise pixel target yet); reliably telling a decimal point
    apart from a stray ink speck via a simple projection profile isn't
    safe enough to guess at without risking a wrong pixel target, so this
    stays conservative and lets the caller fall back to the step's whole
    bbox instead.

    Returns None (caller should fall back to the step's own bbox) whenever
    this can't locate the column with real confidence — too few digit
    clusters detected, the requested column is further left than what was
    actually found, or any processing failure.
    """
    if column not in _PLACE_VALUE_NAMES:
        return None
    try:
        h, w = image_bgr.shape[:2]
        x1, y1, x2, y2 = step_bbox
        px1, py1 = x1 / 1000.0 * w, y1 / 1000.0 * h
        px2, py2 = x2 / 1000.0 * w, y2 / 1000.0 * h
        bw, bh = max(px2 - px1, 1.0), max(py2 - py1, 1.0)

        # Tighter padding than refine_bbox's general search window — this
        # already trusts step_bbox to be a good estimate of the LINE (it's
        # typically already been through refine_bbox), the job here is
        # just splitting that line into its individual digits.
        pad_x, pad_y = bw * 0.1, bh * 0.2
        sx1 = max(0, int(px1 - pad_x))
        sy1 = max(0, int(py1 - pad_y))
        sx2 = min(w, int(px2 + pad_x))
        sy2 = min(h, int(py2 + pad_y))
        if sx2 - sx1 < 6 or sy2 - sy1 < 6:
            return None

        window = image_bgr[sy1:sy2, sx1:sx2]
        gray = cv2.cvtColor(window, cv2.COLOR_BGR2GRAY) if window.ndim == 3 else window
        _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        ink_fraction = float(np.count_nonzero(mask)) / mask.size
        if ink_fraction < 0.01 or ink_fraction > 0.6:
            return None  # same sanity range as refine_bbox — not actually text

        runs = _find_ink_column_runs(mask)
        if len(runs) < 2:
            return None  # not enough separated digits to confidently pick one out

        place_idx = _PLACE_VALUE_NAMES.index(column)
        if place_idx >= len(runs):
            return None  # this column doesn't exist in what was actually detected

        # Rightmost run = ones, next-to-rightmost = tens, etc.
        gx1, gx2 = runs[-(place_idx + 1)]
        col_mask = mask[:, gx1:gx2 + 1]
        rows_with_ink = np.where(col_mask.any(axis=1))[0]
        if len(rows_with_ink) == 0:
            return None
        gy1, gy2 = int(rows_with_ink.min()), int(rows_with_ink.max())

        fx1, fx2 = sx1 + gx1, sx1 + gx2
        fy1, fy2 = sy1 + gy1, sy1 + gy2
        return [
            round(fx1 / w * 1000, 1), round(fy1 / h * 1000, 1),
            round(fx2 / w * 1000, 1), round(fy2 / h * 1000, 1),
        ]
    except Exception as exc:
        logger.info("locate_arithmetic_column: failed (%s) — falling back to the step's own bbox", exc)
        return None


# ---------------------------------------------------------------------------
# Image encoding for the Vision API — public (not module-private) since
# practice_service.tutor_turn() reuses this exact resize/quality convention
# for the AI Tutor's own vision calls, so every vision call in this app
# encodes images the same way rather than drifting per call site.
# ---------------------------------------------------------------------------

def encode_for_vision(img: np.ndarray, target_min_dim: int = 1024) -> str:
    h, w = img.shape[:2]
    result = img.copy()
    rh, rw = h, w
    while min(rh, rw) < target_min_dim:
        step = min(2.0, target_min_dim / max(min(rh, rw), 1))
        rw2, rh2 = int(rw * step), int(rh * step)
        result = cv2.resize(result, (rw2, rh2), interpolation=cv2.INTER_LANCZOS4)
        rh, rw = rh2, rw2
    if max(rh, rw) > 2048:
        sc = 2048 / max(rh, rw)
        result = cv2.resize(result, (int(rw * sc), int(rh * sc)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", result, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("cv2.imencode failed for vision encoding")
    return base64.b64encode(buf.tobytes()).decode("utf-8")


# ---------------------------------------------------------------------------
# Gates B/C — step extraction (OpenAI vision)
# ---------------------------------------------------------------------------

_STEP_EXTRACTION_PROMPT = """You are reading a student's handwritten work on ONE \
specific practice question, photographed from a notebook page. The question is:

"{question_text}"

Extract the student's written steps IN THE ORDER THEY APPEAR on the page, \
preserving spatial/top-to-bottom order. This works for any subject — math \
working, a labeled diagram, a written explanation, a chemical equation, \
whatever the student actually wrote.

Output ONLY a JSON object of this shape:
{{
  "steps": [
    {{"text": "<transcribed step, verbatim>", "bbox": [x1,y1,x2,y2], "confidence": <0-100 int>}}
  ],
  "overall_confidence": <0-100 int>,
  "empty_reason": "<"none" if steps were found, otherwise "illegible" | "off_topic" | "blank">"
}}

bbox is [x1,y1,x2,y2] in a 0-1000 normalized coordinate space (top-left origin).
RULES:
- Confidence reflects YOUR certainty READING the text/handwriting — a page that \
is perfectly sharp and well-lit should get HIGH confidence even if it turns out \
to be the wrong page; legibility and topical relevance are different things and \
must not be conflated into one low number.
- Transcribe mathematical/scientific notation EXACTLY as written, preserving the \
distinction between visually similar constructs — a superscript exponent (x²) is \
NOT the same as a subscript (x₂) or a multiplication (x·2); an integral sign, a \
summation, a partial-derivative ∂, a vector arrow, a Δ, and a → are all distinct \
symbols with different meanings and must not be normalized into plain text that \
loses that distinction. Where the handwritten form is genuinely ambiguous even at \
full resolution, transcribe your best reading and let a LOWER per-step confidence \
carry that uncertainty — don't silently pick whichever reading seems more \
"textbook-plausible" if the ink itself doesn't clearly support it.
- Never invent steps that aren't actually written on the page.
- Do not solve the question yourself or add any step the student didn't write.
- If steps is empty, "empty_reason" MUST explain why, distinguishing three \
different cases a downstream system needs to react to differently:
  - "illegible": the photo itself is blurry, dark, glare-washed or too distant \
to read — a RECAPTURE would fix this.
  - "off_topic": the page is clearly legible but is not the student working on \
THIS question — e.g. a different topic, an unrelated textbook page, or a \
reference page rather than the student's own attempt. A recapture of the SAME \
page won't fix this; the student needs to be looking at the right page/question.
  - "blank": the page is legible and clearly blank or has no attempt started yet.
- Output ONLY the JSON object, no markdown fences, no other text."""

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


async def extract_steps(
    image_bgr: np.ndarray,
    question_text: str,
    api_key: str,
    timeout_sec: int = 30,
) -> dict:
    """
    Returns {"steps": [{"text","bbox","confidence"}...], "overall_confidence": float 0-1}
    On any failure returns {"steps": [], "overall_confidence": 0.0, "error": "..."}
    — caller (Gate B) treats overall_confidence 0 the same as "recapture needed",
    never as "student wrote nothing wrong".
    """
    if not api_key:
        return {"steps": [], "overall_confidence": 0.0, "empty_reason": "error", "error": "no_api_key"}

    try:
        from openai import AsyncOpenAI
    except ImportError:
        return {"steps": [], "overall_confidence": 0.0, "empty_reason": "error", "error": "openai_client_unavailable"}

    try:
        b64 = encode_for_vision(image_bgr)
    except Exception as exc:
        logger.warning("Practice step extraction: encode failed: %s", exc)
        return {"steps": [], "overall_confidence": 0.0, "empty_reason": "error", "error": "encode_failed"}

    client = AsyncOpenAI(api_key=api_key)
    prompt = _STEP_EXTRACTION_PROMPT.format(question_text=question_text[:1000])

    try:
        resp = await client.chat.completions.create(
            model="gpt-4o",
            temperature=0,
            timeout=timeout_sec,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        # "detail": "high" is not optional here — without it
                        # the API defaults to "auto", which can silently fall
                        # back to a much lower effective resolution regardless
                        # of how sharp the source photo actually is. That's a
                        # near-perfect match for "clear photo, reported
                        # illegible, wrong transcription" (reported
                        # 2026-09-19) — this is the SAME setting the main
                        # board-OCR path (ocr_engine.py) already uses for the
                        # same reason (reading handwritten text accurately);
                        # this call was just missing it.
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"}},
                    ],
                }
            ],
        )
        content = resp.choices[0].message.content or ""
    except Exception as exc:
        logger.warning("Practice step extraction: vision call failed: %s", exc)
        return {"steps": [], "overall_confidence": 0.0, "empty_reason": "error", "error": str(exc)}

    match = _JSON_BLOCK.search(content)
    if not match:
        return {"steps": [], "overall_confidence": 0.0, "empty_reason": "error", "error": "no_json_in_response"}

    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return {"steps": [], "overall_confidence": 0.0, "empty_reason": "error", "error": "invalid_json"}

    raw_steps = data.get("steps") or []
    steps = []
    for s in raw_steps:
        if not isinstance(s, dict) or not s.get("text"):
            continue
        conf = s.get("confidence", 0)
        try:
            conf = max(0.0, min(1.0, float(conf) / 100.0))
        except (TypeError, ValueError):
            conf = 0.5
        bbox = s.get("bbox")
        if not (isinstance(bbox, list) and len(bbox) == 4):
            bbox = None
        steps.append({"text": str(s["text"]).strip(), "bbox": bbox, "confidence": round(conf, 3)})

    overall = data.get("overall_confidence", 0)
    try:
        overall = max(0.0, min(1.0, float(overall) / 100.0))
    except (TypeError, ValueError):
        overall = (sum(s["confidence"] for s in steps) / len(steps)) if steps else 0.0

    empty_reason = data.get("empty_reason", "none")
    if empty_reason not in ("none", "illegible", "off_topic", "blank", "error"):
        empty_reason = "illegible"  # unrecognized value — fail toward "ask for a recapture", not silence

    return {"steps": steps, "overall_confidence": round(overall, 3), "empty_reason": empty_reason}


# ---------------------------------------------------------------------------
# Gates B/C, spoken-answer variant — step extraction from a transcript
# ---------------------------------------------------------------------------
# For theory/conceptual questions answered out loud (STT) instead of
# photographed — same downstream shape as extract_steps ({"steps": [...],
# "overall_confidence", "empty_reason"}) so Gates D-H don't need to know
# which input type produced it. No bbox (there's no image to point at), and
# no vision call — this is a plain text LLM call, cheaper and faster than
# the vision path it substitutes for.

_TEXT_STEP_EXTRACTION_PROMPT = """You are reading a student's SPOKEN answer \
(already transcribed to text) to ONE specific practice question. The question is:

"{question_text}"

The student's transcribed answer:
"{transcript}"

Break the answer into an ORDERED list of the distinct claims/points/steps the \
student actually made, in the order they said them. This works for any \
subject — a step-by-step explanation, a list of reasons, a definition \
followed by an example, whatever the student actually said.

Output ONLY a JSON object of this shape:
{{
  "steps": [
    {{"text": "<one claim/point, in the student's own words, lightly cleaned up for filler words only>", "confidence": <0-100 int>}}
  ],
  "overall_confidence": <0-100 int>,
  "empty_reason": "<"none" if steps were found, otherwise "illegible" | "off_topic" | "blank">"
}}

RULES:
- Confidence reflects transcription clarity — a clean transcript should get \
HIGH confidence even if the content turns out to be off-topic or wrong; \
clarity and correctness are different things and must not be conflated.
- Never invent a point the student didn't actually say.
- Do not answer the question yourself or add reasoning the student didn't give.
- If steps is empty, "empty_reason" MUST explain why:
  - "illegible": the transcript is garbled/too fragmentary to make sense of \
— a RE-RECORD would fix this.
  - "off_topic": the transcript is clear but is not an attempt at THIS \
question — the student answered something else entirely.
  - "blank": the transcript is empty or just silence/noise, no real answer given.
- Output ONLY the JSON object, no markdown fences, no other text."""


async def extract_steps_from_text(
    transcript: str,
    question_text: str,
    api_key: str,
    timeout_sec: int = 30,
) -> dict:
    """
    Text-only counterpart to extract_steps, for a spoken answer. Returns the
    same shape ({"steps": [{"text","bbox": None,"confidence"}...],
    "overall_confidence"}) so callers (Gate D router, validate_step) don't
    need to branch on input type at all past this point.
    """
    if not transcript.strip():
        return {"steps": [], "overall_confidence": 0.0, "empty_reason": "blank"}
    if not api_key:
        return {"steps": [], "overall_confidence": 0.0, "empty_reason": "error", "error": "no_api_key"}

    try:
        from openai import AsyncOpenAI
    except ImportError:
        return {"steps": [], "overall_confidence": 0.0, "empty_reason": "error", "error": "openai_client_unavailable"}

    client = AsyncOpenAI(api_key=api_key)
    prompt = _TEXT_STEP_EXTRACTION_PROMPT.format(
        question_text=question_text[:1000], transcript=transcript[:4000],
    )

    try:
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            timeout=timeout_sec,
            messages=[{"role": "user", "content": prompt}],
        )
        content = resp.choices[0].message.content or ""
    except Exception as exc:
        logger.warning("Practice text step extraction: LLM call failed: %s", exc)
        return {"steps": [], "overall_confidence": 0.0, "empty_reason": "error", "error": str(exc)}

    match = _JSON_BLOCK.search(content)
    if not match:
        return {"steps": [], "overall_confidence": 0.0, "empty_reason": "error", "error": "no_json_in_response"}
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return {"steps": [], "overall_confidence": 0.0, "empty_reason": "error", "error": "invalid_json"}

    raw_steps = data.get("steps") or []
    steps = []
    for s in raw_steps:
        if not isinstance(s, dict) or not s.get("text"):
            continue
        conf = s.get("confidence", 0)
        try:
            conf = max(0.0, min(1.0, float(conf) / 100.0))
        except (TypeError, ValueError):
            conf = 0.5
        steps.append({"text": str(s["text"]).strip(), "bbox": None, "confidence": round(conf, 3)})

    overall = data.get("overall_confidence", 0)
    try:
        overall = max(0.0, min(1.0, float(overall) / 100.0))
    except (TypeError, ValueError):
        overall = (sum(s["confidence"] for s in steps) / len(steps)) if steps else 0.0

    empty_reason = data.get("empty_reason", "none")
    if empty_reason not in ("none", "illegible", "off_topic", "blank", "error"):
        empty_reason = "illegible"

    return {"steps": steps, "overall_confidence": round(overall, 3), "empty_reason": empty_reason}


# ---------------------------------------------------------------------------
# Gate D — deterministic arithmetic/algebra check (sympy)
# ---------------------------------------------------------------------------

_EQUATION_RE = re.compile(r"^(.*?)=(.*)$")


def _clean_for_sympify(expr: str) -> str:
    expr = expr.strip()
    expr = expr.replace("^", "**").replace("÷", "/").replace("×", "*")
    return expr


def _parse_equation(step_text: str):
    """Returns (lhs, rhs) sympy expressions, or None if not a parseable equation."""
    from sympy.parsing.sympy_parser import (
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )

    m = _EQUATION_RE.match(step_text.strip())
    if not m:
        return None
    lhs_raw, rhs_raw = m.group(1).strip(), m.group(2).strip()
    if not lhs_raw or not rhs_raw:
        return None
    transformations = standard_transformations + (implicit_multiplication_application,)
    try:
        lhs = parse_expr(_clean_for_sympify(lhs_raw), transformations=transformations)
        rhs = parse_expr(_clean_for_sympify(rhs_raw), transformations=transformations)
    except Exception:
        return None
    return lhs, rhs


# ---------------------------------------------------------------------------
# Column-level pinpointing for an addition/subtraction arithmetic_error —
# WHICH place-value column (ones/tens/hundreds/...) the first wrong digit
# is in, not just "the equation is wrong". Pure digit comparison once both
# the correct and written integers are known — no LLM guessing involved,
# same reliability tier as the rest of Gate D. Feeds practice_engine.
# locate_arithmetic_column (below) and practice_service's Gate E/F, which
# together let the frontend circle the actual digit a carry/borrow mistake
# happened at instead of the whole line (reported 2026-09-24, in response
# to a proposal for LLM-driven per-digit bounding boxes — vision models are
# measurably weak at exactly that kind of fine-grained spatial guess, so
# the semantic "which column" reasoning is kept fully deterministic here,
# and only the final pixel lookup uses the actual photo — see
# locate_arithmetic_column).
# ---------------------------------------------------------------------------

_PLACE_VALUE_NAMES = ["ones", "tens", "hundreds", "thousands", "ten_thousands"]
_SIMPLE_ADD_SUB_EQ_RE = re.compile(r"^\s*(\d+)\s*([+\-])\s*(\d+)\s*=\s*(\d+)\s*$")


def _digits_lsb_first(n: int) -> list[int]:
    if n == 0:
        return [0]
    digits = []
    while n > 0:
        digits.append(n % 10)
        n //= 10
    return digits


def _digit_diff_column(written: int, correct: int) -> dict | None:
    """
    Which place-value column does `written` first diverge from `correct`,
    reading from the ones place upward — exactly where a carry/borrow slip
    actually shows up on the page. Returns None if the two numbers are
    negative, equal (nothing to point at), or the divergence is further
    left than _PLACE_VALUE_NAMES covers (a real but much rarer case —
    Gate E/F's own error_step_index still applies, this only adds the
    finer column pinpoint when it can name the column with confidence).
    """
    if written < 0 or correct < 0 or written == correct:
        return None
    correct_digits = _digits_lsb_first(correct)
    written_digits = _digits_lsb_first(written)
    for i in range(max(len(correct_digits), len(written_digits))):
        cd = correct_digits[i] if i < len(correct_digits) else 0
        wd = written_digits[i] if i < len(written_digits) else 0
        if cd != wd:
            if i >= len(_PLACE_VALUE_NAMES):
                return None
            return {"row": "answer", "column": _PLACE_VALUE_NAMES[i]}
    return None  # every digit matches despite written != correct — shouldn't happen, stay safe


def check_arithmetic_step(step_text: str) -> dict | None:
    """
    Gate D, single-step case: only fires for a CLOSED equation — both sides
    contain no free symbols (e.g. "2 + 2 = 4", "3/4 + 1/8 = 7/8"). This is
    unambiguous: a closed equation is either numerically true or it isn't.

    Deliberately returns None (defers to Gate E/F's LLM path) for anything
    with a free variable (e.g. "2x + 3 = 7") — that's a normal, VALID step in
    solving for x, not an identity, and treating "doesn't simplify to 0" as
    "wrong" for such a line was a real bug caught in testing: it flagged a
    correct step as an arithmetic error. Whether a step WITH unknowns is
    valid depends on the step before it — see check_step_transformation.
    """
    parsed = _parse_equation(step_text)
    if parsed is None:
        return None
    lhs, rhs = parsed
    if lhs.free_symbols or rhs.free_symbols:
        return None  # has unknowns — not this function's job, see check_step_transformation

    import sympy
    try:
        diff = sympy.simplify(lhs - rhs)
    except Exception:
        return None

    is_equal = diff == 0
    result = {
        "applicable": True,
        "verdict": "arithmetically_valid" if is_equal else "arithmetic_error",
        "lhs": str(lhs),
        "rhs": str(rhs),
        "detail": "lhs - rhs simplifies to 0" if is_equal else f"lhs - rhs simplifies to {diff}, not 0",
    }
    if not is_equal:
        # Best-effort column pinpoint for the simplest, most literal shape
        # — a plain "a op b = c" line — computed straight from the digits.
        # Silently absent (not an error) for anything this regex doesn't
        # match (algebra, fractions, multi-term expressions); those still
        # get the ordinary whole-line arithmetic_error, just without the
        # extra column precision.
        m = _SIMPLE_ADD_SUB_EQ_RE.match(step_text.strip())
        if m:
            a_str, op, b_str, written_str = m.groups()
            a, b, written = int(a_str), int(b_str), int(written_str)
            correct = a + b if op == "+" else a - b
            if correct >= 0:
                column_hint = _digit_diff_column(written, correct)
                if column_hint:
                    result["column_hint"] = column_hint
    return result


def check_bare_expression_equality(prev_step_text: str, curr_step_text: str) -> dict | None:
    """
    Gate D, bare-result case: handles a very common notebook pattern that
    the other two checks both miss — one line writes the expression (e.g.
    "2/3 + 1/3"), and the NEXT line is just the computed value with no
    repeated "=" sign at all (e.g. "21/3"). check_arithmetic_step requires
    its own line to contain "="; check_step_transformation requires BOTH
    lines to be equations sharing a variable — neither accepts a bare
    result, so a student who miscalculates 2/3+1/3 as 21/3 and writes only
    "21/3" underneath previously got no deterministic check at all and fell
    straight through to the LLM (confirmed as the root cause of a report
    that this exact mistake was still marked "on the right track").

    Deliberately requires NEITHER line to contain "=" — a line with "=" is
    already the other two functions' job. Only fires when both sides parse
    as closed (no free-symbol) expressions, same reasoning as
    check_arithmetic_step: an unknown makes "not equal" meaningless on its
    own (e.g. simplifying "2x" to "x + x" is a valid step but the two forms
    aren't numerically comparable without solving first).

    Also requires prev_step_text to itself contain an operator (+, -, *, /,
    ^) — i.e. actually look like something-to-be-computed, not just another
    bare number. Without this, two genuinely UNRELATED bare numbers (e.g.
    separate answers to two different sub-questions) would get flagged as
    "arithmetic_error" purely for not being equal to each other, which is
    exactly the false-accusation failure mode this whole gate exists to
    avoid — caught in testing before this ever reached a real classroom.
    """
    if "=" in prev_step_text or "=" in curr_step_text:
        return None  # one of these already has its own equation-based check
    if not re.search(r"[+\-*/^]", prev_step_text.strip().lstrip("-")):
        return None  # prev isn't a calculation (just another bare value) — not safely comparable

    import sympy
    from sympy.parsing.sympy_parser import (
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )

    transformations = standard_transformations + (implicit_multiplication_application,)
    try:
        prev_val = parse_expr(
            _clean_for_sympify(prev_step_text.strip()), transformations=transformations,
        )
        curr_val = parse_expr(
            _clean_for_sympify(curr_step_text.strip()), transformations=transformations,
        )
    except Exception:
        return None
    if prev_val.free_symbols or curr_val.free_symbols:
        return None

    try:
        diff = sympy.simplify(prev_val - curr_val)
    except Exception:
        return None

    is_equal = diff == 0
    prev_clean, curr_clean = prev_step_text.strip(), curr_step_text.strip()
    detail = (
        f"{prev_clean} simplifies to the same value as {curr_clean}"
        if is_equal
        else f"{prev_clean} evaluates to {sympy.simplify(prev_val)}, not {curr_clean}"
    )
    result = {
        "applicable": True,
        "verdict": "arithmetically_valid" if is_equal else "arithmetic_error",
        "detail": detail,
    }
    if not is_equal and isinstance(prev_val, sympy.Integer) and isinstance(curr_val, sympy.Integer):
        # sympy auto-evaluates a plain "47+38" parse straight to Integer(85)
        # — prev_val here IS the correct answer already, curr_val the
        # student's bare written result. Same column-pinpoint reasoning as
        # check_arithmetic_step, just sourced from the already-parsed
        # values instead of re-matching a regex.
        column_hint = _digit_diff_column(int(curr_val), int(prev_val))
        if column_hint:
            result["column_hint"] = column_hint
    return result


def check_step_transformation(prev_step_text: str, curr_step_text: str) -> dict | None:
    """
    Gate D, consecutive-step case: does curr_step follow legally from
    prev_step? Both must be equations in the same variable(s) — checks
    whether they have the same solution set (e.g. "2x + 3 = 7" -> "2x = 4"
    -> "x = 2" are all valid transformations of each other even though none
    is a universal identity).

    Returns None (defers to LLM) whenever the two steps aren't both clean,
    solvable equations in a shared variable — e.g. multi-variable systems,
    inequalities, or anything that failed to parse. Never guesses.
    """
    import sympy

    prev = _parse_equation(prev_step_text)
    curr = _parse_equation(curr_step_text)
    if prev is None or curr is None:
        return None

    prev_lhs, prev_rhs = prev
    curr_lhs, curr_rhs = curr
    prev_vars = prev_lhs.free_symbols | prev_rhs.free_symbols
    curr_vars = curr_lhs.free_symbols | curr_rhs.free_symbols
    shared_vars = prev_vars & curr_vars
    if len(shared_vars) != 1 or prev_vars != curr_vars:
        return None  # only handle the common single-unknown case safely

    var = next(iter(shared_vars))
    try:
        prev_solutions = set(sympy.solve(sympy.Eq(prev_lhs, prev_rhs), var))
        curr_solutions = set(sympy.solve(sympy.Eq(curr_lhs, curr_rhs), var))
    except Exception:
        return None

    if not prev_solutions and not curr_solutions:
        return None  # both unsolvable (e.g. always-true/false) — not safe to compare

    same = prev_solutions == curr_solutions
    return {
        "applicable": True,
        "verdict": "arithmetically_valid" if same else "arithmetic_error",
        "detail": (
            f"same solution set for {var}: {prev_solutions}"
            if same
            else f"solution set changed for {var}: {prev_solutions} -> {curr_solutions}"
        ),
    }
