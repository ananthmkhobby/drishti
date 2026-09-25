"""
OCR service — orchestrates the full pipeline for a single frame.

Calls into app.ocr (modular pipeline):
  image_preprocessor → board_detector → ocr_engine → ocr_service

Falls back to a lightweight placeholder result when OCR engines
(paddleocr / tesseract) are not installed — this keeps unit tests
and local development working without the heavy ML dependencies.
"""

from __future__ import annotations

import asyncio
import uuid
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.frame import Frame
from app.models.session import Session
from app.models.ocr_result import OCRResult
from app.services import storage_service
from app.services.storage_service import load_frame_bytes, save_frame

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Subject/topic auto-detection — lets a teacher start capturing immediately
# with no upfront form, the board content itself supplies subject + topic.
# ---------------------------------------------------------------------------

_MIN_OCR_CHARS_FOR_DETECTION = 20  # a couple of words isn't enough to guess a subject from

_DETECT_PROMPT = """You will be shown text transcribed from a classroom board. \
Identify the SUBJECT (a short school-subject name, e.g. "Physics", "Mathematics", \
"Chemistry", "English", "History") and a short TOPIC title for what's being \
taught (e.g. "Newton's Laws of Motion", "Photosynthesis", "Quadratic Equations").

Output ONLY a JSON object: {"subject": "...", "title": "..."}
If you genuinely cannot tell from the text, use "" for that field — never guess \
wildly. Keep "title" under 8 words."""


async def _detect_subject_and_topic(ocr_text: str, api_key: str) -> dict | None:
    """
    One cheap text-only call (no image — OCR already ran) to fill in subject/
    topic from board content, so a teacher never has to type them upfront.
    Returns None on any failure — caller treats that as "leave it unset",
    never as a reason to fail the OCR pipeline itself.
    """
    if not api_key or len(ocr_text.strip()) < _MIN_OCR_CHARS_FOR_DETECTION:
        return None
    try:
        from openai import AsyncOpenAI
        import json as _json
        import re as _re

        client = AsyncOpenAI(api_key=api_key)
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            timeout=15,
            messages=[
                {"role": "system", "content": _DETECT_PROMPT},
                {"role": "user", "content": ocr_text[:2000]},
            ],
        )
        content = resp.choices[0].message.content or ""
        match = _re.search(r"\{.*\}", content, _re.DOTALL)
        if not match:
            return None
        data = _json.loads(match.group(0))
        subject = str(data.get("subject", "")).strip()
        title = str(data.get("title", "")).strip()
        if not subject and not title:
            return None
        return {"subject": subject or None, "title": title or None}
    except Exception as exc:
        logger.info("Subject/topic auto-detect failed (non-fatal): %s", exc)
        return None


# ---------------------------------------------------------------------------
# Main entry point (called by background task / Celery worker)
# ---------------------------------------------------------------------------

