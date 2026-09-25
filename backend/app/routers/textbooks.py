"""
Textbook upload + chapter-based teaching endpoints.

POST /sessions/{session_id}/textbooks                                   — upload PDF, kick off chapter detection
GET  /sessions/{session_id}/textbooks                                   — list textbooks for a session
GET  /textbooks/{textbook_id}                                           — textbook status + detected chapters
GET  /textbooks/{textbook_id}/chapters/{chapter_id}                     — one chapter's progress
POST /textbooks/{textbook_id}/chapters/{chapter_id}/teach-next          — generate/serve the next teaching segment
POST /textbooks/{textbook_id}/chapters/{chapter_id}/teach-next-stream   — same, streamed as NDJSON (see docstring)
POST /sessions/{session_id}/textbooks/locate-chapter                    — fuzzy-match a spoken phrase to a chapter
"""
import asyncio
import uuid
import logging

from fastapi import APIRouter, File, Form, UploadFile, BackgroundTasks
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.dependencies import CurrentTeacher, DB
from app.exceptions import ACIError
from app.models.session import Session
from app.models.textbook import Textbook, TextbookChapter, TextbookFigure
from app.services import storage_service, textbook_service
from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Textbooks"])

_MAX_SIZE_MB = 60


_VALID_CONTENT_TYPES = {"textbook", "concept_notes"}


def _chapter_out(ch: TextbookChapter) -> dict:
    return {
        "chapter_id": str(ch.id),
        "order_index": ch.order_index,
        "title": ch.title,
        "start_page": ch.start_page,
        "end_page": ch.end_page,
        "pedagogy": ch.pedagogy,
        "current_segment_index": ch.current_segment_index,
        "segment_count": len(ch.segments or []),
        "started": ch.current_segment_index > 0,
        "last_taught_at": ch.last_taught_at.isoformat() if ch.last_taught_at else None,
    }


def _textbook_out(tb: Textbook, chapters: list[TextbookChapter] | None = None) -> dict:
    out = {
        "textbook_id": str(tb.id),
        "session_id": str(tb.session_id),
        "title": tb.title,
        "status": tb.status,
        "error_message": tb.error_message,
        "page_count": tb.page_count,
        "content_type": tb.content_type,
        "language_code": tb.language_code,
        "language_name": tb.language_name,
        "created_at": tb.created_at.isoformat() if tb.created_at else None,
    }
    if chapters is not None:
        out["chapters"] = [_chapter_out(c) for c in sorted(chapters, key=lambda c: c.order_index)]
    return out


