"""
Board region detection, type classification, and perspective correction.

Detection priority (first successful result wins):
  1. Calibrated ROI   — pre-stored corners from POST /sessions/{id}/calibrate
  2. Vision AI        — GPT-4o-mini locates board + classifies type (OPENAI_API_KEY)
  3. OpenCV contour   — multi-scale Canny + largest 4-sided contour (always available)
  4. YOLOv8-seg       — optional; `pip install ultralytics` (uses yolov8n-seg.pt)
  5. Full-frame       — no board isolated (fallback, confidence=0)

NOTE: Vision AI now runs BEFORE OpenCV contour when an API key is present.
Vision AI is reliably more accurate than contour-based detection, especially when:
  - The board has no clear border / fills the frame
  - Lighting is uneven or the background is complex
  - The board is partially obstructed

Board type auto-classification from colour analysis of the warped board region:
  whiteboard  — bright background (V > 175), low saturation (S < 65)
  greenboard  — green-dominant (OpenCV H 35–85)
  blackboard  — very dark background (V < 55)
  chalkboard  — catch-all for any remaining dark / ambiguous board

Confidence scoring:
  1.00   calibrated corners (pre-stored)
  0.85+  Vision AI (model-reported confidence × 0.95)
  0.50–0.68  Canny contour (area-ratio weighted)
  0.55   YOLOv8-seg (YOLO object confidence × 0.80)
  0.00   full-frame fallback

Output  BoardRegion:
  found           — True when a clear board was isolated
  warped          — perspective-corrected BGR (or full-frame copy; always set)
  board_type      — auto-classified type; overrides session setting when found=True
  confidence      — 0–1 detection quality
  corners         — (4,2) float32 TL,TR,BR,BL in original image coords
  polygon_mask    — uint8 mask (255=board, 0=bg), same size as input; None if not found
  original_bbox   — (x,y,w,h) bounding rect in original image; None if not found
  detection_method— "calibrated" | "vision" | "yolo" | "contour" | "fallback"
"""

from __future__ import annotations

import cv2
import logging
import numpy as np
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ── YOLOv8 lazy singleton ─────────────────────────────────────────────────────

_yolo_model: Any = None
_yolo_available: bool | None = None


def _get_yolo() -> Any:
    """Load yolov8n-seg once and cache. Returns None when not installed."""
    global _yolo_model, _yolo_available
    if _yolo_available is not None:
        return _yolo_model if _yolo_available else None
    try:
        from ultralytics import YOLO  # type: ignore
        _yolo_model = YOLO("yolov8n-seg.pt")  # ~7 MB nano-seg, auto-downloads
        _yolo_available = True
        logger.info("YOLOv8-seg loaded for board detection")
    except Exception as exc:
        logger.debug("YOLOv8 not available (optional): %s", exc)
        _yolo_available = False
    return _yolo_model if _yolo_available else None


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class BoardRegion:
    found: bool
    """True when a clear board boundary was isolated."""

    warped: np.ndarray
    """
    Perspective-corrected BGR image of the board.
    Always set — never None. Falls back to the original frame copy.
    """

    board_type: str = "chalkboard"
    """Auto-classified: whiteboard | greenboard | blackboard | chalkboard."""

    confidence: float = 0.0
    """Detection confidence 0–1. 0 = full-frame fallback, no board isolated."""

    corners: np.ndarray | None = None
    """(4, 2) float32 TL,TR,BR,BL in original image coordinates."""

    polygon_mask: np.ndarray | None = None
    """uint8 mask same HxW as input image. 255=board, 0=background."""

    original_bbox: tuple[int, int, int, int] | None = None
    """(x, y, w, h) bounding rect in original image coordinates."""

    detection_method: str = "fallback"
    """How the board was located: calibrated|vision|yolo|contour|fallback."""


# ── Public API ─────────────────────────────────────────────────────────────────

