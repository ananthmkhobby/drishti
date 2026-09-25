import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, File, Form, UploadFile, BackgroundTasks
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.dependencies import CurrentTeacher, DB
from app.exceptions import ACIError
from app.models.session import Session
from app.models.frame import Frame
from app.models.ocr_result import OCRResult
from app.models.job import Job
from app.services import storage_service, ocr_service, sync_service
from app.schemas.frame import (
    FrameUploadResponse,
    FrameResponse,
    FrameListResponse,
    OCRResultResponse,
    OCRRegion,
)
from app.config import get_settings

router = APIRouter(tags=["Frames"])

_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/jpg"}


@router.post("/sessions/{session_id}/frames", status_code=202, response_model=FrameUploadResponse)
async def upload_frame(
    session_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: DB,
    _: CurrentTeacher,
    image: UploadFile = File(...),
    captured_at: str = Form(...),
    sequence_no: int = Form(...),
    local_frame_id: str = Form(...),
    device_fingerprint: str | None = Form(None, description="Stable device ID for sync tracking"),
):
    settings = get_settings()

    # 1. Validate session
    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)
    # "ai_complete" is a status AI generation sets automatically the moment
    # ANY output (notes, quiz, whatever) has been generated at least once —
    # it does NOT mean the teacher is done capturing. Before this fix, a
    # single "generate my notes" mid-lecture (voice or the on-screen button)
    # flipped the session to ai_complete and every capture after that point
    # was rejected here — the sync engine treats a 4xx as permanent and
    # never retries, so those photos were silently lost with only a small,
    # easy-to-miss badge as any indication (confirmed 2026-09-22, reported
    # as "capture isn't pushing to OCR"). Only a genuinely-ended session
    # (status="completed", set explicitly via end_session) should actually
    # block new captures.
    if session.status not in ("active", "ai_complete"):
        raise ACIError("SESSION_NOT_ACTIVE", "Can only upload frames to an active session", 400)

    # 2. Validate image type and size
    if image.content_type not in _ALLOWED_CONTENT_TYPES:
        raise ACIError("INVALID_IMAGE_TYPE", "Only JPEG and PNG images are accepted", 400)

    image_bytes = await image.read()
    size_kb = len(image_bytes) / 1024
    if size_kb > settings.max_frame_size_mb * 1024:
        raise ACIError("IMAGE_TOO_LARGE", f"Image must be under {settings.max_frame_size_mb}MB", 400)

    if session.frame_count >= settings.max_frames_per_session:
        raise ACIError(
            "FRAME_LIMIT_REACHED",
            f"Session has reached the maximum of {settings.max_frames_per_session} frames",
            400,
        )

    # 3. Parse captured_at
    try:
        captured_dt = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError:
        raise ACIError("INVALID_TIMESTAMP", "captured_at must be a valid ISO 8601 timestamp", 400)

    # 4. Persist image
    image_path = await storage_service.save_frame(session_id, local_frame_id, image_bytes)

    # 5. Create frame record
    frame = Frame(
        id=uuid.uuid4(),
        local_frame_id=local_frame_id,
        session_id=session_id,
        sequence_no=sequence_no,
        image_path=image_path,
        image_size_kb=int(size_kb),
        captured_at=captured_dt,
        ocr_status="pending",
    )

    try:
        db.add(frame)
        session.frame_count = (session.frame_count or 0) + 1
        await db.flush()

        # 6. Create OCR job record
        job = Job(
            id=uuid.uuid4(),
            job_type="ocr_processing",
            session_id=session_id,
            frame_id=frame.id,
            status="queued",
        )
        db.add(job)

        # Record frame upload in server-side sync queue (if device is identified)
        if device_fingerprint:
            session_teacher = session.teacher_id
            await sync_service.record_frame_upload(
                frame_id=frame.id,
                session_id=session_id,
                local_frame_id=local_frame_id,
                teacher_id=session_teacher,
                device_fingerprint=device_fingerprint,
                db=db,
            )

        await db.commit()
        await db.refresh(frame)
    except IntegrityError:
        await db.rollback()
        raise ACIError(
            "DUPLICATE_FRAME",
            "A frame with this local_frame_id already exists for this session",
            409,
        )

    # 7. Queue placeholder OCR (runs after response is sent)
    background_tasks.add_task(_run_ocr_background, frame.id)

    return FrameUploadResponse(
        frame_id=frame.id,
        status="queued",
        message="Frame queued for processing",
    )


@router.get("/sessions/{session_id}/frames", response_model=FrameListResponse)
async def list_frames(session_id: uuid.UUID, db: DB, _: CurrentTeacher):
    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    rows = (
        await db.execute(
            select(Frame)
            .where(Frame.session_id == session_id)
            .order_by(Frame.sequence_no)
        )
    ).scalars().all()

    return FrameListResponse(
        frames=[FrameResponse.from_orm(f) for f in rows],
        total=len(rows),
    )


@router.get("/sessions/{session_id}/frames/{frame_id}/image")
async def get_frame_image(session_id: uuid.UUID, frame_id: uuid.UUID, db: DB, _: CurrentTeacher):
    """
    Serve the stored frame image.  If privacy blur was applied during OCR,
    the stored file will already be the blurred version.
    """
    frame = await db.get(Frame, frame_id)
    if not frame or str(frame.session_id) != str(session_id):
        raise ACIError("FRAME_NOT_FOUND", "Frame not found", 404)
    if not frame.image_path:
        raise ACIError("IMAGE_NOT_FOUND", "No image stored for this frame", 404)
    try:
        from app.services.storage_service import load_frame_bytes
        image_bytes = await load_frame_bytes(frame.image_path)
        return Response(
            content=image_bytes,
            media_type="image/jpeg",
            # no-store: the image file is mutated once (original → blurred after OCR).
            # The frontend appends ?v=done as a cache-buster after OCR completes,
            # so this ensures the browser always fetches the blurred version.
            headers={"Cache-Control": "no-store"},
        )
    except (FileNotFoundError, OSError):
        raise ACIError("IMAGE_NOT_FOUND", "Image file not found on server", 404)


