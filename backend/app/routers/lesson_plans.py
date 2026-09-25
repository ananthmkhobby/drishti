"""
Lesson plan upload and retrieval endpoints.

POST /sessions/{session_id}/lesson-plan  — upload PDF or image, extract topics
GET  /sessions/{session_id}/lesson-plan  — get current lesson plan + topics
"""
import io
import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, File, UploadFile
from sqlalchemy import select

from app.dependencies import CurrentTeacher, DB
from app.exceptions import ACIError
from app.models.session import Session
from app.models.lesson_plan import LessonPlan
from app.services import storage_service
from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Lesson Plans"])

_ALLOWED_TYPES = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
}

_MAX_SIZE_MB = 20


@router.post("/sessions/{session_id}/lesson-plan", status_code=201)
async def upload_lesson_plan(
    session_id: uuid.UUID,
    db: DB,
    _: CurrentTeacher,
    file: UploadFile = File(...),
):
    settings = get_settings()

    # Validate session
    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    # Validate file type
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in _ALLOWED_TYPES:
        raise ACIError(
            "INVALID_FILE_TYPE",
            f"Unsupported file type '{content_type}'. Upload a PDF or JPEG/PNG image.",
            400,
        )
    ext = _ALLOWED_TYPES[content_type]
    file_type = "pdf" if ext == "pdf" else "image"

    # Read and size-check
    data = await file.read()
    size_mb = len(data) / (1024 * 1024)
    if size_mb > _MAX_SIZE_MB:
        raise ACIError("FILE_TOO_LARGE", f"File exceeds {_MAX_SIZE_MB} MB limit", 400)

    # Extract text
    raw_text = _extract_text(data, file_type, content_type)

    # Extract topic list via AI (if OpenAI key available)
    topics: list[str] = []
    if settings.openai_api_key:
        try:
            if file_type == "image":
                topics = await _ai_extract_topics_vision(data, content_type, settings)
            elif raw_text:
                topics = await _ai_extract_topics(raw_text, settings)
        except Exception as exc:
            logger.warning("Topic extraction failed: %s", exc)

    # Save file
    file_id = str(uuid.uuid4())
    file_path = await storage_service.save_lesson_plan(session_id, file_id, data, ext)

    # Upsert — replace existing plan for this session
    existing = await db.execute(
        select(LessonPlan).where(LessonPlan.session_id == session_id)
    )
    plan = existing.scalar_one_or_none()

    if plan:
        plan.file_path = file_path
        plan.file_type = file_type
        plan.raw_text = raw_text
        plan.topics = topics
        plan.updated_at = datetime.now(timezone.utc)
    else:
        plan = LessonPlan(
            id=uuid.uuid4(),
            session_id=session_id,
            file_path=file_path,
            file_type=file_type,
            raw_text=raw_text,
            topics=topics,
        )
        db.add(plan)

    await db.commit()
    await db.refresh(plan)

    return {
        "lesson_plan_id": str(plan.id),
        "session_id": str(session_id),
        "file_type": file_type,
        "topics": topics,
        "topic_count": len(topics),
        "raw_text_length": len(raw_text or ""),
    }


@router.get("/sessions/{session_id}/lesson-plan")
async def get_lesson_plan(
    session_id: uuid.UUID,
    db: DB,
    _: CurrentTeacher,
):
    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    result = await db.execute(
        select(LessonPlan).where(LessonPlan.session_id == session_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise ACIError("LESSON_PLAN_NOT_FOUND", "No lesson plan uploaded for this session", 404)

    return {
        "lesson_plan_id": str(plan.id),
        "session_id": str(session_id),
        "file_type": plan.file_type,
        "topics": plan.topics or [],
        "topic_count": len(plan.topics or []),
        "raw_text_length": len(plan.raw_text or ""),
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_text(data: bytes, file_type: str, content_type: str) -> str:
    """Extract raw text from PDF or image bytes."""
    if file_type == "pdf":
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                pages = [page.extract_text() or "" for page in pdf.pages]
            return "\n\n".join(p for p in pages if p.strip())
        except Exception as exc:
            logger.warning("PDF text extraction failed: %s", exc)
            return ""
    else:
        # For images: return empty string — topics will be extracted via Vision API in _ai_extract_topics
        return ""


async def _ai_extract_topics(raw_text: str, settings) -> list[str]:
    """Call OpenAI to extract a clean topic list from lesson plan text."""
    from app.ai import build_topic_extraction_prompt, parse_topic_list
    from app.ai.openai_client import call_openai

    prompt = build_topic_extraction_prompt(raw_text)
    raw_response, _ = await call_openai(
        api_key=settings.openai_api_key,
        model=settings.openai_model_mini,
        system=prompt.system,
        user=prompt.user,
        max_tokens=500,
        timeout_sec=settings.ai_request_timeout_sec,
    )
    return parse_topic_list(raw_response)


async def _ai_extract_topics_vision(image_data: bytes, content_type: str, settings) -> list[str]:
    """Use GPT-4o Vision to extract topics from a lesson plan photo."""
    from app.ai import parse_topic_list
    from app.ai.openai_client import call_openai_vision

    system = (
        "You are a curriculum analyst. The user will show you a photo of a lesson plan. "
        "Extract every topic, chapter, objective, or learning point visible on the page. "
        "Return ONLY a JSON array of short topic strings. Example: [\"Photosynthesis\", \"Cell respiration\"]. "
        "No explanation, no markdown, just the JSON array."
    )
    raw_response, _ = await call_openai_vision(
        api_key=settings.openai_api_key,
        model=settings.openai_model_default,
        system=system,
        user_text="Please extract all lesson plan topics from this image.",
        image_data=image_data,
        image_media_type=content_type,
        max_tokens=500,
        timeout_sec=settings.ai_request_timeout_sec,
    )
    return parse_topic_list(raw_response)