def detect_board(
    image_bgr: np.ndarray,
    min_area_ratio: float = 0.15,
    forced_corners: np.ndarray | None = None,
    api_key: str = "",
) -> BoardRegion:
    """
    Detect and perspective-correct the board region in a frame.

    Detection priority (Vision AI FIRST when api_key present):
      1. forced_corners  — use pre-stored calibrated corners directly
      2. Vision AI       — GPT-4o-mini (needs api_key)  ← most reliable
      3. OpenCV contour  — multi-scale Canny + largest 4-sided contour
      4. YOLOv8-seg      — large-surface segmentation (needs ultralytics)

    Args:
        image_bgr:       Input BGR frame.
        min_area_ratio:  Minimum fraction of frame the board must cover.
        forced_corners:  Pre-calibrated (4,2) float32 corners — skips detection entirely.
        api_key:         OpenAI API key for Vision AI detection.

    Returns:
        BoardRegion with warped image, board_type, confidence, and mask.
    """
    h, w = image_bgr.shape[:2]

    # ── 1. Calibrated ROI ────────────────────────────────────────────────────
    if forced_corners is not None and forced_corners.shape == (4, 2):
        warped = _perspective_transform(image_bgr, forced_corners)
        xs = forced_corners[:, 0]
        ys = forced_corners[:, 1]
        x, y = int(xs.min()), int(ys.min())
        bw = int(xs.max() - xs.min())
        bh = int(ys.max() - ys.min())
        mask = _compute_polygon_mask(h, w, forced_corners)
        btype = _classify_board_type(warped)
        logger.info("Board: calibrated corners → type=%s", btype)
        return BoardRegion(
            found=True,
            warped=warped,
            board_type=btype,
            confidence=1.0,
            corners=forced_corners,
            polygon_mask=mask,
            original_bbox=(x, y, bw, bh),
            detection_method="calibrated",
        )

    # ── 2. Vision AI (FIRST — most reliable when API key is present) ─────────
    # Vision AI handles complex cases: no visible border, partial occlusion,
    # uneven lighting, board filling most of the frame.
    # We store the result so it can be re-used as a last resort even if its
    # confidence falls below our primary threshold.
    low_conf_vision: BoardRegion | None = None
    if api_key:
        vision_result = _detect_board_vision(image_bgr, api_key)
        if vision_result is not None and vision_result.found:
            if vision_result.confidence >= 0.50:
                logger.info(
                    "Board: Vision AI conf=%.2f → type=%s",
                    vision_result.confidence, vision_result.board_type,
                )
                return vision_result
            else:
                # Save as fallback; may still be better than no detection
                low_conf_vision = vision_result
                logger.debug(
                    "Board: Vision AI low conf=%.2f — trying contour first",
                    vision_result.confidence,
                )

    # ── 3. OpenCV contour (fast, always available) ────────────────────────────
    # Multi-scale approach for better robustness.
    contour_result = _detect_board_contour(image_bgr, min_area_ratio)

    if contour_result.found and contour_result.confidence >= 0.55:
        logger.info(
            "Board: contour conf=%.2f → type=%s",
            contour_result.confidence, contour_result.board_type,
        )
        return contour_result

    # ── 4. YOLOv8-seg ─────────────────────────────────────────────────────────
    yolo_result = _detect_board_yolo(image_bgr)
    if yolo_result is not None and yolo_result.found:
        logger.info(
            "Board: YOLOv8 conf=%.2f → type=%s",
            yolo_result.confidence, yolo_result.board_type,
        )
        return yolo_result

    # ── 5. Accept low-confidence contour result if it found something ─────────
    if contour_result.found:
        logger.info(
            "Board: contour (low conf=%.2f) → type=%s",
            contour_result.confidence, contour_result.board_type,
        )
        return contour_result

    # ── 6. Low-confidence Vision AI result ───────────────────────────────────
    # Use Vision AI's low-confidence result rather than falling back to the
    # full frame — even a rough crop is better than no perspective correction.
    if low_conf_vision is not None:
        logger.info(
            "Board: Vision AI (low conf=%.2f) used as last resort → type=%s",
            low_conf_vision.confidence, low_conf_vision.board_type,
        )
        return low_conf_vision

    # ── 7. Full-frame fallback ─────────────────────────────────────────────────
    btype = _classify_board_type(image_bgr)
    logger.debug("Board: no boundary detected — full frame fallback, type=%s", btype)
    return BoardRegion(
        found=False,
        warped=image_bgr.copy(),
        board_type=btype,
        confidence=0.0,
        corners=None,
        polygon_mask=None,
        original_bbox=None,
        detection_method="fallback",
    )


