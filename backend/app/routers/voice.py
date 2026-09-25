import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import desc, select

from app.dependencies import CurrentTeacher, DB
from app.config import get_settings
from app.models.session import Session
from app.models.voice_event import VoiceEvent
from app.services import voice_intent_service, classroom_brain_service
from app.services.whisper_service import transcribe, transcribe_local, TranscriptResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["Voice Assistant"])


def _normalize_title(s: str) -> str:
    """Lowercase, strip punctuation — "Newton's Laws" and "Newtons laws of
    Motion" both normalize to something the other is a substring of. Title
    matching needs this: it's free-text spoken-then-transcribed phrases on
    both sides (what was said vs. what's stored), not a single word like
    subject/grade, so exact substring matching on the raw strings is too
    brittle (a transcription apostrophe alone breaks it)."""
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def _base_session_query(teacher_id: uuid.UUID | None):
    """teacher_id=None means search across ALL teachers — only used when an
    author name was actually given (see _resolve_session). Every other path
    stays scoped to the calling teacher's own sessions."""
    q = select(Session).where(Session.deleted_at.is_(None))
    if teacher_id is not None:
        q = q.where(Session.teacher_id == teacher_id)
    return q


async def _resolve_session(
    db, teacher_id: uuid.UUID,
    subject: str | None, grade: str | None, title: str | None,
    author: str | None, days_ago: object,
) -> Session | None:
    """
    Shared by open_session and delete_session: find the best-matching
    session for whatever subject/grade/topic/author/recency was named. Many
    sessions have no subject set (manual creation doesn't require one), so
    title is often the only reliable identifier when given. Falls back to
    the most recent session in scope if a named filter matches nothing,
    rather than a dead end — but only when at least one filter was actually
    given.

    Scope: normally restricted to the calling teacher's OWN sessions. An
    explicit author name is the only thing that widens the search across
    every teacher — this is a real visibility expansion, so it only kicks
    in when a name was actually said, never implicitly. delete_session
    additionally enforces ownership on top of this (see the caller) — being
    able to FIND another teacher's session by name doesn't mean being able
    to delete it.
    """
    from app.models.teacher import Teacher
    from sqlalchemy import or_

    scope_teacher_id = None if author else teacher_id
    query = _base_session_query(scope_teacher_id)
    if author:
        # Two ways a session can be tagged with who taught it: the free-text
        # instructor_name field set at creation (the realistic path — this
        # app runs as a single shared device with one dev_teacher_id, no
        # real per-person accounts, so THIS is what actually gets searched
        # in practice) or a genuine Teacher account name (kept as a fallback
        # for if/when real multi-account login exists). Outer join so a
        # session matching only on instructor_name — no linked Teacher row,
        # or a Teacher row that doesn't match — still comes back.
        query = query.outerjoin(Teacher, Teacher.id == Session.teacher_id).where(
            or_(
                Session.instructor_name.ilike(f"%{author}%"),
                Teacher.name.ilike(f"%{author}%"),
            )
        )
    if subject:
        query = query.where(Session.subject.ilike(f"%{subject}%"))
    if grade:
        query = query.where(Session.grade.ilike(f"%{grade}%"))

    days_ago_int: int | None = None
    if days_ago is not None:
        try:
            days_ago_int = int(days_ago)
        except (TypeError, ValueError):
            days_ago_int = None
    if days_ago_int is not None and days_ago_int >= 0:
        # Voice-estimated day counts are approximate — match the whole
        # calendar day around "N days ago" rather than an exact instant.
        target = datetime.now(timezone.utc) - timedelta(days=days_ago_int)
        query = query.where(
            Session.created_at >= target - timedelta(hours=18),
            Session.created_at <= target + timedelta(hours=18),
        )

    candidates = (
        await db.execute(query.order_by(desc(Session.created_at)).limit(50))
    ).scalars().all()

    if title:
        norm_title = _normalize_title(title)
        by_title = [s for s in candidates if s.title and norm_title in _normalize_title(s.title)]
        if by_title:
            return by_title[0]
        # Title didn't match among the subject/grade/author/days_ago-filtered
        # set — widen to every session in scope before giving up on title
        # (the subject/grade the model guessed may itself be off, but the
        # title is still the strongest signal available).
        all_sessions = (
            await db.execute(
                _base_session_query(scope_teacher_id).order_by(desc(Session.created_at)).limit(200)
            )
        ).scalars().all()
        by_title = [s for s in all_sessions if s.title and norm_title in _normalize_title(s.title)]
        if by_title:
            return by_title[0]

    if candidates:
        return candidates[0]

    if subject or grade or title or author or days_ago_int is not None:
        return (
            await db.execute(
                _base_session_query(scope_teacher_id).order_by(desc(Session.created_at)).limit(1)
            )
        ).scalar_one_or_none()

    return None


