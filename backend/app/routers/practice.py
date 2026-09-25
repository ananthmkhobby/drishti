import uuid
import json
import logging
from fastapi import APIRouter, File, Form, UploadFile, BackgroundTasks
from fastapi.responses import Response
from sqlalchemy import select

from app.dependencies import CurrentTeacher, DB
from app.exceptions import ACIError
from app.models.session import Session
from app.models.ocr_result import OCRResult
from app.models.frame import Frame
from app.models.practice_question import PracticeQuestion
from app.models.practice_station import PracticeStation
from app.models.practice_attempt import PracticeAttempt
from app.models.practice_attempt_summary import PracticeAttemptSummary
from app.models.practice_tutor_message import PracticeTutorMessage
from app.services import storage_service, practice_service
from app.schemas.practice import (
    PracticeQuestionGenerateRequest,
    PracticeQuestionGenerateFromTopicRequest,
    PracticeQuestionUpdate,
    PracticeQuestionResponse,
    PracticeQuestionListResponse,
    PracticeAttemptResponse,
    PracticeAttemptListResponse,
    PracticeAttemptSummaryResponse,
    PracticeAttemptSummaryListResponse,
    PracticeAttemptFeedback,
    PracticeStationCreate,
    PracticeStationUpdate,
    PracticeStationResponse,
    PracticeStationListResponse,
    BatchScanResponse,
    BatchScanResult,
    PracticeChatRequest,
    PracticeChatResponse,
    PracticeTutorTurnResponse,
    StationNotesResponse,
    StationQuizResponse,
)
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Guided Practice"])

_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/jpg"}
# A spoken answer's MediaRecorder blob — matches what ClassroomBrain.tsx /
# VoiceDictateButton.tsx already send elsewhere in this app.
_ALLOWED_AUDIO_CONTENT_TYPES = {"audio/webm", "audio/ogg", "audio/mp4", "audio/wav", "audio/mpeg"}


# ─── Question generation + review ───────────────────────────────────────────


@router.post(
    "/sessions/{session_id}/practice-questions/generate",
    response_model=PracticeQuestionListResponse,
)
async def generate_questions(
    session_id: uuid.UUID,
    body: PracticeQuestionGenerateRequest,
    db: DB,
    _: CurrentTeacher,
):
    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    # Board OCR text this session has accumulated so far — the source
    # material questions are generated from.
    ocr_rows = (
        await db.execute(
            select(OCRResult)
            .join(Frame, Frame.id == OCRResult.frame_id)
            .where(Frame.session_id == session_id)
            .order_by(Frame.sequence_no)
        )
    ).scalars().all()
    ocr_text = "\n\n".join(r.raw_text for r in ocr_rows if r.raw_text)
    source = "board OCR"
    if not ocr_text.strip():
        # Same fallback ai_service.py already uses for notes/quiz/homework —
        # a teacher who uploaded a textbook chapter or concept-notes PDF
        # under the Textbook tab shouldn't have to also photograph a board
        # before guided-practice questions can be generated (reported
        # 2026-09-22: this endpoint was board-OCR-only while every other
        # generation endpoint already had this fallback).
        from app.services.ai_service import _get_textbook_text
        ocr_text = await _get_textbook_text(session_id, db)
        source = "uploaded textbook/concept-notes"
    if not ocr_text.strip():
        raise ACIError(
            "NO_OCR_CONTENT",
            "No board content or uploaded textbook/concept-notes found for this session yet — capture a board photo or upload a PDF under the Textbook tab first.",
            400,
        )
    logger.info("Guided-practice question generation for session %s using %s", session_id, source)

    settings = get_settings()
    drafted = await practice_service.generate_practice_questions(
        session, ocr_text, body.count, settings.openai_api_key or "",
    )
    if not drafted:
        raise ACIError(
            "GENERATION_FAILED",
            "Couldn't generate practice questions right now — try again in a moment.",
            502,
        )

    rows = []
    for d in drafted:
        q = PracticeQuestion(
            session_id=session_id,
            subject=d["subject"],
            topic=d["topic"],
            difficulty=d["difficulty"],
            text=d["text"],
            answer_domain=d["answer_domain"],
            expected_solution_graph=d["expected_solution_graph"],
            final_answer=d["final_answer"],
            known_misconceptions=d["known_misconceptions"],
            source="ai_generated",
            generated_from_ocr_text=ocr_text[:4000],
            status="pending_review",
        )
        db.add(q)
        rows.append(q)

    await db.commit()
    for q in rows:
        await db.refresh(q)

    return PracticeQuestionListResponse(
        questions=[PracticeQuestionResponse.from_orm(q) for q in rows],
        total=len(rows),
    )


