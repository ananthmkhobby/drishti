"""
Outputs router — AI output retrieval and TiQer export.

Endpoints:
  POST /sessions/{id}/generate            — trigger AI generation (background)
  GET  /sessions/{id}/outputs             — all outputs for a session
  GET  /sessions/{id}/outputs/quiz        — quiz questions (JSON)
  POST /sessions/{id}/outputs/quiz/export-tiqer     — export to TiQer platform
  GET  /sessions/{id}/outputs/quiz/tiqer-preview    — preview / download TiQer JSON
"""

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import Response
from sqlalchemy import select, update

from app.dependencies import CurrentTeacher, DB
from app.exceptions import ACIError
from app.models.session import Session
from app.models.ai_output import AIOutput
from app.models.quiz_question import QuizQuestion
from app.models.tiqer_export_log import TiQerExportLog
from app.models.job import Job
from app.services import ai_service
from app.services.tiqer_service import (
    build_tiqer_payload,
    push_to_tiqer_api,
    serialise_payload,
    payload_to_dict,
)
from app.schemas.ai_output import (
    GenerateRequest,
    GenerateResponse,
    SessionOutputsResponse,
    OutputEntry,
    QuizResponse,
    QuizQuestionResponse,
    TiQerExportRequest,
    TiQerExportResponse,
)

router = APIRouter(tags=["AI Outputs"])


# ── Generation ────────────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/generate", status_code=202, response_model=GenerateResponse)
async def trigger_generation(
    session_id: uuid.UUID,
    body: GenerateRequest,
    background_tasks: BackgroundTasks,
    db: DB,
    _: CurrentTeacher,
):
    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)
    if session.status not in ("completed", "active", "ai_complete"):
        raise ACIError(
            "SESSION_NOT_READY",
            "Session must be active, completed, or ai_complete to generate outputs",
            400,
        )

    job = Job(id=uuid.uuid4(), job_type="ai_generation", session_id=session_id, status="queued", progress=0)
    db.add(job)
    await db.commit()
    await db.refresh(job)

    background_tasks.add_task(
        _run_generation_background, session_id, list(body.outputs), job.id
    )

    return GenerateResponse(job_id=job.id, status="queued", estimated_sec=90)


# ── Outputs list ──────────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/outputs", response_model=SessionOutputsResponse)
async def get_session_outputs(session_id: uuid.UUID, db: DB, _: CurrentTeacher):
    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    rows = (
        await db.execute(select(AIOutput).where(AIOutput.session_id == session_id))
    ).scalars().all()

    outputs: dict[str, OutputEntry] = {}
    for row in rows:
        entry = OutputEntry(
            status=row.status,
            url=row.content_url,
            generated_at=row.created_at if row.status == "ready" else None,
            tokens_used=row.tokens_used or 0,
        )
        if row.status == "ready" and row.content_json:
            entry.data = row.content_json
        outputs[row.output_type] = entry

    total_tokens = sum(e.tokens_used for e in outputs.values())
    return SessionOutputsResponse(session_id=session_id, outputs=outputs, total_tokens=total_tokens)


# ── Quiz ──────────────────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/outputs/quiz", response_model=QuizResponse)
async def get_quiz(session_id: uuid.UUID, db: DB, _: CurrentTeacher):
    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    questions = (
        await db.execute(
            select(QuizQuestion)
            .where(QuizQuestion.session_id == session_id)
            .order_by(QuizQuestion.created_at)
        )
    ).scalars().all()

    if not questions:
        raise ACIError("QUIZ_NOT_READY", "No quiz questions found — trigger generation first", 404)

    return QuizResponse(
        session_id=session_id,
        questions=[
            QuizQuestionResponse(
                id=q.id,
                type=q.question_type,
                text=q.text,
                options=q.options,
                correct=q.correct_answer.get("value") if q.correct_answer else None,
                bloom_level=q.bloom_level,
                topic=q.topic,
                skill_tag=q.skill_tag,
                teacher_edited=q.teacher_edited,
            )
            for q in questions
        ],
    )


# ── TiQer export ──────────────────────────────────────────────────────────────

