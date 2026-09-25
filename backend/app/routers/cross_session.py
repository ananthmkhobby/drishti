"""
Cross-session endpoints — comparing 2+ sessions (possibly different subject/
grade/instructor) to surface genuine conceptual links between them.
"""
import uuid
import logging

from fastapi import APIRouter
from sqlalchemy import select

from app.dependencies import CurrentTeacher, DB
from app.exceptions import ACIError
from app.config import get_settings
from app.models.session import Session
from app.models.ai_output import AIOutput
from app.services.cross_session_service import generate_cross_session_links
from app.schemas.cross_session import (
    CrossSessionLinkRequest,
    CrossSessionLinkResponse,
    SessionSummaryEntry,
    ConceptConnection,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Cross-Session"])


@router.post("/sessions/cross-session-links", response_model=CrossSessionLinkResponse)
async def cross_session_links(body: CrossSessionLinkRequest, db: DB, _: CurrentTeacher):
    session_ids: list[uuid.UUID] = body.session_ids

    sessions_rows = (
        await db.execute(
            select(Session).where(Session.id.in_(session_ids), Session.deleted_at.is_(None))
        )
    ).scalars().all()

    found_ids = {s.id for s in sessions_rows}
    missing = [str(sid) for sid in session_ids if sid not in found_ids]
    if missing:
        raise ACIError("SESSION_NOT_FOUND", f"Session(s) not found: {', '.join(missing)}", 404)

    # Preserve the order the caller asked for, not whatever order the DB returned.
    by_id = {s.id: s for s in sessions_rows}
    ordered_sessions = [by_id[sid] for sid in session_ids]

    notes_rows = (
        await db.execute(
            select(AIOutput).where(
                AIOutput.session_id.in_(session_ids),
                AIOutput.output_type == "notes",
                AIOutput.status == "ready",
            )
        )
    ).scalars().all()
    notes_by_session = {row.session_id: row for row in notes_rows}

    sessions_for_prompt = []
    summary_entries = []
    for s in ordered_sessions:
        notes_row = notes_by_session.get(s.id)
        content = ""
        if notes_row and notes_row.content_json:
            content = notes_row.content_json.get("markdown", "") or ""
        sessions_for_prompt.append({
            "subject": s.subject,
            "grade": s.grade,
            "title": s.title,
            "instructor_name": s.instructor_name,
            "content": content,
        })
        summary_entries.append(SessionSummaryEntry(
            session_id=s.id,
            subject=s.subject,
            grade=s.grade,
            title=s.title,
            instructor_name=s.instructor_name,
            has_notes=bool(content),
        ))

    settings = get_settings()
    result = await generate_cross_session_links(sessions_for_prompt, settings.openai_api_key)

    return CrossSessionLinkResponse(
        sessions=summary_entries,
        unifying_theme=result["unifying_theme"],
        overall_summary=result["overall_summary"],
        connections=[ConceptConnection(**c) for c in result["connections"]],
        integrated_activity=result["integrated_activity"],
    )