@router.post(
    "/sessions/{session_id}/practice-questions/generate-from-topic",
    response_model=PracticeQuestionListResponse,
)
async def generate_questions_from_topic(
    session_id: uuid.UUID,
    body: PracticeQuestionGenerateFromTopicRequest,
    db: DB,
    _: CurrentTeacher,
):
    """
    Same as .../generate, but doesn't need any board content captured
    first — the teacher directly names a subject + chapter/topic and the
    AI writes questions for that, same review/approve flow afterward.
    """
    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    settings = get_settings()
    drafted = await practice_service.generate_practice_questions_from_topic(
        body.subject, body.topic, body.count, settings.openai_api_key or "",
    )
    if not drafted:
        raise ACIError(
            "GENERATION_FAILED",
            "Couldn't generate practice questions right now — try again in a moment.",
            502,
        )

    rows = []
    for d in drafted:
        q = PracticeQuestion(
            session_id=session_id,
            subject=d["subject"],
            topic=d["topic"],
            difficulty=d["difficulty"],
            text=d["text"],
            answer_domain=d["answer_domain"],
            expected_solution_graph=d["expected_solution_graph"],
            final_answer=d["final_answer"],
            known_misconceptions=d["known_misconceptions"],
            source="ai_generated",
            generated_from_ocr_text=f"(typed by teacher, no board capture) subject={body.subject}, topic={body.topic}",
            status="pending_review",
        )
        db.add(q)
        rows.append(q)

    await db.commit()
    for q in rows:
        await db.refresh(q)

    return PracticeQuestionListResponse(
        questions=[PracticeQuestionResponse.from_orm(q) for q in rows],
        total=len(rows),
    )


@router.get("/sessions/{session_id}/practice-questions", response_model=PracticeQuestionListResponse)
async def list_questions(
    session_id: uuid.UUID,
    db: DB,
    _: CurrentTeacher,
    status: str | None = None,
):
    q = select(PracticeQuestion).where(PracticeQuestion.session_id == session_id)
    if status:
        q = q.where(PracticeQuestion.status == status)
    rows = (await db.execute(q.order_by(PracticeQuestion.created_at))).scalars().all()
    return PracticeQuestionListResponse(
        questions=[PracticeQuestionResponse.from_orm(r) for r in rows],
        total=len(rows),
    )


@router.patch("/practice-questions/{question_id}", response_model=PracticeQuestionResponse)
async def update_question(question_id: uuid.UUID, body: PracticeQuestionUpdate, db: DB, _: CurrentTeacher):
    """
    Teacher review/approve screen. A question must be approved here before
    any student attempt can be captured against it — see
    POST .../attempts' ACIError QUESTION_NOT_APPROVED.
    """
    q = await db.get(PracticeQuestion, question_id)
    if not q:
        raise ACIError("QUESTION_NOT_FOUND", "Practice question not found", 404)

    changed = False
    for field in (
        "text", "subject", "topic", "skill_tag", "difficulty", "answer_domain",
        "final_answer", "status",
    ):
        val = getattr(body, field)
        if val is not None:
            setattr(q, field, val)
            changed = True
    if body.expected_solution_graph is not None:
        q.expected_solution_graph = [s.model_dump() for s in body.expected_solution_graph]
        changed = True
    if body.known_misconceptions is not None:
        q.known_misconceptions = [m.model_dump() for m in body.known_misconceptions]
        changed = True
    if changed and body.status is None:
        q.teacher_edited = True

    q.version = q.version + 1 if changed else q.version
    await db.commit()
    await db.refresh(q)
    return PracticeQuestionResponse.from_orm(q)


# ─── Attempts (capture + Gates A-H) ─────────────────────────────────────────


@router.post(
    "/practice-questions/{question_id}/attempts",
    status_code=202,
    response_model=PracticeAttemptResponse,
)
async def create_attempt(
    question_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: DB,
    _: CurrentTeacher,
    image: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
    student_label: str | None = Form(None),
):
    question = await db.get(PracticeQuestion, question_id)
    if not question:
        raise ACIError("QUESTION_NOT_FOUND", "Practice question not found", 404)
    if question.status != "approved":
        raise ACIError(
            "QUESTION_NOT_APPROVED",
            "This question hasn't been approved by a teacher yet — review it before students can attempt it.",
            409,
        )
    image_bytes, audio_bytes = await _read_attempt_media(image, audio)

    attempt = await _persist_attempt(
        db, question, image_bytes, audio_bytes, student_label, station_id=None,
    )
    background_tasks.add_task(_run_attempt_background, attempt.id)
    return PracticeAttemptResponse.from_orm(attempt)