@router.post(
    "/sessions/{session_id}/outputs/quiz/export-tiqer",
    response_model=TiQerExportResponse,
)
async def export_to_tiqer(
    session_id: uuid.UUID,
    body: TiQerExportRequest,
    db: DB,
    teacher_id: CurrentTeacher,
):
    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    questions = (
        await db.execute(
            select(QuizQuestion)
            .where(QuizQuestion.session_id == session_id)
            .order_by(QuizQuestion.created_at)
        )
    ).scalars().all()

    if not questions:
        raise ACIError("QUIZ_NOT_READY", "No quiz questions found — generate quiz first", 404)

    # Build canonical TiQer payload
    export_id = str(uuid.uuid4())
    payload   = build_tiqer_payload(
        session=session,
        teacher_id=teacher_id,
        questions=list(questions),
        tiqer_class_id=body.tiqer_class_id,
        export_id=export_id,
    )

    # Phase 2: push to TiQer API (stub in Phase 1)
    tiqer_session_id = await push_to_tiqer_api(payload)

    # Write audit log
    log = TiQerExportLog(
        id=uuid.uuid4(),
        session_id=session_id,
        teacher_id=teacher_id,
        tiqer_class_id=body.tiqer_class_id,
        tiqer_session_id=tiqer_session_id,
        question_count=len(questions),
        schedule_at=body.schedule_at,
        payload_json=serialise_payload(payload),
    )
    db.add(log)

    # Mark questions as exported
    await db.execute(
        update(QuizQuestion)
        .where(QuizQuestion.session_id == session_id)
        .values(tiqer_exported=True)
    )
    await db.commit()

    return TiQerExportResponse(
        tiqer_session_id=tiqer_session_id,
        status="exported",
        question_count=len(questions),
        exported_at=payload.exported_at,
        payload=payload_to_dict(payload),
    )


@router.get(
    "/sessions/{session_id}/outputs/quiz/tiqer-preview",
    summary="Preview or download the TiQer-formatted JSON for this session's quiz",
)
async def tiqer_preview(
    session_id: uuid.UUID,
    db: DB,
    teacher_id: CurrentTeacher,
    tiqer_class_id: str = "PREVIEW",
    download: bool = False,
):
    """
    Returns the full TiQer export payload as JSON.

    - ``?tiqer_class_id=CLS-...`` — pre-fill the class ID in the payload
    - ``?download=true``          — triggers a file download in the browser
                                    (Content-Disposition: attachment)
    """
    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    questions = (
        await db.execute(
            select(QuizQuestion)
            .where(QuizQuestion.session_id == session_id)
            .order_by(QuizQuestion.created_at)
        )
    ).scalars().all()

    if not questions:
        raise ACIError("QUIZ_NOT_READY", "No quiz questions found — generate quiz first", 404)

    payload   = build_tiqer_payload(
        session=session,
        teacher_id=teacher_id,
        questions=list(questions),
        tiqer_class_id=tiqer_class_id,
    )
    json_bytes = serialise_payload(payload).encode("utf-8")

    filename = (
        f"aci_tiqer_{session.subject or 'quiz'}_{session.grade or ''}"
        f"_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        .replace(" ", "_").lower()
    )

    headers: dict[str, str] = {"Content-Type": "application/json; charset=utf-8"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'

    return Response(content=json_bytes, headers=headers, media_type="application/json")


# ── Session report (simple combined report) ──────────────────────────────────

@router.get("/sessions/{session_id}/session-report")
async def get_session_report(session_id: uuid.UUID, db: DB, _: CurrentTeacher):
    """
    Return the session_report AI output as a flat, human-readable JSON.

    Fields: headline, what_was_covered, how_it_went, highlights, gaps,
            next_class, sources {board_frames, audio}, status, generated_at
    """
    row = (
        await db.execute(
            select(AIOutput).where(
                AIOutput.session_id == session_id,
                AIOutput.output_type == "session_report",
            )
        )
    ).scalar_one_or_none()

    if not row:
        raise ACIError("NOT_FOUND", "Session report not generated yet — POST /sessions/{id}/generate with output_type=session_report", 404)

    content = row.content_json or {}
    return {
        "session_id": str(session_id),
        "status": row.status,
        "generated_at": row.created_at.isoformat() if row.created_at else None,
        "headline": content.get("headline", ""),
        "what_was_covered": content.get("what_was_covered", ""),
        "how_it_went": content.get("how_it_went", ""),
        "highlights": content.get("highlights", []),
        "gaps": content.get("gaps", []),
        "next_class": content.get("next_class", ""),
        "sources": content.get("sources", {}),
    }


# ── Background task wrapper ───────────────────────────────────────────────────

async def _run_generation_background(
    session_id: uuid.UUID, output_types: list[str], job_id: uuid.UUID
):
    from app.database import _get_session_factory

    factory = _get_session_factory()
    async with factory() as db:
        try:
            await ai_service.run_generation(session_id, output_types, job_id, db)
            from app.services.event_service import emit as emit_event
            await emit_event(db, "AI_OUTPUT_READY", session_id=session_id,
                             payload={"output_types": output_types})
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception(
                "AI generation background task failed session=%s", session_id
            )
            job = await db.get(Job, job_id)
            if job:
                job.status = "failed"
                job.error_message = str(exc)[:500]
                await db.commit()