@router.post("/sessions/{session_id}/textbooks", status_code=201)
async def upload_textbook(
    session_id: uuid.UUID,
    db: DB,
    _: CurrentTeacher,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    content_type: str = Form("textbook"),
):
    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    if content_type not in _VALID_CONTENT_TYPES:
        raise ACIError("INVALID_CONTENT_TYPE", f"content_type must be one of {sorted(_VALID_CONTENT_TYPES)}", 400)

    mime_type = (file.content_type or "").split(";")[0].strip().lower()
    if mime_type != "application/pdf":
        raise ACIError("INVALID_FILE_TYPE", "Only PDF textbooks are supported", 400)

    data = await file.read()
    size_mb = len(data) / (1024 * 1024)
    if size_mb > _MAX_SIZE_MB:
        raise ACIError("FILE_TOO_LARGE", f"File exceeds {_MAX_SIZE_MB} MB limit", 400)

    # pdfplumber extraction is synchronous, page-by-page CPU work — on a
    # large PDF this can take long enough to block the whole event loop,
    # which is exactly what caused the reported symptom: the teacher's
    # upload request sits open so long that the browser (or a slow
    # classroom wifi connection) gives up and shows an error, even though
    # the upload is still running server-side and finishes successfully a
    # moment later — "I refresh and it's processing". Retrying the "failed"
    # upload then created a second Textbook row for the same file. Offloading
    # to a thread fixes the blocking half of that; the dedupe check below
    # fixes the duplicate-row half regardless of why the client retried.
    pages = await asyncio.to_thread(textbook_service.extract_pages, data)
    if not pages:
        raise ACIError("EXTRACTION_FAILED", "Could not read any text from this PDF", 400)

    # Idempotency: a retried upload of the exact same PDF produces byte-
    # identical extracted text for every page. Treat that as "this already
    # went through" and hand back the existing textbook instead of creating
    # a duplicate — covers a same-file retry after a false-negative error,
    # a double-submit, or a teacher just uploading it again to be safe.
    existing_result = await db.execute(
        select(Textbook).where(Textbook.session_id == session_id, Textbook.status != "failed")
    )
    for existing in existing_result.scalars().all():
        if existing.raw_pages == pages:
            chapters_result = await db.execute(
                select(TextbookChapter).where(TextbookChapter.textbook_id == existing.id)
            )
            return JSONResponse(
                status_code=200,
                content=_textbook_out(existing, chapters=list(chapters_result.scalars().all())),
            )

    file_id = str(uuid.uuid4())
    file_path = await storage_service.save_textbook(session_id, file_id, data, "pdf")

    textbook = Textbook(
        id=uuid.uuid4(),
        session_id=session_id,
        title=title or (file.filename or "").rsplit(".", 1)[0] or None,
        file_path=file_path,
        page_count=len(pages),
        raw_pages=pages,
        status="processing",
        content_type=content_type,
    )
    db.add(textbook)
    await db.commit()
    await db.refresh(textbook)

    background_tasks.add_task(_detect_chapters_background, textbook.id)

    return _textbook_out(textbook, chapters=[])


@router.get("/sessions/{session_id}/textbooks")
async def list_textbooks(session_id: uuid.UUID, db: DB, _: CurrentTeacher):
    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    result = await db.execute(
        select(Textbook).where(Textbook.session_id == session_id).order_by(Textbook.created_at.desc())
    )
    textbooks = result.scalars().all()

    out = []
    for tb in textbooks:
        chapters_result = await db.execute(
            select(TextbookChapter).where(TextbookChapter.textbook_id == tb.id)
        )
        out.append(_textbook_out(tb, chapters=list(chapters_result.scalars().all())))
    return {"textbooks": out}


@router.get("/textbooks/{textbook_id}")
async def get_textbook(textbook_id: uuid.UUID, db: DB, _: CurrentTeacher):
    textbook = await db.get(Textbook, textbook_id)
    if not textbook:
        raise ACIError("TEXTBOOK_NOT_FOUND", "Textbook not found", 404)

    result = await db.execute(
        select(TextbookChapter).where(TextbookChapter.textbook_id == textbook_id)
    )
    return _textbook_out(textbook, chapters=list(result.scalars().all()))


@router.delete("/textbooks/{textbook_id}", status_code=204)
async def delete_textbook(textbook_id: uuid.UUID, db: DB, _: CurrentTeacher):
    """
    Deletes a textbook and everything under it: its chapters, its
    extracted figures, and all three's stored files. Deletes children
    explicitly rather than relying on the DB's ON DELETE CASCADE — SQLite
    only enforces that when foreign_keys is pragma'd on for the
    connection, which isn't guaranteed here, so this stays correct
    regardless of that setting (and on Postgres it's simply redundant
    with the cascade, never wrong).
    """
    textbook = await db.get(Textbook, textbook_id)
    if not textbook:
        return  # already gone — DELETE is idempotent

    figures_result = await db.execute(
        select(TextbookFigure).where(TextbookFigure.textbook_id == textbook_id)
    )
    for figure in figures_result.scalars().all():
        await storage_service.delete_blob(figure.image_path)
        await db.delete(figure)

    chapters_result = await db.execute(
        select(TextbookChapter).where(TextbookChapter.textbook_id == textbook_id)
    )
    for chapter in chapters_result.scalars().all():
        await db.delete(chapter)

    await storage_service.delete_blob(textbook.file_path)
    await db.delete(textbook)
    await db.commit()