async def _read_attempt_media(
    image: UploadFile | None, audio: UploadFile | None,
) -> tuple[bytes | None, bytes | None]:
    """
    Exactly one of image/audio must be provided — a written capture (photo
    of notebook work) or a spoken answer (for theory/conceptual questions
    with nothing to photograph). Shared by both attempt-creation endpoints.
    """
    if image is not None and audio is not None:
        raise ACIError("AMBIGUOUS_INPUT", "Provide either an image or audio, not both", 400)
    if image is not None:
        if image.content_type not in _ALLOWED_CONTENT_TYPES:
            raise ACIError("INVALID_IMAGE_TYPE", "Only JPEG and PNG images are accepted", 400)
        return await image.read(), None
    if audio is not None:
        if audio.content_type not in _ALLOWED_AUDIO_CONTENT_TYPES:
            raise ACIError("INVALID_AUDIO_TYPE", "Unsupported audio format", 400)
        return None, await audio.read()
    raise ACIError("NO_CAPTURE_PROVIDED", "Provide either an image or audio capture", 400)


async def _persist_attempt(
    db: DB, question: PracticeQuestion, image_bytes: bytes | None, audio_bytes: bytes | None,
    student_label: str | None, station_id: uuid.UUID | None,
) -> PracticeAttempt:
    from datetime import datetime, timezone

    prior_count = (
        await db.execute(
            select(PracticeAttempt).where(PracticeAttempt.question_id == question.id)
        )
    ).scalars().all()
    attempt_no = len(prior_count) + 1
    attempt_id = uuid.uuid4()

    if audio_bytes is not None:
        input_type = "audio"
        image_path = None
        image_size_kb = None
        audio_path = await storage_service.save_practice_attempt_audio(
            question.session_id, str(attempt_id), audio_bytes,
        )
    else:
        input_type = "image"
        audio_path = None
        image_path = await storage_service.save_practice_attempt_image(
            question.session_id, str(attempt_id), image_bytes,
        )
        image_size_kb = int(len(image_bytes) / 1024)

    attempt = PracticeAttempt(
        id=attempt_id,
        question_id=question.id,
        session_id=question.session_id,
        station_id=station_id,
        attempt_no=attempt_no,
        student_label=student_label,
        input_type=input_type,
        image_path=image_path,
        image_size_kb=image_size_kb,
        audio_path=audio_path,
        captured_at=datetime.now(timezone.utc),
        status="processing",
    )
    db.add(attempt)
    await db.commit()
    await db.refresh(attempt)
    return attempt


async def _run_attempt_background(attempt_id: uuid.UUID):
    from app.database import _get_session_factory
    from app.services.event_service import emit as emit_event
    factory = _get_session_factory()
    async with factory() as db:
        try:
            attempt = await practice_service.process_attempt(attempt_id, db)
            await emit_event(
                db, "PRACTICE_ATTEMPT_DONE", session_id=attempt.session_id,
                payload={"attempt_id": str(attempt_id), "question_id": str(attempt.question_id)},
            )
            # Single call site for all three attempt-creation paths (direct,
            # station, batch-scan) that reach this wrapper — bounds the raw
            # history regardless of which of process_attempt's several
            # completion paths (full grading, Gate A rejection, near-
            # duplicate carry-forward) this particular attempt took.
            # Best-effort: a pruning failure shouldn't fail the attempt
            # that just successfully completed.
            try:
                await practice_service.prune_old_attempts_with_summary(
                    db, attempt.question_id, attempt.station_id,
                )
            except Exception:
                logger.exception("Attempt-history pruning failed for question %s", attempt.question_id)
        except Exception:
            logger.exception("Background practice-attempt processing failed for %s", attempt_id)
            try:
                failed = await db.get(PracticeAttempt, attempt_id)
                if failed:
                    failed.status = "failed"
                    failed.error_message = "internal_error"
                    await db.commit()
            except Exception:
                logger.exception("Also failed to mark attempt %s as failed", attempt_id)


@router.get("/practice-attempts/{attempt_id}/image")
async def get_attempt_image(attempt_id: uuid.UUID, db: DB, _: CurrentTeacher):
    attempt = await db.get(PracticeAttempt, attempt_id)
    if not attempt or not attempt.image_path:
        raise ACIError("IMAGE_NOT_FOUND", "No image stored for this attempt", 404)
    try:
        from app.services.storage_service import load_frame_bytes
        image_bytes = await load_frame_bytes(attempt.image_path)
        return Response(content=image_bytes, media_type="image/jpeg")
    except (FileNotFoundError, OSError):
        raise ACIError("IMAGE_NOT_FOUND", "Image file not found on server", 404)