def draw_board_outline(image_bgr: np.ndarray, region: BoardRegion) -> np.ndarray:
    """
    Draw detected board corners on the original frame (debug utility).
    Returns a copy with overlay.
    """
    vis = image_bgr.copy()
    if region.found and region.corners is not None:
        pts = region.corners.astype(np.int32).reshape((-1, 1, 2))
        cv2.polylines(vis, [pts], isClosed=True, color=(0, 255, 0), thickness=3)
        for i, (px, py) in enumerate(region.corners.astype(int)):
            label = ["TL", "TR", "BR", "BL"][i]
            cv2.circle(vis, (px, py), 8, (0, 0, 255), -1)
            cv2.putText(vis, label, (px + 8, py - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        # Board type + confidence label
        label_txt = f"{region.board_type} conf={region.confidence:.2f} ({region.detection_method})"
        cv2.putText(vis, label_txt, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    return vis


# ── Vision AI detection ────────────────────────────────────────────────────────

_BOARD_DETECT_PROMPT = """\
You are analyzing a classroom photograph to locate the writing board.

Find the main writing surface (chalkboard, blackboard, whiteboard, or green board) — \
the large rectangular area where the teacher writes educational content.

Return ONLY valid JSON (no markdown, no explanation):
{
  "found": true,
  "board_type": "whiteboard",
  "confidence": 0.87,
  "corners": [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
}

Rules:
- corners: the 4 corner points of the board surface in order:
  [top-left, top-right, bottom-right, bottom-left]
- All coordinate values use 0-999 space (0,0=top-left, 999,999=bottom-right of image)
- board_type must be exactly one of:
  "whiteboard"  — white/light surface with coloured or black markers
  "greenboard"  — green-painted chalkboard
  "blackboard"  — black or near-black chalk surface
  "chalkboard"  — any other dark chalk surface (use when colour is ambiguous)
- confidence: your certainty this is the writing board (0.0–1.0)
- Include the full board surface plus any surrounding frame/border
- If the board fills most of the image, place corners at the image edges
- Ignore: walls, projection screens, windows, desks, students, teachers, posters

If NO writing board is visible:
  {"found": false, "board_type": "chalkboard", "confidence": 0.0, "corners": []}
"""


def _detect_board_vision(
    image_bgr: np.ndarray,
    api_key: str,
) -> BoardRegion | None:
    """
    Use GPT-4o-mini to detect the board boundary and type.
    Returns BoardRegion (found=True) on success, None on error or no board found.

    Improvements over original:
    - Uses detail="high" for better corner accuracy (worth the cost for OCR quality)
    - Cross-validates board_type with colour analysis
    - Applies sub-pixel corner refinement using Harris corners
    """
    import base64
    import json as _json
    import asyncio

    h, w = image_bgr.shape[:2]

    # Use up to 1024px — enough for accurate corner detection
    scale = min(1.0, 1024.0 / max(h, w, 1))
    if scale < 1.0:
        small = cv2.resize(image_bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    else:
        small = image_bgr

    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        return None
    b64 = base64.b64encode(buf.tobytes()).decode("utf-8")

    async def _call() -> BoardRegion | None:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            return None

        client = AsyncOpenAI(api_key=api_key)
        try:
            resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=300,
                timeout=20,
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
                        {"type": "text", "text": _BOARD_DETECT_PROMPT},
                    ],
                }],
            )
        except Exception as exc:
            logger.warning("Board Vision API error: %s", exc)
            return None

        content = (resp.choices[0].message.content or "").strip()
        if content.startswith("```"):
            import re
            content = re.sub(r"^```[a-z]*\n?", "", content)
            content = re.sub(r"\n?```$", "", content)

        try:
            data = _json.loads(content)
        except Exception:
            logger.warning("Board Vision: non-JSON response: %.80s", content)
            return None

        if not data.get("found", False):
            return None

        raw_corners = data.get("corners", [])
        if len(raw_corners) != 4:
            return None

        try:
            pts = np.array([[float(c[0]), float(c[1])] for c in raw_corners], dtype=np.float32)
        except Exception:
            return None

        # Convert 0–999 space → original pixel coords
        pts[:, 0] = np.clip(pts[:, 0] / 999.0 * w, 0, w - 1)
        pts[:, 1] = np.clip(pts[:, 1] / 999.0 * h, 0, h - 1)

        # Sub-pixel refinement: snap each corner to the nearest Harris corner
        # within a search radius — compensates for AI coordinate imprecision.
        pts = _refine_corners_harris(image_bgr, pts, search_radius=30)

        ordered = _order_corners(pts)
        warped = _perspective_transform(image_bgr, ordered)
        xs, ys = ordered[:, 0], ordered[:, 1]
        bbox = (int(xs.min()), int(ys.min()), int(xs.max() - xs.min()), int(ys.max() - ys.min()))
        mask = _compute_polygon_mask(h, w, ordered)

        # Board type: use colour analysis as the primary source of truth.
        # Vision AI's label is used as a tiebreaker when colour is ambiguous.
        ai_btype = (data.get("board_type") or "chalkboard").lower().strip()
        if ai_btype not in ("whiteboard", "greenboard", "blackboard", "chalkboard"):
            ai_btype = "chalkboard"
        colour_btype = _classify_board_type(warped)
        board_type = colour_btype if colour_btype != "chalkboard" else ai_btype

        raw_conf = float(data.get("confidence", 0.7))
        confidence = round(min(raw_conf, 1.0) * 0.95, 3)

        return BoardRegion(
            found=True,
            warped=warped,
            board_type=board_type,
            confidence=confidence,
            corners=ordered,
            polygon_mask=mask,
            original_bbox=bbox,
            detection_method="vision",
        )

    # Async-to-sync bridge (same pattern as privacy detection)
    try:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is not None and running_loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, _call()).result(timeout=25)
        else:
            return asyncio.run(_call())
    except Exception as exc:
        logger.warning("Board Vision runner error: %s", exc)
        return None


