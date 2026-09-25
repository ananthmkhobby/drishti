"""
OCR pipeline orchestrator.

process_frame()         — single image bytes → FrameOCRResult
merge_session_frames()  — list of FrameOCRResults → SessionMergeResult

The pipeline per frame:
  1. Decode image bytes to BGR ndarray
  2. Validate (blur / brightness / size)
  3. Board detection + perspective correction
  4. Board-type-specific preprocessing
  5. Convert grayscale back to 3-channel BGR for engine compat
  6. Run OCR (PaddleOCR / Tesseract) with confidence routing
  7. Return FrameOCRResult

Session merge:
  - Sort frames by sequence_no
  - Skip near-duplicate text blocks (>85% token Jaccard overlap)
  - Emit diagrams as marker entries (content=null)
  - Format merged_text as structured Markdown (headings → ##, lists → -, formulas indented)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.ocr.image_preprocessor import validate_frame, to_ocr_ready
from app.ocr.board_detector import detect_board
from app.ocr.ocr_engine import run_ocr, FrameOCRResult, TextRegion

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session merge result
# ---------------------------------------------------------------------------

@dataclass
class SessionMergeResult:
    session_id: str
    merged_text: str
    """Markdown-formatted text: headings as ##, lists as -, formulas indented."""

    regions: list[dict]
    """
    All non-duplicate regions across all frames. Each entry:
    {
      "frame_id": str,
      "sequence_no": int,
      "type": str,
      "content": str | null,
      "bbox": [x1, y1, x2, y2],
      "confidence": float | null,
    }
    """

    frame_count: int
    """Total frames attempted."""

    processed_frames: int
    """Frames that produced at least one region (not errored / invalid)."""


# ---------------------------------------------------------------------------
# Privacy: detect and blur people
#
# Detection strategy (tried in order, first success wins):
#
#   1. GPT-4o-mini Vision  — when OPENAI_API_KEY is set.
#      Sends a cheap, targeted prompt asking only "where are the people?".
#      Returns normalised bounding boxes [x1%,y1%,x2%,y2%] with very high
#      accuracy at any angle, distance, lighting, or occlusion.
#
#   2. OpenCV Haar cascades — fallback when no OpenAI key.
#      Covers frontal + profile faces and upper/full body.  Less reliable
#      but zero API cost and no network dependency.
#
# Blurring is always done by OpenCV GaussianBlur regardless of which
# detector found the regions.
# ---------------------------------------------------------------------------

# ── Vision AI detection ──────────────────────────────────────────────────────