async def run_ocr_for_frame(frame_id: uuid.UUID, db: AsyncSession) -> OCRResult:
    """
    Run the full OCR pipeline on a frame and persist the result.

    Steps:
      1. Load Frame + parent Session from DB
      2. Read image bytes from storage (local fs or S3)
      3. Run process_frame() from app.ocr
      4. Persist OCRResult row
      5. Update frame.ocr_status
    """
    frame = await db.get(Frame, frame_id)
    if not frame:
        raise ValueError(f"Frame {frame_id} not found")

    # Get board_type and calibrated board_roi from the parent session
    session = await db.get(Session, frame.session_id)
    board_type = session.board_type if session else "chalkboard"
    board_roi  = session.board_roi  if session else None   # calibrated corner list or None
    subject    = (session.subject if session else None) or "General"
    grade      = (session.grade if session else None) or "Grade 8"
    # Captured before anything below expires the ORM object's attributes —
    # this is what decides whether to auto-detect subject/topic from this
    # frame's OCR further down. A teacher who DID set these (via the form,
    # or a prior auto-detect on an earlier frame) always wins; this only
    # fills in genuinely blank fields.
    session_needs_subject = session is not None and not session.subject
    session_needs_title   = session is not None and not session.title

    # Capture attributes that will be expired after db.commit()
    # (SQLAlchemy 2.0 async: non-PK columns expire on commit by default)
    image_path        = frame.image_path
    frame_session_id  = frame.session_id
    frame_local_id    = frame.local_frame_id

    # Mark frame as processing
    frame.ocr_status = "processing"
    await db.commit()

    # Load image bytes (using captured path — frame.image_path is expired now)
    if not image_path:
        logger.warning("Frame %s has no image_path — using placeholder OCR", frame_id)
        return await _save_placeholder(frame_id, db, reason="no_image_path")

    try:
        image_bytes = await load_frame_bytes(image_path)
    except FileNotFoundError:
        logger.error("Image file not found for frame %s: %s", frame_id, image_path)
        return await _save_error(frame, db, "image_file_not_found")
    except Exception as exc:
        logger.error("Failed to load image for frame %s: %s", frame_id, exc)
        return await _save_error(frame, db, str(exc))

    # Run pipeline — import here to keep startup fast when OCR not installed.
    # process_frame() is synchronous and can block for a long time (board
    # detection / vision calls do network I/O with timeouts up to 180s) —
    # calling it directly here would freeze the ONE shared event loop for
    # that whole duration, so every other frame's background task (queued
    # via FastAPI BackgroundTasks on the same loop) just sits at "pending"
    # until it's done. asyncio.to_thread() runs it on a worker thread so
    # concurrently-uploaded frames' OCR can actually run concurrently
    # instead of queueing behind whichever frame happened to go first.
    try:
        from app.ocr.ocr_service import process_frame
        ocr_result = await asyncio.to_thread(
            process_frame,
            image_bytes, str(frame_id), board_type, board_roi=board_roi,
            subject=subject, grade=grade,
        )
    except ImportError:
        logger.warning("app.ocr not importable (cv2 / numpy missing) — using placeholder")
        return await _save_placeholder(frame_id, db, reason="ocr_module_unavailable")
    except Exception as exc:
        logger.exception("Unexpected OCR error for frame %s", frame_id)
        return await _save_error(frame, db, str(exc))

    # Privacy: if blur was applied, overwrite the stored file with the blurred version.
    # This ensures the image served from disk never contains unblurred faces.
    if ocr_result.privacy_blurred > 0 and ocr_result.blurred_image_bytes:
        try:
            await save_frame(frame_session_id, frame_local_id, ocr_result.blurred_image_bytes)
            logger.info(
                "Privacy: blurred image saved for frame %s (%d region(s))",
                frame_id, ocr_result.privacy_blurred,
            )
        except Exception as exc:
            logger.warning("Privacy: failed to overwrite stored image for frame %s: %s", frame_id, exc)

    # Handle errors from the pipeline
    if ocr_result.error:
        reason = ocr_result.error

        # Graceful fallbacks — produce a placeholder result rather than marking failed:
        #   skipped_invalid: frame too small / too dark / blurry (common in tests + edge-cases)
        #   No OCR engine: engines not installed (dev / test environment)
        #   Failed to decode image: corrupt bytes
        if (
            reason.startswith("skipped_invalid:")
            or "No OCR engine" in reason
            or "Failed to decode" in reason
        ):
            log_level = logger.debug if reason.startswith("skipped_invalid:") else logger.warning
            log_level("Frame %s using placeholder: %s", frame_id, reason)
            return await _save_placeholder(
                frame_id, db, reason=reason,
                privacy_blurred=ocr_result.privacy_blurred,
            )

        # Hard failure — mark frame as failed so the dashboard can surface it
        return await _save_error(frame, db, reason)

    # Persist any cropped diagram images this frame produced, alongside their
    # correctness validation. Stored under the session's diagrams/ subfolder,
    # served back via GET /sessions/{id}/frames/{frame_id}/diagrams/{index}/image.
    diagrams_out: list[dict] = []
    for idx, d in enumerate(ocr_result.diagrams):
        try:
            diagram_path = await storage_service.save_diagram(
                frame_session_id, str(frame_id), idx, d["image_bytes"],
            )
        except Exception as exc:
            logger.warning("Failed to save diagram crop for frame %s idx %d: %s", frame_id, idx, exc)
            continue
        diagrams_out.append({
            "index": idx,
            "image_path": diagram_path,
            "description": d["description"],
            "validation": d["validation"],
        })

    # Persist result
    structured_json = {
        "regions": [
            {
                "type": r.type,
                "content": r.content,
                "bbox": r.bbox,
                "confidence": r.confidence,
                "engine": r.engine,
            }
            for r in ocr_result.regions
        ],
        "needs_review": ocr_result.needs_review,
        "privacy_blurred": ocr_result.privacy_blurred,
        # Board detection metadata — exposed in the OCR API response
        "board_type": ocr_result.board_type,
        "board_confidence": round(ocr_result.board_confidence, 3),
        "board_detection_method": ocr_result.board_detection_method,
        # Cropped board diagrams + correctness validation (see crop_and_validate_diagrams)
        "diagrams": diagrams_out,
    }

    ocr = OCRResult(
        id=uuid.uuid4(),
        frame_id=frame_id,
        raw_text=ocr_result.raw_text,
        structured_json=structured_json,
        confidence=ocr_result.confidence,
        engine_used=ocr_result.engine_used,
        processing_ms=ocr_result.processing_ms,
    )
    db.add(ocr)

    # Auto-fill subject/topic from what's actually on the board, so a
    # teacher can start capturing immediately with no upfront form and
    # still end up with a labelled session — only touches fields that are
    # genuinely still blank (session_needs_subject/title, captured before
    # this function's earlier commit expired the ORM object's attributes).
    if (session_needs_subject or session_needs_title) and ocr_result.raw_text:
        from app.config import get_settings
        detected = await _detect_subject_and_topic(ocr_result.raw_text, get_settings().openai_api_key or "")
        if detected and session is not None:
            if session_needs_subject and detected.get("subject"):
                session.subject = detected["subject"]
            if session_needs_title and detected.get("title"):
                session.title = detected["title"]

    frame.ocr_status = "done"
    await db.commit()
    await db.refresh(ocr)

    logger.info(
        "OCR complete frame=%s engine=%s conf=%.3f regions=%d",
        frame_id, ocr_result.engine_used, ocr_result.confidence, len(ocr_result.regions),
    )
    return ocr