@router.get("/sessions/{session_id}/frames/{frame_id}/diagrams/{index}/image")
async def get_frame_diagram_image(
    session_id: uuid.UUID, frame_id: uuid.UUID, index: int, db: DB, _: CurrentTeacher,
):
    """Serve a cropped board-diagram image extracted from this frame's OCR pass."""
    frame = await db.get(Frame, frame_id)
    if not frame or str(frame.session_id) != str(session_id):
        raise ACIError("FRAME_NOT_FOUND", "Frame not found", 404)

    result = await db.execute(select(OCRResult).where(OCRResult.frame_id == frame_id))
    ocr = result.scalar_one_or_none()
    diagrams = (ocr.structured_json or {}).get("diagrams") if ocr and ocr.structured_json else None
    if not diagrams or index < 0 or index >= len(diagrams):
        raise ACIError("DIAGRAM_NOT_FOUND", "Diagram not found", 404)

    try:
        from app.services.storage_service import load_frame_bytes
        image_bytes = await load_frame_bytes(diagrams[index]["image_path"])
        return Response(
            content=image_bytes,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=3600"},
        )
    except (FileNotFoundError, OSError):
        raise ACIError("IMAGE_NOT_FOUND", "Diagram image not found on server", 404)


@router.get("/frames/{frame_id}/ocr", response_model=OCRResultResponse)
async def get_frame_ocr(frame_id: uuid.UUID, db: DB, _: CurrentTeacher):
    frame = await db.get(Frame, frame_id)
    if not frame:
        raise ACIError("FRAME_NOT_FOUND", "No frame found with the given ID", 404)

    if frame.ocr_status == "pending":
        raise ACIError("OCR_NOT_READY", "OCR processing has not started yet", 404)
    if frame.ocr_status == "processing":
        raise ACIError("OCR_IN_PROGRESS", "OCR is currently processing — check back shortly", 404)
    if frame.ocr_status == "failed":
        raise ACIError("OCR_FAILED", "OCR processing failed for this frame", 500)

    ocr = await ocr_service.get_ocr_result(frame_id, db)
    if not ocr:
        raise ACIError("OCR_RESULT_NOT_FOUND", "OCR result not available yet", 404)

    regions = []
    if ocr.structured_json and "regions" in ocr.structured_json:
        for r in ocr.structured_json["regions"]:
            regions.append(
                OCRRegion(
                    type=r.get("type", "text"),
                    bbox=r.get("bbox"),
                    content=r.get("content"),
                    confidence=r.get("confidence"),
                )
            )

    sj = ocr.structured_json or {}
    privacy_blurred        = int(sj.get("privacy_blurred", 0) or 0)
    board_type             = str(sj.get("board_type", "chalkboard"))
    board_confidence       = float(sj.get("board_confidence", 0.0))
    board_detection_method = str(sj.get("board_detection_method", "fallback"))

    return OCRResultResponse(
        frame_id=frame_id,
        ocr_text=ocr.raw_text,
        confidence=ocr.confidence,
        regions=regions,
        engine_used=ocr.engine_used,
        processed_at=ocr.created_at,
        privacy_blurred=privacy_blurred,
        board_type=board_type,
        board_confidence=board_confidence,
        board_detection_method=board_detection_method,
    )


@router.post("/frames/{frame_id}/ocr/retry", status_code=202)
async def retry_frame_ocr(
    frame_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: DB,
    _: CurrentTeacher,
):
    frame = await db.get(Frame, frame_id)
    if not frame:
        raise ACIError("FRAME_NOT_FOUND", "No frame found with the given ID", 404)
    if frame.ocr_status == "processing":
        raise ACIError("OCR_IN_PROGRESS", "OCR is already running for this frame", 409)

    frame.ocr_status = "pending"
    await db.commit()
    background_tasks.add_task(_run_ocr_background, frame_id)
    return {"queued": True, "frame_id": str(frame_id)}


async def _run_ocr_background(frame_id: uuid.UUID):
    """Background task: run OCR on a frame after upload response is sent."""
    import logging as _logging
    _logger = _logging.getLogger(__name__)
    from app.database import _get_session_factory
    from app.services.event_service import emit as emit_event
    factory = _get_session_factory()
    async with factory() as db:
        try:
            await ocr_service.run_ocr_for_frame(frame_id, db)
            # Emit event so clients can poll for completion
            from app.models.frame import Frame as _Frame
            frame = await db.get(_Frame, frame_id)
            if frame:
                await emit_event(db, "OCR_DONE", session_id=frame.session_id,
                                 payload={"frame_id": str(frame_id)})
        except Exception:
            # Log full traceback so "last frame stuck" is diagnosable
            _logger.exception("Background OCR failed for frame %s", frame_id)
            # Attempt to mark the frame as failed so the UI doesn't spin forever
            try:
                from app.models.frame import Frame as _Frame
                frame = await db.get(_Frame, frame_id)
                if frame and frame.ocr_status not in ("done", "failed"):
                    frame.ocr_status = "failed"
                    await db.commit()
            except Exception:
                pass