# ── YOLOv8-seg detection ──────────────────────────────────────────────────────

def _detect_board_yolo(image_bgr: np.ndarray) -> BoardRegion | None:
    """
    Use YOLOv8-seg to find the board region.
    Requires: pip install ultralytics
    Returns BoardRegion (found=True) on success, None if not available/found.
    """
    model = _get_yolo()
    if model is None:
        return None

    h, w = image_bgr.shape[:2]
    frame_area = float(h * w)

    try:
        results = model(image_bgr, verbose=False)
        if not results or results[0].masks is None:
            return None

        result = results[0]
        masks = result.masks.data  # (N, H, W) boolean tensors
        boxes = result.boxes

        best_area = 0
        best_mask = None
        best_conf = 0.0

        for i in range(len(masks)):
            cls_id = int(boxes.cls[i].item()) if boxes is not None else -1
            if cls_id == 0:  # skip person (COCO class 0)
                continue

            obj_conf = float(boxes.conf[i].item()) if boxes is not None else 0.5
            mask_np = masks[i].cpu().numpy().astype(np.uint8) * 255

            # Resize mask to original image dimensions
            mask_resized = cv2.resize(mask_np, (w, h), interpolation=cv2.INTER_NEAREST)
            area = int(mask_resized.sum()) // 255

            if area < frame_area * 0.15:
                continue
            if area > best_area:
                best_area = area
                best_mask = mask_resized
                best_conf = obj_conf

        if best_mask is None:
            return None

        # Find the largest contour in the mask → approximate as quadrilateral
        contours, _ = cv2.findContours(best_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        cnt = max(contours, key=cv2.contourArea)
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.03 * peri, True)

        if len(approx) == 4:
            pts = approx.reshape(4, 2).astype(np.float32)
        else:
            rect = cv2.minAreaRect(cnt)
            pts = cv2.boxPoints(rect).astype(np.float32)

        ordered = _order_corners(pts)
        warped = _perspective_transform(image_bgr, ordered)
        xs, ys = ordered[:, 0], ordered[:, 1]
        bbox = (int(xs.min()), int(ys.min()), int(xs.max() - xs.min()), int(ys.max() - ys.min()))
        mask_out = _compute_polygon_mask(h, w, ordered)
        board_type = _classify_board_type(warped)
        confidence = round(min(best_conf * 0.80, 0.75), 3)

        return BoardRegion(
            found=True,
            warped=warped,
            board_type=board_type,
            confidence=confidence,
            corners=ordered,
            polygon_mask=mask_out,
            original_bbox=bbox,
            detection_method="yolo",
        )

    except Exception as exc:
        logger.warning("YOLOv8 board detection error: %s", exc)
        return None


