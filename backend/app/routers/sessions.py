import uuid
import logging
from datetime import datetime, timezone
from typing import Annotated
from fastapi import APIRouter, File, Header, Query, Response, UploadFile
from sqlalchemy import select, func, delete as sa_delete
from sqlalchemy.exc import IntegrityError

from app.dependencies import CurrentTeacher, DB
from app.exceptions import ACIError
from app.models.session import Session
from app.models.frame import Frame
from app.models.ocr_result import OCRResult
from app.schemas.session import (
    SessionCreate,
    SessionUpdate,
    SessionCreateResponse,
    SessionResponse,
    SessionListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["Sessions"])


@router.post("", status_code=201, response_model=SessionCreateResponse)
async def create_session(
    body: SessionCreate,
    db: DB,
    _: CurrentTeacher,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    # Idempotency: if a session with this UUID already exists, return it as-is.
    # This covers the offline-create replay case: the sync engine retries the
    # POST after reconnect and must receive the same session_id it used offline.
    session_id = body.client_session_id or uuid.uuid4()

    if idempotency_key:
        try:
            key_uuid = uuid.UUID(idempotency_key)
            existing = await db.get(Session, key_uuid)
            if existing:
                return SessionCreateResponse(
                    session_id=existing.id,
                    status=existing.status,
                    created_at=existing.created_at,
                )
            # Use the idempotency key as the session UUID if no client_session_id given
            if not body.client_session_id:
                session_id = key_uuid
        except ValueError:
            pass  # malformed key — generate a fresh UUID

    now = datetime.now(timezone.utc)
    # Deliberately left None when not given, rather than an auto-generated
    # placeholder like "Grade 7 · Sep 10" — that placeholder used to count
    # as "already set" and silently block the real topic OCR would have
    # detected from the first photo (see _detect_subject_and_topic in
    # ocr_service.py). A still-blank title after capture just means the
    # board hasn't revealed a clear topic yet, which is honest; a fake
    # placeholder masquerading as a real one is worse than that.
    title = body.title or None

    session = Session(
        id=session_id,
        teacher_id=body.teacher_id,
        classroom_id=body.classroom_id,
        local_session_id=body.local_session_id,
        subject=body.subject,
        grade=body.grade,
        title=title,
        instructor_name=body.instructor_name,
        board_type=body.board_type,
        capture_mode=body.capture_mode,
        capture_interval_sec=body.capture_interval_sec,
        status="active",
        frame_count=0,
        sync_status="pending",
        started_at=now,
    )
    try:
        db.add(session)
        await db.commit()
        await db.refresh(session)
    except IntegrityError:
        await db.rollback()
        # Race condition — another request created the same session. Return it.
        existing = await db.get(Session, session_id)
        if existing:
            return SessionCreateResponse(
                session_id=existing.id,
                status=existing.status,
                created_at=existing.created_at,
            )
        raise ACIError("DUPLICATE_SESSION", "A session with this local_session_id already exists", 409)

    return SessionCreateResponse(
        session_id=session.id,
        status=session.status,
        created_at=session.created_at,
    )


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    db: DB,
    _: CurrentTeacher,
    teacher_id: uuid.UUID | None = Query(None),
    from_date: datetime | None = Query(None, alias="from"),
    to_date: datetime | None = Query(None, alias="to"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    q = select(Session).where(Session.deleted_at.is_(None))
    if teacher_id:
        q = q.where(Session.teacher_id == teacher_id)
    if from_date:
        q = q.where(Session.created_at >= from_date)
    if to_date:
        q = q.where(Session.created_at <= to_date)

    total_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(total_q)).scalar_one()

    rows = (await db.execute(q.order_by(Session.created_at.desc()).limit(limit).offset(offset))).scalars().all()

    return SessionListResponse(
        sessions=[SessionResponse.from_orm(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: uuid.UUID, db: DB, _: CurrentTeacher):
    session = await db.get(Session, session_id)
    if not session or session.deleted_at is not None:
        raise ACIError("SESSION_NOT_FOUND", f"Session {session_id} not found", 404)
    return SessionResponse.from_orm(session)


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(session_id: uuid.UUID, body: SessionUpdate, db: DB, _: CurrentTeacher):
    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", f"Session {session_id} not found", 404)

    if body.status is not None:
        session.status = body.status
        if body.status == "completed" and session.completed_at is None:
            session.completed_at = datetime.now(timezone.utc)

    if body.sync_status is not None:
        session.sync_status = body.sync_status

    if body.title is not None:
        session.title = body.title

    if body.subject is not None:
        session.subject = body.subject

    if body.instructor_name is not None:
        session.instructor_name = body.instructor_name

    await db.commit()
    await db.refresh(session)
    return SessionResponse.from_orm(session)


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: uuid.UUID, db: DB, _: CurrentTeacher):
    """
    Soft delete: marks the session as deleted so it disappears from every
    listing and lookup, but keeps the row, its frames/OCR/AI output data, and
    the stored image files on disk — nothing is actually removed. Deleting
    a class's worth of captured work is not something a misheard voice
    command or a stray tap should be able to make unrecoverable.
    """
    session = await db.get(Session, session_id)
    if not session or session.deleted_at is not None:
        raise ACIError("SESSION_NOT_FOUND", f"Session {session_id} not found", 404)

    session.deleted_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info("Session %s soft-deleted", session_id)
    return Response(status_code=204)


@router.post("/{session_id}/calibrate", response_model=SessionResponse)
async def calibrate_board_roi(
    session_id: uuid.UUID,
    db: DB,
    _: CurrentTeacher,
    image: UploadFile = File(...),
):
    """
    Auto-detect the board region from a calibration photo and store the
    4 corner points on the session.  Future frames skip per-frame detection
    and use these stored corners for perspective warp directly.

    POST multipart/form-data with field `image` (JPEG/PNG).
    Returns the updated session with board_roi populated.
    """
    import numpy as _np
    import cv2 as _cv2
    from app.ocr.board_detector import detect_board

    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    raw = await image.read()
    arr = _np.frombuffer(raw, _np.uint8)
    bgr = _cv2.imdecode(arr, _cv2.IMREAD_COLOR)
    if bgr is None:
        raise ACIError("INVALID_IMAGE", "Could not decode calibration image", 400)

    board = detect_board(bgr)
    if not board.found or board.corners is None:
        raise ACIError(
            "BOARD_NOT_DETECTED",
            "No clear rectangular board boundary found — ensure the full board is visible "
            "and well-lit, then try again.",
            422,
        )

    # Store corners as [[x,y], [x,y], [x,y], [x,y]] (TL, TR, BR, BL)
    session.board_roi = board.corners.tolist()
    await db.commit()
    await db.refresh(session)
    return SessionResponse.from_orm(session)


@router.post("/{session_id}/reprocess-ocr", status_code=202)
async def reprocess_ocr(session_id: uuid.UUID, db: DB, _: CurrentTeacher):
    """
    Re-run OCR on ALL frames in a session using the latest OCR pipeline.

    Steps:
      1. Delete existing OCRResult rows for all frames.
      2. Reset every frame's ocr_status to "pending".
      3. Queue OCR background tasks for all frames.

    Useful when the OCR engine has been improved and you want to extract
    better text from already-uploaded frames.

    Returns: { queued: N, session_id: ... }
    """
    from fastapi import BackgroundTasks as _BT  # noqa: F401
    from app.services.ocr_service import run_ocr_for_frame

    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    # Load all frames for this session
    frames_result = await db.execute(
        select(Frame).where(Frame.session_id == session_id).order_by(Frame.sequence_no)
    )
    frames = frames_result.scalars().all()
    if not frames:
        return {"queued": 0, "session_id": str(session_id), "message": "No frames found"}

    frame_ids = [f.id for f in frames]

    # Delete existing OCR results
    await db.execute(
        sa_delete(OCRResult).where(OCRResult.frame_id.in_(frame_ids))
    )

    # Reset all frames to pending
    for frame in frames:
        frame.ocr_status = "pending"

    # Reset session status so it can be re-generated after OCR
    if session.status == "ai_complete":
        session.status = "completed"

    await db.commit()

    # Queue OCR background tasks for each frame (non-blocking)
    import asyncio as _asyncio

    async def _run_ocr_bg(fid: uuid.UUID):
        from app.database import _get_session_factory
        factory = _get_session_factory()
        async with factory() as bg_db:
            try:
                await run_ocr_for_frame(fid, bg_db)
            except Exception:
                logger.exception("Reprocess OCR failed for frame %s", fid)

    for fid in frame_ids:
        _asyncio.create_task(_run_ocr_bg(fid))

    logger.info(
        "Reprocess OCR queued for %d frames in session %s",
        len(frame_ids), session_id,
    )
    return {
        "queued": len(frame_ids),
        "session_id": str(session_id),
        "message": f"OCR reprocessing queued for {len(frame_ids)} frame(s). "
                   "Check frame statuses — they will update as OCR completes.",
    }