@router.get("/practice-attempts/{attempt_id}/audio")
async def get_attempt_audio(attempt_id: uuid.UUID, db: DB, _: CurrentTeacher):
    attempt = await db.get(PracticeAttempt, attempt_id)
    if not attempt or not attempt.audio_path:
        raise ACIError("AUDIO_NOT_FOUND", "No audio stored for this attempt", 404)
    try:
        from app.services.storage_service import load_frame_bytes
        audio_bytes = await load_frame_bytes(attempt.audio_path)
        return Response(content=audio_bytes, media_type="audio/webm")
    except (FileNotFoundError, OSError):
        raise ACIError("AUDIO_NOT_FOUND", "Audio file not found on server", 404)


@router.get("/practice-attempts/{attempt_id}", response_model=PracticeAttemptResponse)
async def get_attempt(attempt_id: uuid.UUID, db: DB, _: CurrentTeacher):
    attempt = await db.get(PracticeAttempt, attempt_id)
    if not attempt:
        raise ACIError("ATTEMPT_NOT_FOUND", "Practice attempt not found", 404)
    return PracticeAttemptResponse.from_orm(attempt)


@router.get("/practice-questions/{question_id}/attempts", response_model=PracticeAttemptListResponse)
async def list_question_attempts(question_id: uuid.UUID, db: DB, _: CurrentTeacher):
    rows = (
        await db.execute(
            select(PracticeAttempt)
            .where(PracticeAttempt.question_id == question_id)
            .order_by(PracticeAttempt.attempt_no)
        )
    ).scalars().all()
    return PracticeAttemptListResponse(
        attempts=[PracticeAttemptResponse.from_orm(a) for a in rows], total=len(rows),
    )


@router.get("/sessions/{session_id}/practice-attempts", response_model=PracticeAttemptListResponse)
async def list_session_attempts(session_id: uuid.UUID, db: DB, _: CurrentTeacher):
    """Teacher dashboard feed: every attempt across every question in this session."""
    rows = (
        await db.execute(
            select(PracticeAttempt)
            .where(PracticeAttempt.session_id == session_id)
            .order_by(PracticeAttempt.created_at.desc())
        )
    ).scalars().all()
    return PracticeAttemptListResponse(
        attempts=[PracticeAttemptResponse.from_orm(a) for a in rows], total=len(rows),
    )


@router.patch("/practice-attempts/{attempt_id}/feedback", response_model=PracticeAttemptResponse)
async def submit_attempt_feedback(
    attempt_id: uuid.UUID, body: PracticeAttemptFeedback, db: DB, _: CurrentTeacher,
):
    """
    Shadow-mode / pilot data collection (PRD §12): teacher approves or
    rejects the AI's classification+hint for this attempt. Also the
    mechanism for a teacher override — this never changes validation_status
    itself (that stays as evidence of what the AI actually said), it just
    records the teacher's judgment alongside it.
    """
    attempt = await db.get(PracticeAttempt, attempt_id)
    if not attempt:
        raise ACIError("ATTEMPT_NOT_FOUND", "Practice attempt not found", 404)

    attempt.teacher_feedback = body.teacher_feedback
    if body.teacher_override:
        attempt.teacher_override = body.teacher_override.model_dump()
    await db.commit()
    await db.refresh(attempt)
    return PracticeAttemptResponse.from_orm(attempt)


@router.delete("/practice-attempts/{attempt_id}", status_code=204)
async def delete_attempt(attempt_id: uuid.UUID, db: DB, _: CurrentTeacher):
    """
    Permanently removes one attempt and its stored image/audio file — unlike
    the feedback-panel "Clear" action (a client-side view filter that hides
    history locally but leaves it all in the database, so it reappears on
    next load), this actually deletes the row. No undo.
    """
    attempt = await db.get(PracticeAttempt, attempt_id)
    if not attempt:
        return  # already gone — DELETE is idempotent
    await storage_service.delete_blob(attempt.image_path)
    await storage_service.delete_blob(attempt.audio_path)
    await db.delete(attempt)
    await db.commit()


# ─── Stations (per-student/notebook periodic auto-capture) ─────────────────
#
# A station is a persistent capture channel for one student/desk — a device
# is propped over one notebook and left running, auto-capturing on its own
# interval instead of a teacher manually tapping Capture per student. Every
# resulting attempt carries station_id, so the teacher dashboard can group
# an individual student's ongoing work into one "folder" over time.


async def _resolve_station(db: DB, station_id: uuid.UUID) -> PracticeStation:
    station = await db.get(PracticeStation, station_id)
    if not station:
        raise ACIError("STATION_NOT_FOUND", "Practice station not found", 404)
    return station