# ---------------------------------------------------------------------------
# Legacy name kept for backward compat with existing Celery worker stubs
# ---------------------------------------------------------------------------

async def run_placeholder_ocr(frame_id: uuid.UUID, db: AsyncSession) -> OCRResult:
    """Deprecated: use run_ocr_for_frame(). Kept for Celery worker backward compat."""
    return await run_ocr_for_frame(frame_id, db)


async def get_ocr_result(frame_id: uuid.UUID, db: AsyncSession) -> OCRResult | None:
    """Fetch an existing OCRResult for a frame."""
    result = await db.execute(
        select(OCRResult).where(OCRResult.frame_id == frame_id)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Session-level merge (called after all frames in a session are processed)
# ---------------------------------------------------------------------------

async def merge_session_ocr(session_id: uuid.UUID, db: AsyncSession) -> dict:
    """
    Merge all done OCR results for a session into a single document.
    Returns the SessionMergeResult as a dict suitable for storing in ai_outputs.
    """
    from sqlalchemy import select as sa_select
    from app.models.frame import Frame
    from app.models.ocr_result import OCRResult as OCRResultModel
    from app.ocr.ocr_engine import FrameOCRResult, TextRegion
    from app.ocr.ocr_service import merge_session_frames

    # Load all done frames and their OCR results
    stmt = (
        sa_select(Frame, OCRResultModel)
        .join(OCRResultModel, OCRResultModel.frame_id == Frame.id, isouter=True)
        .where(Frame.session_id == session_id)
        .where(Frame.ocr_status == "done")
        .order_by(Frame.sequence_no)
    )
    rows = (await db.execute(stmt)).all()

    frame_results: list[FrameOCRResult] = []
    sequence_map: dict[str, int] = {}

    for frame, ocr in rows:
        if ocr is None:
            continue
        regions: list[TextRegion] = []
        if ocr.structured_json and "regions" in ocr.structured_json:
            for r in ocr.structured_json["regions"]:
                regions.append(TextRegion(
                    type=r.get("type", "text"),
                    content=r.get("content"),
                    bbox=r.get("bbox", [0, 0, 0, 0]),
                    confidence=r.get("confidence"),
                    engine=r.get("engine"),
                ))
        frame_results.append(FrameOCRResult(
            frame_id=str(frame.id),
            engine_used=ocr.engine_used or "unknown",
            confidence=ocr.confidence or 0.0,
            regions=regions,
            raw_text=ocr.raw_text or "",
        ))
        sequence_map[str(frame.id)] = frame.sequence_no

    merge = merge_session_frames(frame_results, str(session_id), sequence_map)
    return {
        "session_id": merge.session_id,
        "merged_text": merge.merged_text,
        "regions": merge.regions,
        "frame_count": merge.frame_count,
        "processed_frames": merge.processed_frames,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _placeholder_copy(reason: str) -> tuple[str, str]:
    """(heading, detail) shown to the teacher — tailored to why OCR was skipped,
    since this used to always say "install paddleocr" even when the real cause
    was a blurry photo or a missing image, which was actively misleading."""
    if reason.startswith("skipped_invalid:too_blurry"):
        return ("Photo too blurry", "Hold the camera steady and retake the photo.")
    if reason.startswith("skipped_invalid:too_dark"):
        return ("Photo too dark", "Improve lighting on the board and retake the photo.")
    if reason.startswith("skipped_invalid:board_crop_too_tiny"):
        return ("Board too small in frame", "Move closer to the board and retake the photo.")
    if reason.startswith("skipped_invalid:"):
        return ("Photo not usable", "The image didn't pass quality checks. Retake the photo.")
    if "No OCR engine" in reason:
        return (
            "No OCR engine configured",
            "Set OPENAI_API_KEY on the backend, or install pytesseract/paddleocr.",
        )
    if reason == "ocr_module_unavailable":
        return ("OCR module missing", "Required dependencies (opencv-python, numpy) aren't installed on the server.")
    if reason == "no_image_path":
        return ("Image missing", "No image file was found for this frame.")
    if "Failed to decode" in reason:
        return ("Corrupt image", "The captured image file couldn't be read.")
    return ("OCR unavailable", "Real OCR couldn't run for this frame.")


def _placeholder_regions(reason: str) -> list[dict]:
    heading, detail = _placeholder_copy(reason)
    return [
        {
            "type": "heading",
            "content": heading,
            "bbox": [10, 10, 600, 50],
            "confidence": 0.0,
            "engine": "placeholder",
        },
        {
            "type": "text",
            "content": f"[OCR Placeholder] {detail}",
            "bbox": [10, 60, 600, 300],
            "confidence": 0.0,
            "engine": "placeholder",
        },
    ]


async def _save_placeholder(
    frame_id: uuid.UUID,
    db: AsyncSession,
    reason: str = "placeholder",
    privacy_blurred: int = 0,
) -> OCRResult:
    frame = await db.get(Frame, frame_id)
    heading, detail = _placeholder_copy(reason)
    ocr = OCRResult(
        id=uuid.uuid4(),
        frame_id=frame_id,
        raw_text=f"[OCR Placeholder] {heading}: {detail}",
        structured_json={
            "regions": _placeholder_regions(reason),
            "placeholder": True,
            "reason": reason,
            "privacy_blurred": privacy_blurred,
        },
        confidence=0.0,
        engine_used="placeholder",
        processing_ms=0,
    )
    db.add(ocr)
    if frame:
        frame.ocr_status = "done"
    await db.commit()
    await db.refresh(ocr)
    return ocr


async def _save_error(
    frame: Frame,
    db: AsyncSession,
    error_message: str,
    status: str = "failed",
) -> OCRResult:
    ocr = OCRResult(
        id=uuid.uuid4(),
        frame_id=frame.id,
        raw_text="",
        structured_json={"error": error_message},
        confidence=0.0,
        engine_used="none",
        processing_ms=0,
    )
    db.add(ocr)
    frame.ocr_status = status
    await db.commit()
    await db.refresh(ocr)
    return ocr