def _detect_people_vision(
    image_bgr: np.ndarray,
    frame_id: str,
    api_key: str,
) -> list[tuple[int, int, int, int]]:
    """
    Ask GPT-4o-mini to locate people in the image.
    Returns pixel-space boxes as (x, y, w, h) tuples, ready for GaussianBlur.
    Returns [] on any error (non-fatal — caller falls back to Haar).

    The image is downscaled to ≤ 512 px before sending — privacy detection
    does not need the full resolution that OCR requires, so this is ~4×
    cheaper than the OCR call.
    """
    import base64, json as _json, asyncio

    h, w = image_bgr.shape[:2]

    # Downscale — 768px gives enough detail to detect full bodies and partial silhouettes
    max_dim = 768
    scale = min(1.0, max_dim / max(h, w, 1))
    small = cv2.resize(image_bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        return []
    b64 = base64.b64encode(buf.tobytes()).decode("utf-8")

    prompt = (
        "Look at this image carefully. Find EVERY person — faces, bodies, silhouettes, "
        "even partial (backs of heads, shoulders, arms).\n"
        "Return ONLY valid JSON (no markdown, no explanation):\n"
        '{"people": [{"bbox": [x1, y1, x2, y2]}, ...]}\n'
        "bbox = PERCENTAGES 0–100 of image width/height. "
        "x1,y1 = top-left, x2,y2 = bottom-right of the person's full body area.\n"
        "Expand each box by ~15% so hair edges and shoulders are fully covered.\n"
        "A person standing in front of a board: their ENTIRE silhouette should be one box.\n"
        'If absolutely NO person is visible: {"people": []}'
    )

    async def _call() -> list[tuple[int, int, int, int]]:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            return []
        client = AsyncOpenAI(api_key=api_key)
        try:
            resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=256,
                timeout=15,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "auto"},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }],
            )
        except Exception as exc:
            logger.warning("Privacy Vision API error frame=%s: %s", frame_id, exc)
            return []

        content = (resp.choices[0].message.content or "").strip()
        # Strip markdown fences if present
        if content.startswith("```"):
            content = __import__("re").sub(r"^```[a-z]*\n?", "", content)
            content = __import__("re").sub(r"\n?```$", "", content)
        try:
            data = _json.loads(content)
        except Exception:
            logger.warning("Privacy Vision: non-JSON response frame=%s: %.80s", frame_id, content)
            return []

        sh, sw = small.shape[:2]
        boxes: list[tuple[int, int, int, int]] = []
        for person in data.get("people", []):
            bbox = person.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            try:
                # Convert pct → original-image pixel coords
                px1 = int(bbox[0] / 100 * sw / scale)
                py1 = int(bbox[1] / 100 * sh / scale)
                px2 = int(bbox[2] / 100 * sw / scale)
                py2 = int(bbox[3] / 100 * sh / scale)
                bw  = max(1, px2 - px1)
                bh  = max(1, py2 - py1)
                boxes.append((px1, py1, bw, bh))
            except Exception:
                continue

        logger.info(
            "Privacy Vision frame=%s — detected %d person region(s)",
            frame_id, len(boxes),
        )
        return boxes

    try:
        # If we're already inside a running event loop (FastAPI async handler),
        # we must not call loop.run_until_complete() — run in a thread instead.
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is not None and running_loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, _call()).result(timeout=20)
        else:
            return asyncio.run(_call())
    except Exception as exc:
        logger.warning("Privacy Vision runner error frame=%s: %s", frame_id, exc)
        return []


# ── Haar cascade fallback ────────────────────────────────────────────────────

def _detect_people_haar(image_bgr: np.ndarray, frame_id: str) -> list[tuple[int, int, int, int]]:
    """
    Haar-cascade fallback — used when no OpenAI key is available.
    Detects frontal faces, profile faces, upper bodies, and full bodies.
    """
    try:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)  # helps with dim / mixed classroom lighting

        def _load(name: str):
            path = cv2.data.haarcascades + name  # type: ignore[attr-defined]
            cc = cv2.CascadeClassifier(path)
            return cc if not cc.empty() else None

        boxes: list[tuple[int, int, int, int]] = []
        for name, neighbors, min_sz in [
            ("haarcascade_frontalface_alt2.xml",   3, (24, 24)),
            ("haarcascade_frontalface_default.xml", 3, (24, 24)),
            ("haarcascade_profileface.xml",         3, (24, 24)),
            ("haarcascade_fullbody.xml",            2, (40, 40)),
            ("haarcascade_upperbody.xml",           2, (40, 40)),
        ]:
            cc = _load(name)
            if cc is None:
                continue
            found = cc.detectMultiScale(
                gray, scaleFactor=1.05, minNeighbors=neighbors,
                minSize=min_sz, flags=cv2.CASCADE_SCALE_IMAGE,
            )
            if len(found):
                boxes.extend([tuple(b) for b in found])  # type: ignore[misc]

        return _nms(boxes, iou_threshold=0.4)
    except Exception as exc:
        logger.warning("Haar detection error frame=%s: %s", frame_id, exc)
        return []