@router.get("/textbooks/{textbook_id}/chapters/{chapter_id}")
async def get_chapter(textbook_id: uuid.UUID, chapter_id: uuid.UUID, db: DB, _: CurrentTeacher):
    chapter = await db.get(TextbookChapter, chapter_id)
    if not chapter or chapter.textbook_id != textbook_id:
        raise ACIError("CHAPTER_NOT_FOUND", "Chapter not found", 404)
    textbook = await db.get(Textbook, textbook_id)
    out = _chapter_out(chapter)
    out["language_code"] = textbook.language_code if textbook else None
    out["language_name"] = textbook.language_name if textbook else None
    out["taught_log"] = chapter.taught_log or []
    # last-served segment text (+ visual, if any), so a client resuming
    # mid-chapter (e.g. next day, or after a page refresh) can redisplay
    # it without regenerating
    segments = chapter.segments or []
    last = segments[-1] if segments else None
    out["last_segment_text"] = last["segment_text"] if last else None
    out["is_last_segment"] = bool(last["is_last_segment"]) if last else False
    out["last_segment_figure_id"] = last.get("figure_id") if last else None
    out["last_segment_figure_caption"] = last.get("figure_caption") if last else None
    out["last_segment_diagram_spec"] = last.get("diagram_spec") if last else None
    out["last_segment_quest_phase"] = last.get("quest_phase") if last else None
    # Full per-segment history (not just the last one) — lets the client
    # offer a "previous" control that steps back through everything already
    # taught, including after a page reload, instead of only ever being
    # able to move forward.
    out["segments"] = [
        {
            "segment_index": i,
            "segment_text": s.get("segment_text"),
            "is_last_segment": bool(s.get("is_last_segment")),
            "figure_id": s.get("figure_id"),
            "figure_caption": s.get("figure_caption"),
            "diagram_spec": s.get("diagram_spec"),
            "quest_phase": s.get("quest_phase"),
        }
        for i, s in enumerate(segments)
    ]
    return out


@router.post("/textbooks/{textbook_id}/chapters/{chapter_id}/teach-next")
async def teach_next_segment(textbook_id: uuid.UUID, chapter_id: uuid.UUID, db: DB, _: CurrentTeacher):
    textbook = await db.get(Textbook, textbook_id)
    if not textbook:
        raise ACIError("TEXTBOOK_NOT_FOUND", "Textbook not found", 404)
    chapter = await db.get(TextbookChapter, chapter_id)
    if not chapter or chapter.textbook_id != textbook_id:
        raise ACIError("CHAPTER_NOT_FOUND", "Chapter not found", 404)

    try:
        segment = await textbook_service.generate_next_segment(textbook, chapter, db)
    except RuntimeError as exc:
        raise ACIError("AI_NOT_CONFIGURED", str(exc), 503)
    except Exception as exc:
        logger.exception("Teaching segment generation failed for chapter %s", chapter_id)
        raise ACIError("SEGMENT_GENERATION_FAILED", "Could not generate the next segment", 502)

    return segment