class ClassifyIntentRequest(BaseModel):
    transcript: str


class SpeakRequest(BaseModel):
    text: str
    # Optional steering for gpt-4o-mini-tts's "instructions" param — e.g. the
    # textbook Teaching page asks for a warmer, more expressive delivery than
    # the flatter default used for quick assistant answers elsewhere in the app.
    instructions: str | None = None


class AskRequest(BaseModel):
    question: str
    subject: str | None = None
    grade: str | None = None


class TranscribeResponse(BaseModel):
    transcript: str


class BrainAnswer(BaseModel):
    answer: str
    topics_covered: list[str]
    pending_concepts: list[str]
    suggested_next: str
    source: str  # "local" | "cloud" | "none"
    needs_clarification: bool = False


class VoiceCommandResponse(BaseModel):
    transcript: str
    intent: str
    params: dict
    source: str  # "local" | "cloud" | "none"
    brain_answer: BrainAnswer | None = None


async def _log_event(
    db: DB,
    teacher_id: uuid.UUID,
    transcript: str,
    intent_result: dict,
    brain_answer: dict | None,
    processing_ms: int,
) -> None:
    try:
        db.add(VoiceEvent(
            id=uuid.uuid4(),
            teacher_id=teacher_id,
            transcript=transcript,
            intent=intent_result["intent"],
            params=intent_result.get("params") or {},
            intent_source=intent_result["source"],
            answer=brain_answer["answer"] if brain_answer else None,
            answer_source=brain_answer["source"] if brain_answer else None,
            needs_clarification=bool(brain_answer and brain_answer.get("needs_clarification")),
            processing_ms=processing_ms,
        ))
        await db.commit()
    except Exception as exc:
        logger.warning("Voice event logging failed (non-fatal): %s", exc)


async def _transcribe_command(
    audio_bytes: bytes, filename: str, language: str | None, settings,
) -> TranscriptResult:
    """
    Shared by /voice/transcribe and /voice/command — try local whisper-server
    first (fast, only for short command utterances; see config.py), fall
    back to OpenAI cloud on any failure or when disabled.
    """
    if settings.local_whisper_enabled:
        local_result = await transcribe_local(
            audio_bytes, filename, settings.local_whisper_url, language or settings.whisper_language,
        )
        if local_result is not None:
            return local_result
    # A tight timeout here specifically (vs. transcribe()'s 120s default,
    # sized for long lecture recordings) — this is a live, mid-lesson voice
    # command, a few seconds of speech at most, so there's no legitimate
    # reason for the actual transcription call to take anywhere near that
    # long. Matches transcribe_local's own 25s default just above.
    return await transcribe(
        audio_bytes, filename, settings.openai_api_key, language or settings.whisper_language or None,
        timeout_sec=25.0,
    )


@router.post("/transcribe", response_model=TranscribeResponse)
async def voice_transcribe(
    _: CurrentTeacher,
    audio: UploadFile = File(...),
    language: str | None = Form(None),
):
    """
    Audio in, transcript out — nothing else. Split out from /command so the
    frontend can show "here's what I heard" immediately, before the slower
    intent-classification + answer-generation step runs.
    """
    settings = get_settings()
    if not settings.local_whisper_enabled and not settings.openai_api_key:
        return TranscribeResponse(transcript="")
    audio_bytes = await audio.read()
    try:
        result = await _transcribe_command(audio_bytes, audio.filename or "command.webm", language, settings)
        return TranscribeResponse(transcript=result.text)
    except Exception as exc:
        logger.warning("Voice transcribe failed: %s", exc)
        return TranscribeResponse(transcript="")