async def _heal_stale_capturing(db: DB, station: PracticeStation) -> None:
    """
    A station's own device is the only thing that ever sets status back to
    "idle" (the capture page's Back link, or its pagehide beacon) — anything
    that skips both (a killed tab, a crashed browser, the device losing
    power or wifi outright) leaves it reporting "capturing" forever, which
    the teacher dashboard then shows as a permanently-stuck "Pause" button
    (reported 2026-09-22). Self-heals on every read: a station claiming
    "capturing" whose last real capture (or, if it never captured at all,
    whose last status change) is far older than its own interval clearly
    isn't actually running anymore.
    """
    if station.status != "capturing":
        return
    from datetime import datetime, timezone
    last_activity = station.last_capture_at or station.updated_at
    if last_activity is None:
        return
    if last_activity.tzinfo is None:
        last_activity = last_activity.replace(tzinfo=timezone.utc)
    stale_after = max(90, station.capture_interval_sec * 4)
    if (datetime.now(timezone.utc) - last_activity).total_seconds() > stale_after:
        station.status = "idle"
        await db.commit()
        await db.refresh(station)


async def _station_response(db: DB, station: PracticeStation) -> PracticeStationResponse:
    await _heal_stale_capturing(db, station)
    latest = (
        await db.execute(
            select(PracticeAttempt)
            .where(PracticeAttempt.station_id == station.id)
            # created_at, not attempt_no — attempt_no is a PER-QUESTION
            # counter (see _persist_attempt), so if this station's active
            # question was ever reassigned, a brand-new attempt #1 on the
            # new question would sort before an older attempt #7 on the
            # previous one, surfacing a stale "latest" result (confirmed
            # 2026-09-19: a fresh hint wasn't appearing because of exactly
            # this — an older, higher-attempt_no row from a prior question
            # was still winning).
            .order_by(PracticeAttempt.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    question_text = None
    if station.active_question_id:
        q = await db.get(PracticeQuestion, station.active_question_id)
        question_text = q.text if q else None
    return PracticeStationResponse.from_orm(station, latest_attempt=latest, active_question_text=question_text)


@router.post("/sessions/{session_id}/practice-stations", status_code=201, response_model=PracticeStationResponse)
async def create_station(session_id: uuid.UUID, body: PracticeStationCreate, db: DB, _: CurrentTeacher):
    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    if body.active_question_id:
        q = await db.get(PracticeQuestion, body.active_question_id)
        if not q or q.session_id != session_id:
            raise ACIError("QUESTION_NOT_FOUND", "Practice question not found in this session", 404)

    station = PracticeStation(
        session_id=session_id,
        label=body.label,
        active_question_id=body.active_question_id,
        capture_interval_sec=body.capture_interval_sec,
        camera_mount=body.camera_mount,
        status="idle",
    )
    db.add(station)
    await db.commit()
    await db.refresh(station)
    return await _station_response(db, station)


@router.get("/sessions/{session_id}/practice-stations", response_model=PracticeStationListResponse)
async def list_stations(session_id: uuid.UUID, db: DB, _: CurrentTeacher):
    rows = (
        await db.execute(
            select(PracticeStation)
            .where(PracticeStation.session_id == session_id)
            .order_by(PracticeStation.created_at)
        )
    ).scalars().all()
    return PracticeStationListResponse(
        stations=[await _station_response(db, s) for s in rows], total=len(rows),
    )


@router.get("/practice-stations/{station_id}", response_model=PracticeStationResponse)
async def get_station(station_id: uuid.UUID, db: DB, _: CurrentTeacher):
    station = await _resolve_station(db, station_id)
    return await _station_response(db, station)


@router.patch("/practice-stations/{station_id}", response_model=PracticeStationResponse)
async def update_station(station_id: uuid.UUID, body: PracticeStationUpdate, db: DB, _: CurrentTeacher):
    station = await _resolve_station(db, station_id)

    if body.active_question_id is not None:
        q = await db.get(PracticeQuestion, body.active_question_id)
        if not q or q.session_id != station.session_id:
            raise ACIError("QUESTION_NOT_FOUND", "Practice question not found in this session", 404)
        station.active_question_id = body.active_question_id
    if body.label is not None:
        station.label = body.label
    if body.capture_interval_sec is not None:
        station.capture_interval_sec = body.capture_interval_sec
    if body.status is not None:
        station.status = body.status
    if body.teacher_note is not None:
        station.teacher_note = body.teacher_note
    if body.camera_mount is not None:
        station.camera_mount = body.camera_mount

    await db.commit()
    await db.refresh(station)
    return await _station_response(db, station)


@router.delete("/practice-stations/{station_id}", status_code=204)
async def delete_station(station_id: uuid.UUID, db: DB, _: CurrentTeacher):
    station = await db.get(PracticeStation, station_id)
    if not station:
        return  # already gone — DELETE is idempotent

    attempts_result = await db.execute(
        select(PracticeAttempt).where(PracticeAttempt.station_id == station_id)
    )
    for attempt in attempts_result.scalars().all():
        await storage_service.delete_blob(attempt.image_path)
        await storage_service.delete_blob(attempt.audio_path)
        await db.delete(attempt)

    # Tutor-turn images — the PracticeTutorMessage rows themselves cascade
    # on the DB FK, but their on-disk image blobs don't, same as attempts
    # above.
    tutor_msgs_result = await db.execute(
        select(PracticeTutorMessage).where(PracticeTutorMessage.station_id == station_id)
    )
    for msg in tutor_msgs_result.scalars().all():
        if msg.image_path:
            await storage_service.delete_blob(msg.image_path)
        await db.delete(msg)

    await db.delete(station)
    await db.commit()


@router.post(
    "/practice-stations/{station_id}/attempts",
    status_code=202,
    response_model=PracticeAttemptResponse,
)
async def create_station_attempt(
    station_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: DB,
    _: CurrentTeacher,
    image: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
):
    """
    Periodic auto-capture upload from a station's device — no question_id
    in the request, the station's currently-assigned active_question_id
    decides it, so the capturing device never needs to know or re-select it.
    Accepts either a photo (written work) or a spoken answer.
    """
    station = await _resolve_station(db, station_id)
    if not station.active_question_id:
        raise ACIError(
            "NO_ACTIVE_QUESTION",
            "This station has no question assigned yet — pick one from the teacher dashboard first.",
            409,
        )
    question = await db.get(PracticeQuestion, station.active_question_id)
    if not question:
        raise ACIError("QUESTION_NOT_FOUND", "The station's assigned question no longer exists", 404)
    if question.status != "approved":
        raise ACIError("QUESTION_NOT_APPROVED", "This question hasn't been approved by a teacher yet", 409)

    image_bytes, audio_bytes = await _read_attempt_media(image, audio)

    attempt = await _persist_attempt(
        db, question, image_bytes, audio_bytes, station.label, station_id=station.id,
    )

    from datetime import datetime, timezone
    station.last_capture_at = datetime.now(timezone.utc)
    await db.commit()

    background_tasks.add_task(_run_attempt_background, attempt.id)
    return PracticeAttemptResponse.from_orm(attempt)


@router.get("/practice-stations/{station_id}/attempts", response_model=PracticeAttemptListResponse)
async def list_station_attempts(station_id: uuid.UUID, db: DB, _: CurrentTeacher):
    """
    Full timeline for one student's station — the 'folder' detail view.

    Ordered by created_at, not attempt_no — attempt_no only counts
    consecutive attempts WITHIN one question (see _persist_attempt), so a
    station whose active question was ever reassigned would otherwise
    interleave attempts out of true chronological order (a new attempt #1
    on the newly-assigned question sorting before an old attempt #7 on the
    previous one). The frontend's "show the most recent N" panel logic
    relies on this list actually being oldest-to-newest.
    """
    rows = (
        await db.execute(
            select(PracticeAttempt)
            .where(PracticeAttempt.station_id == station_id)
            .order_by(PracticeAttempt.created_at)
        )
    ).scalars().all()

    # Batch-fetch question text for whatever question(s) this station's
    # timeline actually touches — usually one, but a reassignment means it
    # can be several, and each card needs to say which one it's about.
    question_ids = {r.question_id for r in rows}
    question_texts: dict[uuid.UUID, str] = {}
    if question_ids:
        q_rows = (
            await db.execute(select(PracticeQuestion).where(PracticeQuestion.id.in_(question_ids)))
        ).scalars().all()
        question_texts = {q.id: q.text for q in q_rows}

    return PracticeAttemptListResponse(
        attempts=[PracticeAttemptResponse.from_orm(a, question_texts.get(a.question_id)) for a in rows],
        total=len(rows),
    )


@router.get("/practice-stations/{station_id}/attempt-summaries", response_model=PracticeAttemptSummaryListResponse)
async def list_station_attempt_summaries(station_id: uuid.UUID, db: DB, _: CurrentTeacher):
    """
    Consolidated record of whatever's been pruned from this station's raw
    attempt history (see practice_service.prune_old_attempts_with_summary)
    — the "what happened before the last 10" view, since the raw rows and
    images themselves are genuinely gone by the time a batch shows up
    here. Newest batch first.
    """
    rows = (
        await db.execute(
            select(PracticeAttemptSummary)
            .where(PracticeAttemptSummary.station_id == station_id)
            .order_by(PracticeAttemptSummary.created_at.desc())
        )
    ).scalars().all()
    return PracticeAttemptSummaryListResponse(
        summaries=[PracticeAttemptSummaryResponse.model_validate(r) for r in rows],
        total=len(rows),
    )


@router.get("/practice-questions/{question_id}/attempt-summaries", response_model=PracticeAttemptSummaryListResponse)
async def list_question_attempt_summaries(question_id: uuid.UUID, db: DB, _: CurrentTeacher):
    """Same as the station-scoped listing above, but keyed by question —
    useful when reviewing one question's history across every station
    that's ever worked on it, not just one device's timeline."""
    rows = (
        await db.execute(
            select(PracticeAttemptSummary)
            .where(PracticeAttemptSummary.question_id == question_id)
            .order_by(PracticeAttemptSummary.created_at.desc())
        )
    ).scalars().all()
    return PracticeAttemptSummaryListResponse(
        summaries=[PracticeAttemptSummaryResponse.model_validate(r) for r in rows],
        total=len(rows),
    )


@router.post("/practice-stations/{station_id}/ask", response_model=PracticeChatResponse)
async def ask_classroom_brain(station_id: uuid.UUID, body: PracticeChatRequest, db: DB, _: CurrentTeacher):
    """
    A student asking the Classroom Brain about their station's active
    question — synchronous (the student is waiting on a reply live, unlike
    attempt grading which runs in the background and gets polled), scoped
    strictly to that one question via practice_service.answer_question.
    """
    station = await _resolve_station(db, station_id)
    if not station.active_question_id:
        raise ACIError(
            "NO_ACTIVE_QUESTION",
            "This station has no question assigned yet — pick one from the teacher dashboard first.",
            409,
        )
    question = await db.get(PracticeQuestion, station.active_question_id)
    if not question:
        raise ACIError("QUESTION_NOT_FOUND", "The station's assigned question no longer exists", 404)

    settings = get_settings()
    result = await practice_service.answer_question(
        question, body.message,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_brain_model,
        openai_api_key=settings.openai_api_key or "",
        local_enabled=settings.practice_local_llm_enabled,
    )
    return PracticeChatResponse(reply=result["reply"], declined=result["declined"])


@router.post("/practice-stations/{station_id}/generate-notes", response_model=StationNotesResponse)
async def generate_station_notes(station_id: uuid.UUID, db: DB, _: CurrentTeacher):
    """
    The station-scoped voice-command analog of a session's generate_notes
    — "generate notes" said at a student's own station means THIS station's
    attempt history, not the whole class's lecture. Synchronous (no job
    queue): a single station's digest is small enough that there's no
    latency case for the async job machinery generate_notes' session-wide
    version needs.
    """
    await _resolve_station(db, station_id)
    settings = get_settings()
    result = await practice_service.generate_station_notes(
        db, station_id,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_brain_model,
        openai_api_key=settings.openai_api_key or "",
        local_enabled=settings.practice_local_llm_enabled,
    )
    return StationNotesResponse(notes=result["notes"])


@router.post("/practice-stations/{station_id}/generate-quiz", response_model=StationQuizResponse)
async def generate_station_quiz(station_id: uuid.UUID, db: DB, _: CurrentTeacher):
    """Station-scoped analog of generate_quiz — see generate_station_notes above."""
    await _resolve_station(db, station_id)
    settings = get_settings()
    result = await practice_service.generate_station_quiz(
        db, station_id,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_brain_model,
        openai_api_key=settings.openai_api_key or "",
        local_enabled=settings.practice_local_llm_enabled,
    )
    return StationQuizResponse(questions=result["questions"])


@router.post("/practice-stations/{station_id}/tutor-turn", response_model=PracticeTutorTurnResponse)
async def tutor_turn(
    station_id: uuid.UUID,
    db: DB,
    _: CurrentTeacher,
    audio: UploadFile = File(...),
    image: UploadFile | None = File(None),
    history: str = Form("[]"),
):
    """
    One turn of Learning mode's AI Tutor — a live voice+vision conversation,
    grounded in whatever the student's camera is currently pointed at. The
    active question (if any) is included as context but, unlike /ask, a
    tutor conversation doesn't require one — a student can explore a
    concept before a question is even assigned. See
    practice_service.tutor_turn for why this endpoint is otherwise
    stateless (history comes from the client each call).
    """
    station = await _resolve_station(db, station_id)
    question = await db.get(PracticeQuestion, station.active_question_id) if station.active_question_id else None

    try:
        history_turns = json.loads(history)
        if not isinstance(history_turns, list):
            history_turns = []
    except (json.JSONDecodeError, TypeError):
        history_turns = []

    if audio.content_type not in _ALLOWED_AUDIO_CONTENT_TYPES:
        raise ACIError("INVALID_AUDIO_TYPE", "Unsupported audio format", 400)
    audio_bytes = await audio.read()
    image_bytes = None
    if image is not None:
        if image.content_type not in _ALLOWED_CONTENT_TYPES:
            raise ACIError("INVALID_IMAGE_TYPE", "Only JPEG and PNG images are accepted", 400)
        image_bytes = await image.read()

    settings = get_settings()
    result = await practice_service.tutor_turn(
        db, station, question, history_turns, audio_bytes, image_bytes, settings=settings,
    )
    return PracticeTutorTurnResponse(transcript=result["transcript"], reply=result["reply"])


@router.post(
    "/sessions/{session_id}/practice-questions/{question_id}/batch-scan",
    status_code=202,
    response_model=BatchScanResponse,
)
async def batch_scan(
    session_id: uuid.UUID,
    question_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: DB,
    _: CurrentTeacher,
    image: UploadFile = File(...),
):
    """
    One photo covering several students (names handwritten above/beside
    their own work) — detects each name, crops their individual work out
    of the photo, and creates (or reuses, matched by label) one Station +
    one attempt per student, all against `question_id`. Each attempt then
    runs through the exact same background grading pipeline
    (_run_attempt_background -> process_attempt) as a normal single-photo
    capture — this endpoint only replaces "teacher photographs one
    notebook at a time and types a label" with "one wide photo, names
    read automatically."

    Synchronous here: detection (one vision call) + station lookups/attempt
    creation for however many students were found — seconds, not the
    minutes a full Gates-A-H grading run would take, which is why THAT
    part still fans out to background tasks per attempt rather than
    blocking this request.
    """
    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)
    question = await db.get(PracticeQuestion, question_id)
    if not question or question.session_id != session_id:
        raise ACIError("QUESTION_NOT_FOUND", "Practice question not found in this session", 404)
    if question.status != "approved":
        raise ACIError("QUESTION_NOT_APPROVED", "This question hasn't been approved by a teacher yet", 409)

    if image.content_type not in _ALLOWED_CONTENT_TYPES:
        raise ACIError("INVALID_IMAGE_TYPE", "Only JPEG and PNG images are accepted", 400)
    image_bytes = await image.read()

    try:
        detections = await practice_service.detect_student_regions(image_bytes, question.text)
    except RuntimeError as exc:
        raise ACIError("AI_NOT_CONFIGURED", str(exc), 503)
    except Exception:
        logger.exception("Batch scan detection failed for session %s", session_id)
        raise ACIError("BATCH_SCAN_FAILED", "Could not analyze this photo — please try again", 502)

    if not detections:
        raise ACIError(
            "NO_STUDENTS_DETECTED",
            "Couldn't make out any names with work under them in this photo — make sure each "
            "student's name is written clearly above or beside their own work, then try again.",
            422,
        )

    existing_stations = (
        await db.execute(select(PracticeStation).where(PracticeStation.session_id == session_id))
    ).scalars().all()
    by_label = {s.label.strip().lower(): s for s in existing_stations if s.label}

    results: list[BatchScanResult] = []
    skipped: list[str] = []
    for det in detections:
        crop_bytes = practice_service.crop_student_region(image_bytes, det["bbox"])
        if crop_bytes is None:
            skipped.append(det["name"])
            continue

        station = by_label.get(det["name"].strip().lower())
        is_new = station is None
        if station is None:
            station = PracticeStation(
                session_id=session_id, label=det["name"], active_question_id=question_id, status="idle",
            )
            db.add(station)
            await db.flush()
            by_label[det["name"].strip().lower()] = station
        else:
            # Re-scanning the same names for a new question re-points every
            # matched station at it — same "batch scan always targets the
            # current question" assumption the detection prompt is given.
            station.active_question_id = question_id

        attempt = await _persist_attempt(
            db, question, crop_bytes, None, det["name"], station_id=station.id,
        )
        results.append(BatchScanResult(
            name=det["name"], station_id=station.id, attempt_id=attempt.id, is_new_station=is_new,
        ))

    for r in results:
        background_tasks.add_task(_run_attempt_background, r.attempt_id)

    return BatchScanResponse(detected=results, skipped=skipped)