@router.post("/textbooks/{textbook_id}/chapters/{chapter_id}/teach-next-stream")
async def teach_next_segment_stream(textbook_id: uuid.UUID, chapter_id: uuid.UUID, db: DB, _: CurrentTeacher):
    """
    Streaming twin of teach-next (kept alongside it, unchanged, as a safe
    fallback) — NDJSON, one JSON object per line:
      {"type": "delta", "text": "..."}   zero or more, as the lesson text
                                          is generated
      {"type": "done", ...}              exactly once, last — same shape
                                          teach-next's single response has
      {"type": "error", "message": "..."} instead of "done", on failure

    Lets the teaching page start showing (and, once fully arrived,
    speaking) the segment within roughly one round trip instead of sitting
    on a "Thinking…" spinner for the whole generation — reported
    2026-09-22 as "Continue taking too much time in thinking state".

    The FIRST item is pulled before the response actually starts (same
    pattern as /voice/speak) so a genuine failure — AI not configured, the
    very first OpenAI call erroring — still produces a clean HTTP error
    status instead of a 200 that immediately, silently ends.
    """
    textbook = await db.get(Textbook, textbook_id)
    if not textbook:
        raise ACIError("TEXTBOOK_NOT_FOUND", "Textbook not found", 404)
    chapter = await db.get(TextbookChapter, chapter_id)
    if not chapter or chapter.textbook_id != textbook_id:
        raise ACIError("CHAPTER_NOT_FOUND", "Chapter not found", 404)

    gen = textbook_service.generate_next_segment_streaming(textbook, chapter, db)
    try:
        first_item = await gen.__anext__()
    except StopAsyncIteration:
        raise ACIError("SEGMENT_GENERATION_FAILED", "Could not generate the next segment", 502)
    except Exception:
        logger.exception("Streaming teaching segment generation failed for chapter %s", chapter_id)
        raise ACIError("SEGMENT_GENERATION_FAILED", "Could not generate the next segment", 502)

    if first_item.get("type") == "error":
        message = first_item.get("message", "Could not generate the next segment")
        if "not configured" in message.lower():
            raise ACIError("AI_NOT_CONFIGURED", message, 503)
        raise ACIError("SEGMENT_GENERATION_FAILED", message, 502)

    async def ndjson_lines():
        import json as _json
        yield _json.dumps(first_item) + "\n"
        try:
            async for item in gen:
                yield _json.dumps(item) + "\n"
        except Exception:
            logger.exception("Streaming teaching segment generation failed mid-stream for chapter %s", chapter_id)
            yield _json.dumps({"type": "error", "message": "Could not generate the next segment"}) + "\n"

    return StreamingResponse(ndjson_lines(), media_type="application/x-ndjson")


@router.post("/textbooks/{textbook_id}/chapters/{chapter_id}/check-understanding")
async def check_understanding(textbook_id: uuid.UUID, chapter_id: uuid.UUID, db: DB, _: CurrentTeacher):
    """
    Teacher-triggered at any point during teaching: one MCQ grounded in
    what's been taught so far. Does not advance or otherwise touch the
    chapter's teaching bookmark — see textbook_service.generate_check_understanding.
    """
    textbook = await db.get(Textbook, textbook_id)
    if not textbook:
        raise ACIError("TEXTBOOK_NOT_FOUND", "Textbook not found", 404)
    chapter = await db.get(TextbookChapter, chapter_id)
    if not chapter or chapter.textbook_id != textbook_id:
        raise ACIError("CHAPTER_NOT_FOUND", "Chapter not found", 404)

    try:
        return await textbook_service.generate_check_understanding(textbook, chapter)
    except RuntimeError as exc:
        raise ACIError("AI_NOT_CONFIGURED", str(exc), 503)
    except ValueError as exc:
        raise ACIError("NOTHING_TAUGHT_YET", str(exc), 400)
    except Exception:
        logger.exception("Check-understanding generation failed for chapter %s", chapter_id)
        raise ACIError("CHECK_GENERATION_FAILED", "Could not generate a check-understanding question", 502)


@router.post("/textbooks/{textbook_id}/chapters/{chapter_id}/revise")
async def revise_chapter(textbook_id: uuid.UUID, chapter_id: uuid.UUID, db: DB, _: CurrentTeacher):
    """
    Condensed bullet-point recap of what's been taught so far — shown once
    when a teacher resumes a chapter with existing progress, before moving
    on to new material. Does not advance or otherwise touch the chapter's
    teaching bookmark, same as check-understanding.
    """
    textbook = await db.get(Textbook, textbook_id)
    if not textbook:
        raise ACIError("TEXTBOOK_NOT_FOUND", "Textbook not found", 404)
    chapter = await db.get(TextbookChapter, chapter_id)
    if not chapter or chapter.textbook_id != textbook_id:
        raise ACIError("CHAPTER_NOT_FOUND", "Chapter not found", 404)

    try:
        return await textbook_service.generate_revision_recap(textbook, chapter)
    except RuntimeError as exc:
        raise ACIError("AI_NOT_CONFIGURED", str(exc), 503)
    except ValueError as exc:
        raise ACIError("NOTHING_TAUGHT_YET", str(exc), 400)
    except Exception:
        logger.exception("Revision recap generation failed for chapter %s", chapter_id)
        raise ACIError("REVISION_GENERATION_FAILED", "Could not generate a revision recap", 502)