def _nms(
    boxes: list[tuple[int, int, int, int]],
    iou_threshold: float = 0.4,
) -> list[tuple[int, int, int, int]]:
    """Merge heavily overlapping boxes (same person found by multiple cascades)."""
    if not boxes:
        return []
    keep: list[tuple[int, int, int, int]] = []
    for box in boxes:
        x, y, bw, bh = box
        merged = False
        for i, k in enumerate(keep):
            kx, ky, kw, kh = k
            ix1, iy1 = max(x, kx), max(y, ky)
            ix2, iy2 = min(x + bw, kx + kw), min(y + bh, ky + kh)
            if ix2 <= ix1 or iy2 <= iy1:
                continue
            inter = (ix2 - ix1) * (iy2 - iy1)
            union = bw * bh + kw * kh - inter
            if union > 0 and inter / union >= iou_threshold:
                nx1, ny1 = min(x, kx), min(y, ky)
                nx2, ny2 = max(x + bw, kx + kw), max(y + bh, ky + kh)
                keep[i] = (nx1, ny1, nx2 - nx1, ny2 - ny1)
                merged = True
                break
        if not merged:
            keep.append(box)
    return keep


# ── Blur applicator (shared by both detection paths) ─────────────────────────

def _apply_blur(
    image_bgr: np.ndarray,
    boxes: list[tuple[int, int, int, int]],
) -> np.ndarray:
    """
    Apply heavy privacy blur to each bounding box region.

    Strategy (strongest possible anonymisation):
      1. Expand the box by 50% padding so hairline / shoulder edges are covered.
      2. Pixelate the region (downscale → nearest-neighbour upscale) — this
         destroys fine detail like facial features and is irreversible.
      3. Apply a large Gaussian blur on top of the pixelated region for a
         smooth, unmistakably blurred appearance.
      4. Repeat the Gaussian pass three times to ensure no residual detail.
    """
    result = image_bgr.copy()
    h, w = result.shape[:2]
    for (x, y, bw, bh) in boxes:
        # 50% padding — covers hair, shoulders, partial profiles
        pad_x, pad_y = int(bw * 0.50), int(bh * 0.50)
        x1, y1 = max(0, x - pad_x), max(0, y - pad_y)
        x2, y2 = min(w, x + bw + pad_x), min(h, y + bh + pad_y)
        roi = result[y1:y2, x1:x2]
        if roi.size == 0:
            continue

        roi_h, roi_w = roi.shape[:2]

        # Step 1: Pixelate — reduce to ~12×12 pixel blocks
        pixel_size = max(6, min(roi_w, roi_h) // 12)
        small_w = max(1, roi_w // pixel_size)
        small_h = max(1, roi_h // pixel_size)
        small = cv2.resize(roi, (small_w, small_h), interpolation=cv2.INTER_LINEAR)
        pixelated = cv2.resize(small, (roi_w, roi_h), interpolation=cv2.INTER_NEAREST)

        # Step 2: Heavy Gaussian blur — kernel scales with region size, minimum 151
        k = max(151, (min(roi_w, roi_h) // 2) | 1)
        blurred = cv2.GaussianBlur(pixelated, (k, k), 0)

        # Step 3: Two additional blur passes — ensures no edge detail survives
        blurred = cv2.GaussianBlur(blurred, (k, k), 0)
        blurred = cv2.GaussianBlur(blurred, (k, k), 0)

        result[y1:y2, x1:x2] = blurred
    return result


# ── Face-only Haar (safety net, fast) ────────────────────────────────────────

def _detect_faces_haar(image_bgr: np.ndarray, frame_id: str) -> list[tuple[int, int, int, int]]:
    """
    Lightweight face-only Haar pass — only frontal + profile face cascades.
    Much faster and more precise than full _detect_people_haar.
    Used as a safety-net second pass after Vision AI to catch any missed faces.
    """
    try:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)

        def _load(name: str):
            path = cv2.data.haarcascades + name  # type: ignore[attr-defined]
            cc = cv2.CascadeClassifier(path)
            return cc if not cc.empty() else None

        boxes: list[tuple[int, int, int, int]] = []
        for name, neighbors, min_sz in [
            ("haarcascade_frontalface_alt2.xml",    4, (30, 30)),
            ("haarcascade_frontalface_default.xml",  4, (30, 30)),
            ("haarcascade_profileface.xml",          4, (30, 30)),
        ]:
            cc = _load(name)
            if cc is None:
                continue
            found = cc.detectMultiScale(
                gray, scaleFactor=1.05, minNeighbors=neighbors,
                minSize=min_sz, flags=cv2.CASCADE_SCALE_IMAGE,
            )
            if len(found):
                boxes.extend([tuple(b) for b in found])  # type: ignore[misc]

        return _nms(boxes, iou_threshold=0.3)
    except Exception as exc:
        logger.warning("Face Haar detection error frame=%s: %s", frame_id, exc)
        return []


# ── Public entry point ────────────────────────────────────────────────────────

def _blur_people(
    image_bgr: np.ndarray,
    frame_id: str,
    openai_key: str = "",
) -> tuple[np.ndarray, int]:
    """
    Detect people and blur them.

    Strategy (both paths run together when Vision AI key is present):
      • GPT-4o-mini Vision  — body-level bounding boxes (best coverage)
      • Haar face cascades  — tight face boxes as a safety net

    When no OpenAI key: Haar-only (full body + face cascades).

    Running both Vision AI and Haar together ensures that even if Vision AI
    returns a bbox that misses the edges of a face, the Haar face pass catches
    it and the union of boxes is blurred.

    Returns (processed_image, num_regions_blurred).
    num_regions_blurred == 0 means no people detected.
    Runs silently — any error returns the original image unchanged.
    """
    try:
        if openai_key:
            # Primary: Vision AI body-level detection
            boxes = _detect_people_vision(image_bgr, frame_id, openai_key)
            # Safety net: Haar face-specific pass (catches faces outside Vision AI bbox)
            face_boxes = _detect_faces_haar(image_bgr, frame_id)
            all_boxes = _nms(boxes + face_boxes, iou_threshold=0.3)
            engine = "vision+haar"
        else:
            all_boxes = _detect_people_haar(image_bgr, frame_id)
            engine = "haar"

        if not all_boxes:
            logger.debug("Privacy(%s): frame %s — no people detected", engine, frame_id)
            return image_bgr, 0

        logger.info(
            "Privacy(%s): frame %s — blurring %d region(s)",
            engine, frame_id, len(all_boxes),
        )
        return _apply_blur(image_bgr, all_boxes), len(all_boxes)

    except Exception as exc:
        logger.warning("Privacy blur failed for frame %s (continuing): %s", frame_id, exc)
        return image_bgr, 0


# ---------------------------------------------------------------------------
# Board-exterior privacy blur
# ---------------------------------------------------------------------------

def _blur_outside_board(
    image_bgr: np.ndarray,
    board,  # BoardRegion from detect_board()
) -> tuple[np.ndarray, int]:
    """
    GUARANTEED privacy blur strategy:
      1. Blur the ENTIRE image heavily
      2. Paste back ONLY the board region (unblurred)

    This ensures anyone outside the board boundary is always blurred —
    no person-detection AI is needed.  Works for people standing beside,
    in front of, or around the board.

    Also runs the Haar face cascade as a safety net for anyone partially
    overlapping the board edges.

    Returns (blurred_image, regions_blurred_count).
    regions_blurred_count = 0 only when board detection completely failed
    AND no faces were found (very unlikely).
    """
    h, w = image_bgr.shape[:2]

    # Build the board mask ─────────────────────────────────────────────────────
    board_mask: np.ndarray | None = None

    if board is not None and board.found and board.polygon_mask is not None:
        board_mask = board.polygon_mask  # uint8, 255=board area
    elif board is not None and board.found and board.corners is not None:
        # Recompute mask from corners if polygon_mask wasn't stored
        board_mask = np.zeros((h, w), dtype=np.uint8)
        pts = board.corners.astype(np.int32)
        cv2.fillPoly(board_mask, [pts], 255)

    # Heavy blur of the full image (three passes for maximum anonymisation) ────
    k = max(99, (min(h, w) // 8) | 1)   # kernel scales with image size, always odd
    blurred_full = cv2.GaussianBlur(image_bgr, (k, k), 0)
    blurred_full = cv2.GaussianBlur(blurred_full, (k, k), 0)
    blurred_full = cv2.GaussianBlur(blurred_full, (k, k), 0)

    if board_mask is not None:
        # Paste back the unblurred board region
        result = blurred_full.copy()
        result[board_mask > 0] = image_bgr[board_mask > 0]
        regions_count = 1  # at least the outside-board area was blurred
        logger.info(
            "Privacy(board-exterior): frame — board area preserved, "
            "everything outside blurred (mask coverage %.1f%%)",
            100.0 * float(np.sum(board_mask > 0)) / (h * w),
        )
    else:
        # Board not detected: blur the entire image as a safe fallback
        result = blurred_full
        regions_count = 1
        logger.info(
            "Privacy(board-exterior): board mask unavailable — full-image blur applied"
        )

    # Safety-net: also blur any faces that are still visible INSIDE the board
    # region (e.g., someone standing directly in front of / writing on the board)
    face_boxes = _detect_faces_haar(result, "safety-net")
    if face_boxes:
        result = _apply_blur(result, face_boxes)
        regions_count += len(face_boxes)
        logger.info(
            "Privacy(board-exterior): %d face(s) detected inside board area — blurred",
            len(face_boxes),
        )

    return result, regions_count


def _blur_faces_only(image_bgr: np.ndarray) -> tuple[np.ndarray, int]:
    """
    Privacy pass for board types with no "board" shape to guarantee-blur
    around (notebook photos) — the board-exterior strategy above would just
    blur the entire image, since there's no board mask to paste back. A
    notebook capture is inherently a close-up of paper, not a room, so the
    realistic risk is a hand or a stray face at the edge of frame — detect
    and blur only that, rather than destroying the whole page.

    Returns (image, regions_blurred_count) — same shape as
    _blur_outside_board so callers don't need to branch on the return value.
    """
    face_boxes = _detect_faces_haar(image_bgr, "notebook")
    if not face_boxes:
        return image_bgr, 0
    result = _apply_blur(image_bgr, face_boxes)
    logger.info("Privacy(notebook): %d face(s) detected — blurred", len(face_boxes))
    return result, len(face_boxes)


# ---------------------------------------------------------------------------
# Single-frame pipeline
# ---------------------------------------------------------------------------

def process_frame(
    image_bytes: bytes,
    frame_id: str,
    board_type: str = "chalkboard",
    board_roi: list | None = None,
    subject: str = "General",
    grade: str = "Grade 8",
) -> FrameOCRResult:
    """
    Full OCR pipeline for a single frame.

    Pipeline order (board detection now runs BEFORE privacy so that the
    board polygon is available for the guaranteed board-exterior blur):

      1. Decode image
      2. Board detection  ← moved up; result reused by privacy AND OCR
      3. Privacy blur     ← uses board polygon to blur everything outside board
      4. Validate image quality
      5. Preprocessing
      6. OCR
      7. Diagram crop + correctness validation (if any diagram regions found)

    Args:
        image_bytes:  Raw JPEG/PNG bytes from storage.
        frame_id:     UUID string for the Frame row.
        board_type:   "chalkboard" | "whiteboard" | "smartboard".
        subject:      Session subject — used to prompt diagram validation.
        grade:        Session grade — used to prompt diagram validation.

    Returns:
        FrameOCRResult with regions, confidence, engine_used, raw_text.
        On hard failure (bad bytes, no engines), returns a result with error set.
    """
    # ── Step 1: Decode ────────────────────────────────────────────────────────
    nparr = np.frombuffer(image_bytes, np.uint8)
    image_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if image_bgr is None:
        return FrameOCRResult(
            frame_id=frame_id,
            engine_used="none",
            confidence=0.0,
            regions=[],
            raw_text="",
            error="Failed to decode image — not a valid JPEG/PNG",
        )

    try:
        from app.config import get_settings as _gs
        _openai_key = _gs().openai_api_key or ""
    except Exception:
        _openai_key = ""

    # ── Step 2: Board detection (single call — result used for privacy + OCR) ─
    # Skipped entirely for "notebook": there is no board shape to find — the
    # photo IS the content, edge to edge — so searching for one only wastes
    # a Vision API call and risks warping to a bogus region. board stays
    # None, which every downstream step already treats as "use the full
    # frame" (this is the same object board detection itself returns on a
    # genuine failure, so nothing else needs a notebook-specific branch).
    board = None
    board_type_used: str = board_type
    board_confidence_used: float = 0.0
    board_method_used: str = "fallback"
    if board_type == "notebook":
        board_method_used = "notebook_no_board"
        logger.debug("Frame %s: notebook mode — skipping board detection", frame_id)
    else:
        try:
            if board_roi and len(board_roi) == 4:
                corners = np.array(board_roi, dtype=np.float32)
                board = detect_board(image_bgr, forced_corners=corners, api_key=_openai_key)
                logger.debug("Frame %s: using calibrated board ROI", frame_id)
            else:
                board = detect_board(image_bgr, api_key=_openai_key)
                if board.found:
                    logger.info(
                        "Frame %s: board detected method=%s conf=%.2f type=%s",
                        frame_id, board.detection_method, board.confidence, board.board_type,
                    )
                else:
                    logger.debug("Frame %s: no board boundary — full-frame fallback", frame_id)
            board_type_used = (
                board.board_type if board.found and board.confidence >= 0.45 else board_type
            )
            board_confidence_used = board.confidence
            board_method_used = board.detection_method
        except Exception as exc:
            logger.warning("Frame %s: board detection failed (%s) — continuing", frame_id, exc)

    # ── Step 3: Privacy — board-exterior blur (GUARANTEED approach) ───────────
    #
    # Strategy: blur the ENTIRE image, then restore the board region pixel-for-
    # pixel.  Everyone outside the board is unconditionally blurred — no person-
    # detection AI, no false-negatives.
    #
    # IMPORTANT: image_bgr is intentionally NOT replaced.
    # OCR must run on the ORIGINAL so text near people's hands/bodies is readable.
    blurred_image_bytes: bytes | None = None
    privacy_blurred: int = 0
    try:
        # Notebook has no board to guarantee-blur around — _blur_outside_board
        # would treat "no board" as "blur the entire photo", which for a
        # notebook (the whole frame IS the content) destroys the capture.
        # Detect-and-blur faces only instead.
        if board_type == "notebook":
            blurred_bgr, privacy_blurred = _blur_faces_only(image_bgr)
        else:
            blurred_bgr, privacy_blurred = _blur_outside_board(image_bgr, board)
        ok, buf = cv2.imencode(".jpg", blurred_bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if ok:
            blurred_image_bytes = buf.tobytes()
        logger.info("Frame %s: privacy_blurred=%d blurred_bytes=%s",
                    frame_id, privacy_blurred, "yes" if blurred_image_bytes else "no")
    except Exception as exc:
        logger.warning("Frame %s: privacy blur failed (%s) — continuing without blur", frame_id, exc)

    # ── Step 4: Validate image quality ───────────────────────────────────────
    validation = validate_frame(image_bgr)
    logger.info(
        "Frame %s validation: valid=%s reason=%s blur=%.1f brightness=%.1f size=%dx%d",
        frame_id, validation.is_valid, validation.reason,
        validation.blur_score, validation.brightness,
        image_bgr.shape[1], image_bgr.shape[0],
    )
    if not validation.is_valid:
        return FrameOCRResult(
            frame_id=frame_id,
            engine_used="none",
            confidence=0.0,
            regions=[],
            raw_text="",
            error=f"skipped_invalid:{validation.reason}",
            privacy_blurred=privacy_blurred,
            blurred_image_bytes=blurred_image_bytes,
            board_type=board_type_used,
            board_confidence=board_confidence_used,
            board_detection_method=board_method_used,
        )

    # ── Steps 5–6: Preprocessing + OCR ───────────────────────────────────────
    # Wrapped in try/except so any crash still returns the blurred bytes.
    try:
        working = board.warped if board is not None else image_bgr.copy()

        effective_board_type = board_type_used
        if effective_board_type != board_type:
            logger.info(
                "Frame %s: auto board type '%s' overrides session '%s'",
                frame_id, effective_board_type, board_type,
            )

        # Step 5: Board-type preprocessing (for PaddleOCR)
        _, ocr_ready_gray = to_ocr_ready(working, effective_board_type)

        # Step 6: OCR
        if len(ocr_ready_gray.shape) == 2:
            ocr_input = cv2.cvtColor(ocr_ready_gray, cv2.COLOR_GRAY2BGR)
        else:
            ocr_input = ocr_ready_gray

        result = run_ocr(ocr_input, frame_id=frame_id, board_type=effective_board_type, original_bgr=working)

        # A confidently-wrong board detection (e.g. picking wall/ceiling above
        # the actual board) can crop something that's genuinely illegible even
        # when the full photo is sharp and well-lit — `validate_frame(image_bgr)`
        # above only checks the raw photo, never the crop actually sent to OCR.
        # If cropping to the "detected board" found nothing, retry once on the
        # full original frame before giving up.
        if (
            board is not None
            and not result.regions
            and not result.raw_text
            and not result.error
        ):
            logger.info(
                "Frame %s: board crop (method=%s) OCR found nothing — retrying on full frame",
                frame_id, board.detection_method,
            )
            full_frame = image_bgr.copy()
            fallback_result = run_ocr(
                full_frame, frame_id=frame_id, board_type=effective_board_type, original_bgr=full_frame,
            )
            if fallback_result.regions or fallback_result.raw_text:
                logger.info(
                    "Frame %s: full-frame retry succeeded (regions=%d) — using it instead of the board crop",
                    frame_id, len(fallback_result.regions),
                )
                result = fallback_result
                working = full_frame

        # Step 7: any diagram regions with a real bbox get cropped + validated
        # for correctness. Uses `working` (same coordinate space the Vision
        # OCR pass reported bbox against) and only runs when Vision is
        # configured — no local-engine equivalent exists for this.
        if _openai_key and result.regions:
            try:
                from app.ocr.ocr_engine import crop_and_validate_diagrams
                result.diagrams = crop_and_validate_diagrams(
                    result.regions, working, subject, grade, _openai_key, frame_id,
                )
            except Exception as exc:
                logger.warning("Frame %s: diagram crop/validate failed: %s", frame_id, exc)

    except Exception as exc:
        logger.exception("OCR pipeline failed for frame %s — privacy blur preserved", frame_id)
        return FrameOCRResult(
            frame_id=frame_id,
            engine_used="none",
            confidence=0.0,
            regions=[],
            raw_text="",
            error=f"pipeline_error:{str(exc)[:200]}",
            privacy_blurred=privacy_blurred,
            blurred_image_bytes=blurred_image_bytes,
            board_type=board_type_used,
            board_confidence=board_confidence_used,
            board_detection_method=board_method_used,
        )

    result.privacy_blurred = privacy_blurred
    result.blurred_image_bytes = blurred_image_bytes
    result.board_type = board_type_used
    result.board_confidence = board_confidence_used
    result.board_detection_method = board_method_used
    return result


# ---------------------------------------------------------------------------
# Session-level multi-frame merge
# ---------------------------------------------------------------------------

def merge_session_frames(
    frame_results: list[FrameOCRResult],
    session_id: str,
    sequence_map: dict[str, int] | None = None,
) -> SessionMergeResult:
    """
    Merge per-frame OCR results into a single de-duplicated session document.

    Args:
        frame_results:  List of FrameOCRResult from process_frame().
        session_id:     UUID string for the Session row.
        sequence_map:   {frame_id: sequence_no} for temporal ordering.
                        If omitted, frames are processed in list order.

    Returns:
        SessionMergeResult with merged_text and flat regions list.
    """
    # Sort by sequence number
    def _seq(r: FrameOCRResult) -> int:
        return sequence_map.get(r.frame_id, 9999) if sequence_map else 9999

    ordered = sorted(frame_results, key=_seq)

    seen_texts: list[str] = []
    merged_regions: list[dict] = []
    processed = 0

    for frame in ordered:
        if frame.error or not frame.regions:
            continue
        processed += 1
        seq_no = sequence_map.get(frame.frame_id, 0) if sequence_map else 0

        for region in frame.regions:
            if region.type == "diagram":
                # Include diagram bounding-box marker without text content
                merged_regions.append({
                    "frame_id": frame.frame_id,
                    "sequence_no": seq_no,
                    "type": "diagram",
                    "content": None,
                    "bbox": region.bbox,
                    "confidence": None,
                })
                continue

            if not region.content or not region.content.strip():
                continue

            # De-duplicate: skip if > 85% token Jaccard overlap with any kept region
            if _is_near_duplicate(region.content, seen_texts, threshold=0.85):
                continue

            seen_texts.append(region.content)
            merged_regions.append({
                "frame_id": frame.frame_id,
                "sequence_no": seq_no,
                "type": region.type,
                "content": region.content,
                "bbox": region.bbox,
                "confidence": region.confidence,
            })

    merged_text = _format_as_markdown(merged_regions)

    logger.info(
        "Session %s merge: %d/%d frames, %d unique regions",
        session_id, processed, len(frame_results), len(merged_regions),
    )

    return SessionMergeResult(
        session_id=session_id,
        merged_text=merged_text,
        regions=merged_regions,
        frame_count=len(frame_results),
        processed_frames=processed,
    )


# ---------------------------------------------------------------------------
# Merge helpers
# ---------------------------------------------------------------------------

def _token_jaccard(a: str, b: str) -> float:
    """Token-level Jaccard similarity (set-based, case-insensitive)."""
    ta = set(a.lower().split())
    tb = set(b.lower().split())
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _is_near_duplicate(text: str, existing: list[str], threshold: float = 0.85) -> bool:
    for candidate in existing:
        if _token_jaccard(text, candidate) >= threshold:
            return True
    return False


def _format_as_markdown(regions: list[dict]) -> str:
    """
    Format de-duplicated regions as structured Markdown.

    Ordering within each sequence group:
      heading → formula → list → text → (diagrams skipped in text)

    Headings get ## prefix, formulas are indented with 4 spaces,
    list items get leading -, plain text flows as paragraphs.
    """
    _TYPE_ORDER = {"heading": 0, "formula": 1, "list": 2, "text": 3}

    text_regions = [r for r in regions if r["type"] != "diagram" and r.get("content")]

    sorted_regions = sorted(
        text_regions,
        key=lambda r: (r["sequence_no"], _TYPE_ORDER.get(r["type"], 4)),
    )

    lines: list[str] = []
    last_type: str | None = None

    for r in sorted_regions:
        t = r["type"]
        content = r["content"]

        if t == "heading":
            if lines:
                lines.append("")  # blank line before heading
            lines.append(f"## {content}")
            lines.append("")
        elif t == "formula":
            lines.append(f"    {content}")
        elif t == "list":
            # If content already has a bullet, strip it to normalise
            clean = content.lstrip("•-*–0123456789.):\t ")
            lines.append(f"- {clean}")
        else:
            if last_type == "text":
                lines[-1] = lines[-1] + " " + content  # same paragraph
            else:
                lines.append(content)

        last_type = t

    return "\n".join(lines).strip()