@router.post("/speak")
async def voice_speak(body: SpeakRequest, _: CurrentTeacher):
    """
    Text in, MP3 audio out via OpenAI TTS — STREAMED, not buffered whole.
    The browser's built-in speechSynthesis is the offline fallback (used
    client-side when this call fails or there's no OpenAI key) — it works
    with no network, but sounds robotic on most systems. This endpoint is
    for when we're online and want a genuinely natural-sounding voice.

    Streaming (2026-09-22): the old version awaited resp.read() — the
    WHOLE clip — before returning anything. Measured against the real
    OpenAI API: first audio bytes arrive noticeably before the full clip
    finishes generating (a real, measured example: first chunk at 1.5s,
    full clip only done at 2.2s — the gap grows with longer answers). That
    entire difference was pure dead air the teacher sat through waiting for
    narration to START, on top of an already-measured ~10s round trip for
    the rest of the voice pipeline. Streaming forwards each chunk to the
    frontend as OpenAI produces it; see api.voiceSpeak in the frontend for
    the MediaSource-based progressive playback that actually uses this.

    The first chunk is fetched (and any failure raised as a clean
    HTTPException) BEFORE the streaming response is started — once
    StreamingResponse begins, the 200 status is already committed and a
    later failure can only silently end the stream, not report an error
    status the frontend's `!res.ok` check would catch.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(503, "OpenAI API key not configured — use offline TTS")

    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "No text to speak")

    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    kwargs = {"model": "gpt-4o-mini-tts", "voice": "nova", "input": text, "response_format": "mp3"}
    if body.instructions:
        kwargs["instructions"] = body.instructions

    try:
        # Explicit timeout — same fix as whisper_service.transcribe(): the
        # SDK's own default (no timeout passed) is ~600s plus automatic
        # retries, which on a slow/flaky connection can hang far longer
        # than a teacher would ever wait for narration to start.
        stream_cm = client.audio.speech.with_streaming_response.create(**kwargs, timeout=30.0)
        resp = await stream_cm.__aenter__()
        chunk_iter = resp.iter_bytes()
        first_chunk = await chunk_iter.__anext__()
    except Exception as exc:
        logger.warning("Voice speak: OpenAI TTS failed: %s", exc)
        raise HTTPException(502, "TTS generation failed — use offline TTS")

    async def audio_chunks():
        try:
            yield first_chunk
            async for chunk in chunk_iter:
                yield chunk
        except Exception as exc:
            logger.warning("Voice speak: streaming interrupted mid-clip: %s", exc)
        finally:
            await stream_cm.__aexit__(None, None, None)

    return StreamingResponse(audio_chunks(), media_type="audio/mpeg")


@router.post("/classify-intent", response_model=VoiceCommandResponse)
async def classify_intent(body: ClassifyIntentRequest, _: CurrentTeacher):
    """
    Text-in, intent-out. Lets us verify local/cloud intent classification
    directly (curl a transcript) without needing microphone/audio plumbing.
    """
    settings = get_settings()
    result = await voice_intent_service.classify_intent(
        body.transcript,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_intent_model,
        openai_api_key=settings.openai_api_key,
        timeout_sec=settings.voice_intent_timeout_sec,
        local_enabled=settings.local_llm_enabled,
    )
    return VoiceCommandResponse(transcript=body.transcript, **result)


@router.post("/ask", response_model=BrainAnswer)
async def ask(body: AskRequest, teacher_id: CurrentTeacher, db: DB):
    """
    Text-in, grounded-answer-out. Bypasses intent classification — for
    directly testing the Classroom Brain (context retrieval + Qwen/OpenAI
    answer) without needing audio or the full command pipeline.
    """
    settings = get_settings()
    result = await classroom_brain_service.answer_question(
        body.question,
        teacher_id=teacher_id,
        db=db,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_brain_model,
        openai_api_key=settings.openai_api_key,
        subject=body.subject,
        grade=body.grade,
        timeout_sec=settings.voice_intent_timeout_sec,
        local_enabled=settings.local_llm_enabled,
    )
    return BrainAnswer(**result)


@router.post("/command", response_model=VoiceCommandResponse)
async def voice_command(
    teacher_id: CurrentTeacher,
    db: DB,
    audio: UploadFile = File(...),
    language: str | None = Form(None),
    transcript_hint: str | None = Form(None),
):
    """
    Full pipeline: audio in -> Whisper transcription -> intent classification
    -> (if the intent is a question) Classroom Brain answer.
    The frontend is responsible for executing every OTHER intent (create
    session, capture frame, generate notes, etc.) using its existing API
    calls — this endpoint only understands what was said and, for questions,
    answers directly.

    If the frontend already transcribed via /voice/transcribe (to show the
    transcript immediately), pass it as transcript_hint to skip re-running
    Whisper here.
    """
    t_start = time.monotonic()
    settings = get_settings()

    if transcript_hint is not None:
        transcript = transcript_hint
    else:
        transcript = ""
        audio_bytes = await audio.read()
        if settings.local_whisper_enabled or settings.openai_api_key:
            try:
                result = await _transcribe_command(audio_bytes, audio.filename or "command.webm", language, settings)
                transcript = result.text
            except Exception as exc:
                logger.warning("Voice command: transcription failed: %s", exc)

    intent_result = await voice_intent_service.classify_intent(
        transcript,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_intent_model,
        openai_api_key=settings.openai_api_key,
        timeout_sec=settings.voice_intent_timeout_sec,
        local_enabled=settings.local_llm_enabled,
    )

    brain_answer = None
    if intent_result["intent"] == "ask_question":
        question = intent_result["params"].get("question") or transcript
        brain_result = await classroom_brain_service.answer_question(
            question,
            teacher_id=teacher_id,
            db=db,
            ollama_base_url=settings.ollama_base_url,
            ollama_model=settings.ollama_brain_model,
            openai_api_key=settings.openai_api_key,
            subject=intent_result["params"].get("subject"),
            grade=intent_result["params"].get("grade"),
            timeout_sec=settings.voice_intent_timeout_sec,
            local_enabled=settings.local_llm_enabled,
        )
        brain_answer = BrainAnswer(**brain_result)

    if intent_result["intent"] in ("open_session", "delete_session"):
        author = intent_result["params"].get("author")
        matched = await _resolve_session(
            db, teacher_id,
            intent_result["params"].get("subject"),
            intent_result["params"].get("grade"),
            intent_result["params"].get("title"),
            author,
            intent_result["params"].get("days_ago"),
        )
        if matched is not None and intent_result["intent"] == "delete_session" and matched.teacher_id != teacher_id:
            # An author name can find another teacher's session (open/view is
            # meant to search across the whole school), but finding it isn't
            # the same as being allowed to delete it — that stays restricted
            # to the teacher's own sessions, full stop.
            intent_result["params"]["not_authorized"] = True
            intent_result["params"]["session_label"] = (
                f"{matched.title or matched.subject or matched.grade or 'session'} "
                f"(by {author or 'another teacher'})"
            )
        elif matched is not None:
            intent_result["params"]["session_id"] = str(matched.id)
            # For delete_session the frontend shows this in the confirmation
            # prompt ("Delete the Newton's Laws session from Sep 3?") — the
            # teacher needs to see WHICH session was found before confirming.
            # Title is the most specific identifier when set (many sessions
            # have no subject), so prefer it.
            label = f"{matched.title or matched.subject or matched.grade or 'session'} ({matched.created_at.strftime('%b %-d')})"
            # Show who actually taught it whenever known — not just when the
            # teacher_id differs (this app has no real per-person login, so
            # instructor_name is the only "whose session is this" signal
            # that exists in practice; showing it lets a human catch "that's
            # not mine" before confirming a delete, which is the only real
            # safeguard available without real auth).
            if matched.instructor_name:
                label += f", by {matched.instructor_name}"
            elif author and matched.teacher_id != teacher_id:
                label += f", by {author}"
            intent_result["params"]["session_label"] = label
        else:
            intent_result["params"]["not_found"] = True

    processing_ms = int((time.monotonic() - t_start) * 1000)
    await _log_event(
        db, teacher_id, transcript, intent_result,
        brain_answer.model_dump() if brain_answer else None, processing_ms,
    )

    return VoiceCommandResponse(transcript=transcript, brain_answer=brain_answer, **intent_result)