@router.get("/textbooks/{textbook_id}/figures/{figure_id}/image")
async def get_figure_image(textbook_id: uuid.UUID, figure_id: uuid.UUID, db: DB, _: CurrentTeacher):
    """Serve a content-safety-approved diagram cropped from the textbook — see textbook_service.extract_figures."""
    figure = await db.get(TextbookFigure, figure_id)
    if not figure or figure.textbook_id != textbook_id:
        raise ACIError("FIGURE_NOT_FOUND", "Figure not found", 404)
    try:
        image_bytes = await storage_service.load_frame_bytes(figure.image_path)
        return Response(content=image_bytes, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})
    except (FileNotFoundError, OSError):
        raise ACIError("IMAGE_NOT_FOUND", "Figure image not found on server", 404)


class LocateChapterRequest(BaseModel):
    query: str


@router.post("/sessions/{session_id}/textbooks/locate-chapter")
async def locate_chapter(session_id: uuid.UUID, body: LocateChapterRequest, db: DB, _: CurrentTeacher):
    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    tb_result = await db.execute(
        select(Textbook).where(Textbook.session_id == session_id, Textbook.status == "ready")
    )
    textbooks = tb_result.scalars().all()
    if not textbooks:
        # Distinguish "nothing uploaded at all" from "uploaded, still being
        # processed" — these need different messages. Chapter detection is
        # a real LLM call over every page (plus vision-OCR fallback for
        # scanned pages), so a just-uploaded PDF can sit in "processing"
        # for a while; before this fix, both cases produced the same
        # generic 404 and the voice assistant told the teacher to "upload
        # a textbook" even when one was already visible, mid-processing,
        # on the Textbook tab (reported 2026-09-22).
        any_result = await db.execute(
            select(Textbook.status).where(Textbook.session_id == session_id)
        )
        any_statuses = any_result.scalars().all()
        if any_statuses:
            if "failed" in any_statuses and all(s == "failed" for s in any_statuses):
                raise ACIError("TEXTBOOK_FAILED", "The uploaded textbook couldn't be processed — check the Textbook tab", 404)
            raise ACIError("TEXTBOOK_PROCESSING", "The uploaded textbook is still being processed — try again in a moment", 409)
        raise ACIError("NO_TEXTBOOK_READY", "No textbook has been uploaded for this session yet", 404)

    for tb in textbooks:
        ch_result = await db.execute(
            select(TextbookChapter).where(TextbookChapter.textbook_id == tb.id)
        )
        chapters = list(ch_result.scalars().all())
        match = textbook_service.find_chapter_by_query(chapters, body.query)
        if match:
            return {
                "textbook_id": str(tb.id),
                "chapter_id": str(match.id),
                "title": match.title,
            }

    raise ACIError("CHAPTER_NOT_FOUND", f"Could not find a chapter matching '{body.query}'", 404)


async def _detect_chapters_background(textbook_id: uuid.UUID):
    from app.database import _get_session_factory
    factory = _get_session_factory()
    async with factory() as db:
        await textbook_service.detect_chapters(textbook_id, db)
    # Figure extraction runs after chapter detection, in its own session —
    # a textbook is still fully usable (text-only teaching) if this part
    # fails, so it never affects Textbook.status.
    async with factory() as db:
        try:
            await textbook_service.extract_figures(textbook_id, db)
        except Exception:
            logger.exception("Figure extraction failed for textbook %s", textbook_id)