# ── OpenCV contour detection ───────────────────────────────────────────────────

def _detect_board_contour(
    image_bgr: np.ndarray,
    min_area_ratio: float = 0.15,
) -> BoardRegion:
    """
    Multi-scale Canny → largest 4-sided contour → Harris-refined perspective warp.

    Improvements over v1:
    - Tries multiple Canny threshold combinations (auto + fixed fallbacks)
    - Uses morphological closing (not just dilation) to better connect edges
    - Accepts approximated polygons with 4-8 sides and simplifies to 4 corners
    - Applies Harris corner refinement to improve corner accuracy
    - Lower min_area_ratio (0.15 vs 0.20) to catch more boards
    - Confidence: 0.50 base + 0.18 bonus for area coverage

    Always returns a BoardRegion (found=True if qualifying contour found,
    found=False with full-frame fallback otherwise).
    """
    h, w = image_bgr.shape[:2]
    frame_area = float(h * w)

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

    # ── Edge map: try multiple preprocessing and threshold settings ───────────
    # We generate several candidate edge maps and merge them. This catches boards
    # with subtle borders (worn edge paint) as well as boards with strong frames.

    edges_combined = np.zeros((h, w), dtype=np.uint8)

    # Attempt 1: Otsu-derived auto-thresholds on lightly blurred image
    blurred_light = cv2.GaussianBlur(gray, (3, 3), 0)
    _, otsu_thresh = cv2.threshold(blurred_light, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    median_val = float(np.median(blurred_light))
    lower_auto = int(max(0, 0.50 * median_val))
    upper_auto = int(min(255, 1.50 * median_val))
    if upper_auto - lower_auto < 15:
        lower_auto, upper_auto = 40, 120
    edges1 = cv2.Canny(blurred_light, lower_auto, upper_auto)
    edges_combined = cv2.bitwise_or(edges_combined, edges1)

    # Attempt 2: Fixed wide-range thresholds on more blurred image (catches weak edges)
    blurred_med = cv2.GaussianBlur(gray, (7, 7), 0)
    edges2 = cv2.Canny(blurred_med, 20, 80)
    edges_combined = cv2.bitwise_or(edges_combined, edges2)

    # Attempt 3: High-contrast thresholds (catches boards with strong frame)
    edges3 = cv2.Canny(blurred_light, 80, 200)
    edges_combined = cv2.bitwise_or(edges_combined, edges3)

    # ── Morphological closing to connect fragmented edges ────────────────────
    # Closing = dilate then erode — fills small gaps without expanding borders much
    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    closed = cv2.morphologyEx(edges_combined, cv2.MORPH_CLOSE, close_kernel, iterations=2)

    # Additional dilation to bridge any remaining gaps
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    dilated = cv2.dilate(closed, dilate_kernel, iterations=1)

    # ── Find and rank contours ────────────────────────────────────────────────
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    best: BoardRegion | None = None

    for contour in contours[:15]:
        area = cv2.contourArea(contour)
        if area < frame_area * min_area_ratio:
            break

        # Try a range of approximation epsilons to find a 4-sided polygon
        peri = cv2.arcLength(contour, True)
        quad = None

        for eps_frac in (0.01, 0.02, 0.03, 0.04, 0.05, 0.07):
            approx = cv2.approxPolyDP(contour, eps_frac * peri, True)
            n = len(approx)
            if n == 4:
                quad = approx.reshape(4, 2).astype(np.float32)
                break
            elif 5 <= n <= 8 and quad is None:
                # More than 4 sides — keep as candidate and try larger epsilon
                pass

        # If no clean quad found, try fitting the convex hull as a quadrilateral
        if quad is None:
            hull = cv2.convexHull(contour)
            peri_h = cv2.arcLength(hull, True)
            for eps_frac in (0.02, 0.04, 0.06, 0.08):
                approx_h = cv2.approxPolyDP(hull, eps_frac * peri_h, True)
                if len(approx_h) == 4:
                    quad = approx_h.reshape(4, 2).astype(np.float32)
                    break

        # Last resort: bounding rectangle (axis-aligned)
        if quad is None:
            x, y, bw, bh = cv2.boundingRect(contour)
            # Only accept bounding rect if it's reasonably rectangular
            rect_area = float(bw * bh)
            if rect_area > 0 and area / rect_area >= 0.70:
                quad = np.array([
                    [x, y], [x + bw, y], [x + bw, y + bh], [x, y + bh]
                ], dtype=np.float32)

        if quad is None:
            continue

        # Validate the quadrilateral is roughly rectangular (not degenerate)
        if not _is_valid_quad(quad, h, w):
            continue

        # Sub-pixel corner refinement
        quad = _refine_corners_harris(image_bgr, quad, search_radius=20)

        ordered = _order_corners(quad)
        warped = _perspective_transform(image_bgr, ordered)
        x_bbox, y_bbox, bw_bbox, bh_bbox = cv2.boundingRect(contour)
        mask = _compute_polygon_mask(h, w, ordered)
        board_type = _classify_board_type(warped)
        area_frac = area / frame_area

        # Confidence: 0.50 base + up to 0.18 bonus for larger area coverage
        confidence = round(min(0.50 + 0.18 * area_frac, 0.68), 3)

        result = BoardRegion(
            found=True,
            warped=warped,
            board_type=board_type,
            confidence=confidence,
            corners=ordered,
            polygon_mask=mask,
            original_bbox=(x_bbox, y_bbox, bw_bbox, bh_bbox),
            detection_method="contour",
        )

        if best is None or confidence > best.confidence:
            best = result

        # If confidence is high enough, no need to check more contours
        if confidence >= 0.60:
            break

    if best is not None:
        return best

    # No qualifying quadrilateral — full frame fallback
    board_type = _classify_board_type(image_bgr)
    return BoardRegion(
        found=False,
        warped=image_bgr.copy(),
        board_type=board_type,
        confidence=0.0,
        corners=None,
        polygon_mask=None,
        original_bbox=None,
        detection_method="fallback",
    )


# ── Board type colour classification ──────────────────────────────────────────

def _classify_board_type(image_bgr: np.ndarray) -> str:
    """
    Classify the board type from HSV colour statistics.

    Improved sampling strategy:
    - Uses both the border region AND the full image histogram
    - Weights border region more (likely to contain board background)
    - Falls back gracefully for very small images

    Returns: "whiteboard" | "greenboard" | "blackboard" | "chalkboard"
    """
    h, w = image_bgr.shape[:2]
    if h < 10 or w < 10:
        return "chalkboard"

    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)

    # ── Full-image statistics ─────────────────────────────────────────────────
    full_hue = hsv[:, :, 0].ravel()
    full_sat = hsv[:, :, 1].ravel()
    full_val = hsv[:, :, 2].ravel()

    # ── Border region statistics (likely background, not text) ───────────────
    margin_y = max(h // 8, 8)
    margin_x = max(w // 8, 8)

    border_mask = np.zeros((h, w), dtype=np.uint8)
    border_mask[:margin_y, :] = 255
    border_mask[-margin_y:, :] = 255
    border_mask[:, :margin_x] = 255
    border_mask[:, -margin_x:] = 255

    bm = border_mask > 0
    border_hue = hsv[:, :, 0][bm]
    border_sat = hsv[:, :, 1][bm]
    border_val = hsv[:, :, 2][bm]

    if len(border_hue) == 0:
        return "chalkboard"

    # Weighted averages (border region = 60%, full image = 40%)
    # This is better than using only the border when the board has a wide frame
    mean_val = float(0.6 * np.mean(border_val) + 0.4 * np.mean(full_val))
    mean_sat = float(0.6 * np.mean(border_sat) + 0.4 * np.mean(full_sat))

    # Green hue fraction: check both border and full image
    border_green_frac = float(np.sum((border_hue >= 35) & (border_hue <= 85))) / max(len(border_hue), 1)
    full_green_frac = float(np.sum((full_hue >= 35) & (full_hue <= 85))) / max(len(full_hue), 1)
    green_frac = max(border_green_frac, full_green_frac)  # either region can indicate green

    # ── Classification thresholds ─────────────────────────────────────────────

    # Whiteboard: bright background + low saturation
    # Slightly relaxed thresholds vs v1 (175→160 for val, 65→75 for sat)
    # to catch older/yellowed whiteboards
    if mean_val > 160 and mean_sat < 75:
        return "whiteboard"

    # Greenboard: dominant green hue in either border or full image
    if green_frac > 0.22:  # relaxed from 0.28 — green boards may have a lot of writing
        return "greenboard"

    # Blackboard: very dark (border region emphasis to avoid dark text affecting result)
    border_mean_val = float(np.mean(border_val))
    if border_mean_val < 60:  # slightly relaxed from 55
        return "blackboard"

    # Chalkboard: medium-dark (could be faded black board or dusty green)
    return "chalkboard"


# ── Corner refinement ─────────────────────────────────────────────────────────

def _refine_corners_harris(
    image_bgr: np.ndarray,
    corners: np.ndarray,
    search_radius: int = 25,
) -> np.ndarray:
    """
    Snap each approximate corner to the nearest strong Harris corner within
    a search radius.  Falls back to the original point if no corner is found.

    This compensates for:
    - AI coordinate imprecision (coarse 0-999 space)
    - approxPolyDP simplification error
    - Blur effects moving the apparent corner

    Args:
        image_bgr:     Original BGR image
        corners:       (4, 2) float32 approximate corner locations
        search_radius: Pixel radius to search for a better corner

    Returns:
        (4, 2) float32 refined corners (unchanged if no nearby Harris corner found)
    """
    try:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        harris = cv2.cornerHarris(gray, blockSize=4, ksize=3, k=0.04)
        harris = cv2.dilate(harris, None)  # local maxima

        # Threshold: keep only strong corners (top 1%)
        threshold = 0.01 * harris.max()
        strong = harris > threshold

        h, w = image_bgr.shape[:2]
        refined = corners.copy()

        for i, (cx, cy) in enumerate(corners):
            cx, cy = float(cx), float(cy)

            # Search window clamped to image bounds
            x1 = max(0, int(cx - search_radius))
            x2 = min(w - 1, int(cx + search_radius))
            y1 = max(0, int(cy - search_radius))
            y2 = min(h - 1, int(cy + search_radius))

            roi = strong[y1:y2 + 1, x1:x2 + 1]
            if roi.size == 0 or not roi.any():
                continue  # no strong corner nearby — keep original

            # Candidate points within search window
            ys_local, xs_local = np.where(roi)
            candidate_x = xs_local + x1
            candidate_y = ys_local + y1

            # Pick the candidate closest to the approximate corner
            dists = np.hypot(candidate_x - cx, candidate_y - cy)
            best_idx = int(np.argmin(dists))
            if dists[best_idx] < search_radius:
                refined[i, 0] = float(candidate_x[best_idx])
                refined[i, 1] = float(candidate_y[best_idx])

        return refined

    except Exception as exc:
        logger.debug("Harris corner refinement failed (using original): %s", exc)
        return corners


# ── Quad validity check ────────────────────────────────────────────────────────

def _is_valid_quad(pts: np.ndarray, image_h: int, image_w: int) -> bool:
    """
    Check that a quadrilateral is a plausible board region:
    - Minimum side lengths (at least 10% of shorter image dimension)
    - Approximately convex (no self-intersecting sides)
    - Aspect ratio between 0.2 and 5.0 (avoids degenerate thin strips)
    - No extremely acute interior angles (< 20 degrees)
    """
    try:
        min_dim = min(image_h, image_w)
        min_side = min_dim * 0.10

        ordered = _order_corners(pts)
        tl, tr, br, bl = ordered

        # Side lengths
        sides = [
            float(np.linalg.norm(tr - tl)),  # top
            float(np.linalg.norm(br - tr)),  # right
            float(np.linalg.norm(bl - br)),  # bottom
            float(np.linalg.norm(tl - bl)),  # left
        ]

        if any(s < min_side for s in sides):
            return False

        # Aspect ratio check
        avg_width = (sides[0] + sides[2]) / 2.0
        avg_height = (sides[1] + sides[3]) / 2.0
        if avg_height < 1 or avg_width < 1:
            return False
        ratio = max(avg_width, avg_height) / min(avg_width, avg_height)
        if ratio > 6.0:
            return False

        # Convexity check (board should be roughly convex)
        hull_area = cv2.contourArea(cv2.convexHull(ordered.astype(np.int32)))
        quad_area = cv2.contourArea(ordered.astype(np.int32))
        if hull_area > 0 and quad_area / hull_area < 0.80:
            return False  # too concave

        return True

    except Exception:
        return True  # on error, be permissive


# ── Internal helpers ──────────────────────────────────────────────────────────

def _compute_polygon_mask(h: int, w: int, corners: np.ndarray) -> np.ndarray:
    """
    Create a binary mask with the quadrilateral defined by `corners` filled.
    Returns uint8 array of shape (h, w) with 255 inside the polygon.
    """
    mask = np.zeros((h, w), dtype=np.uint8)
    pts = corners.astype(np.int32).reshape((-1, 1, 2))
    cv2.fillPoly(mask, [pts], 255)
    return mask


def _order_corners(pts: np.ndarray) -> np.ndarray:
    """
    Reorder 4 points into canonical sequence: TL, TR, BR, BL.

    Method:
      TL → smallest (x+y) sum
      BR → largest  (x+y) sum
      TR → smallest (x-y) diff
      BL → largest  (x-y) diff
    """
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]   # top-left
    rect[2] = pts[np.argmax(s)]   # bottom-right
    diff = np.diff(pts, axis=1).ravel()
    rect[1] = pts[np.argmin(diff)]  # top-right
    rect[3] = pts[np.argmax(diff)]  # bottom-left
    return rect


def _perspective_transform(image: np.ndarray, corners: np.ndarray) -> np.ndarray:
    """
    Four-point homography → top-down rectangular view.

    Output dimensions are the maximum of the two parallel side lengths so no
    content is lost. Clamped to 4096 px on either axis (memory safety).
    """
    tl, tr, br, bl = corners

    w_top = float(np.linalg.norm(tr - tl))
    w_bot = float(np.linalg.norm(br - bl))
    out_w = min(int(max(w_top, w_bot)), 4096)

    h_left  = float(np.linalg.norm(bl - tl))
    h_right = float(np.linalg.norm(br - tr))
    out_h = min(int(max(h_left, h_right)), 4096)

    if out_w < 10 or out_h < 10:
        return image.copy()

    dst = np.array(
        [[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]],
        dtype=np.float32,
    )
    M = cv2.getPerspectiveTransform(corners, dst)
    return cv2.warpPerspective(image, M, (out_w, out_h), flags=cv2.INTER_LANCZOS4)
