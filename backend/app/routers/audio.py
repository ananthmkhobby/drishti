"""
Session audio endpoints.

POST /sessions/{session_id}/audio   — upload a new recording, trigger Whisper
GET  /sessions/{session_id}/audio   — return ALL recordings (list)
POST /sessions/{session_id}/audio/{audio_id}/transcribe — retry failed transcription
DELETE /sessions/{session_id}/audio/{audio_id} — delete one recording
"""
import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, File, UploadFile
from sqlalchemy import select, func

from app.dependencies import CurrentTeacher, DB
from app.exceptions import ACIError
from app.models.session import Session
from app.models.session_audio import SessionAudio
from app.services import storage_service
from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Audio"])

_ALLOWED_TYPES = {
    "audio/webm":  "webm",
    "audio/ogg":   "ogg",
    "audio/mp4":   "mp4",
    "audio/x-m4a": "m4a",
    "audio/mpeg":  "mp3",
    "audio/wav":   "wav",
    "video/webm":  "webm",  # Chrome records video/webm even for audio-only
}

_MAX_SIZE_MB = 200


@router.post("/sessions/{session_id}/audio", status_code=201)
async def upload_audio(
    session_id: uuid.UUID,
    db: DB,
    _: CurrentTeacher,
    file: UploadFile = File(...),
):
    settings = get_settings()

    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    ext = _ALLOWED_TYPES.get(content_type, "webm")

    data = await file.read()
    size_mb = len(data) / (1024 * 1024)
    if size_mb > _MAX_SIZE_MB:
        raise ACIError("FILE_TOO_LARGE", f"Audio exceeds {_MAX_SIZE_MB} MB limit", 400)
    if len(data) < 100:
        raise ACIError("FILE_EMPTY", "Audio file appears to be empty", 400)

    # Determine recording number (next in sequence for this session)
    count_result = await db.execute(
        select(func.count()).where(SessionAudio.session_id == session_id)
    )
    existing_count = count_result.scalar() or 0
    recording_number = existing_count + 1

    # Save to disk
    file_id = str(uuid.uuid4())
    file_path = await storage_service.save_audio(session_id, file_id, data, ext)

    # Transcribe with Whisper
    transcript: str | None = None
    segments: list | None = None
    language: str | None = None
    duration_sec: float | None = None
    whisper_tokens: int | None = None

    if settings.openai_api_key:
        try:
            from app.services.whisper_service import transcribe
            result = await transcribe(data, f"recording.{ext}", settings.openai_api_key, language=settings.whisper_language or None)
            transcript = result.text
            segments = result.segments
            language = result.language
            duration_sec = result.duration_sec
            whisper_tokens = max(1, int(duration_sec or 0) * 10)
        except Exception as exc:
            logger.warning("Whisper transcription failed for session %s: %s", session_id, exc)

    row = SessionAudio(
        id=uuid.uuid4(),
        session_id=session_id,
        recording_number=recording_number,
        file_path=file_path,
        file_type=ext,
        duration_sec=duration_sec,
        transcript=transcript,
        segments=segments,
        whisper_language=language,
        whisper_tokens=whisper_tokens,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    # Emit sync event so clients polling for completions get notified
    from app.services.event_service import emit as emit_event
    await emit_event(db, "AUDIO_TRANSCRIBED", session_id=session_id,
                     payload={"audio_id": str(row.id), "transcribed": transcript is not None})

    return {
        "audio_id": str(row.id),
        "session_id": str(session_id),
        "recording_number": recording_number,
        "duration_sec": duration_sec,
        "transcript": transcript,
        "segment_count": len(segments or []),
        "language": language,
        "transcribed": transcript is not None,
    }


@router.post("/sessions/{session_id}/audio/{audio_id}/transcribe")
async def retry_transcription(
    session_id: uuid.UUID,
    audio_id: uuid.UUID,
    db: DB,
    _: CurrentTeacher,
):
    """
    Re-run Whisper on a stored recording whose original transcription failed
    (transcript is NULL). Reads the file back from storage — no re-upload needed.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        raise ACIError("AI_NOT_CONFIGURED", "OPENAI_API_KEY is not configured", 400)

    result = await db.execute(
        select(SessionAudio).where(
            SessionAudio.id == audio_id,
            SessionAudio.session_id == session_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise ACIError("AUDIO_NOT_FOUND", "Recording not found", 404)

    try:
        data = await storage_service.load_frame_bytes(row.file_path)
    except Exception as exc:
        logger.warning("Could not load audio file %s: %s", row.file_path, exc)
        raise ACIError("FILE_MISSING", "Stored audio file could not be read", 410)

    from app.services.whisper_service import transcribe
    try:
        tr = await transcribe(data, f"recording.{row.file_type}", settings.openai_api_key, language=settings.whisper_language or None)
    except Exception as exc:
        logger.warning("Whisper retry failed for audio %s: %s", audio_id, exc)
        raise ACIError("TRANSCRIPTION_FAILED", f"Whisper failed: {str(exc)[:200]}", 502)

    row.transcript = tr.text
    row.segments = tr.segments
    row.whisper_language = tr.language
    row.duration_sec = tr.duration_sec
    row.whisper_tokens = max(1, int(tr.duration_sec or 0) * 10)
    await db.commit()
    await db.refresh(row)

    from app.services.event_service import emit as emit_event
    await emit_event(db, "AUDIO_TRANSCRIBED", session_id=session_id,
                     payload={"audio_id": str(row.id), "transcribed": True, "retry": True})

    return {
        "audio_id": str(row.id),
        "session_id": str(session_id),
        "recording_number": row.recording_number,
        "duration_sec": row.duration_sec,
        "transcript": row.transcript,
        "segment_count": len(row.segments or []),
        "language": row.whisper_language,
        "transcribed": True,
    }


@router.get("/sessions/{session_id}/audio")
async def get_audio(
    session_id: uuid.UUID,
    db: DB,
    _: CurrentTeacher,
):
    """Return all recordings for a session, ordered by recording_number."""
    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    result = await db.execute(
        select(SessionAudio)
        .where(SessionAudio.session_id == session_id)
        .order_by(SessionAudio.recording_number)
    )
    rows = result.scalars().all()

    # Compute engagement metrics from segments if available
    from app.services.engagement_service import compute_engagement_metrics
    rows_with_segments = [r for r in rows if r.segments]
    engagement = compute_engagement_metrics(rows_with_segments) if rows_with_segments else None

    return {
        "session_id": str(session_id),
        "recording_count": len(rows),
        "engagement": engagement,
        "recordings": [
            {
                "audio_id": str(r.id),
                "recording_number": r.recording_number,
                "source": r.source,
                "file_type": r.file_type,
                "duration_sec": r.duration_sec,
                "transcript": r.transcript,
                "segments": r.segments or [],
                "language": r.whisper_language,
                "transcribed": r.transcript is not None,
                "whisper_tokens": r.whisper_tokens or 0,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.post("/sessions/{session_id}/audio/{audio_id}/transcribe/retry", status_code=202)
async def retry_transcription(
    session_id: uuid.UUID,
    audio_id: uuid.UUID,
    db: DB,
    _: CurrentTeacher,
):
    """Re-run Whisper on a recording that failed or returned an empty transcript."""
    result = await db.execute(
        select(SessionAudio).where(
            SessionAudio.session_id == session_id,
            SessionAudio.id == audio_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise ACIError("AUDIO_NOT_FOUND", "Recording not found", 404)

    settings = get_settings()
    if not settings.openai_api_key:
        raise ACIError("NO_API_KEY", "OpenAI API key not configured", 503)

    if not row.file_path:
        raise ACIError("NO_FILE", "No audio/video file stored for this recording", 404)

    file_path = row.file_path
    if not file_path.startswith("/"):
        import os
        file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), file_path)

    try:
        import aiofiles
        async with aiofiles.open(file_path, "rb") as f:
            raw_bytes = await f.read()
    except (FileNotFoundError, OSError) as exc:
        raise ACIError("FILE_NOT_FOUND", f"Recording file not found: {exc}", 404)

    # For video files, extract audio with ffmpeg first
    ext = row.file_type or "webm"
    audio_data = raw_bytes
    if ext in ("mp4", "webm", "ogg") and row.source == "video":
        import asyncio, tempfile
        from pathlib import Path as _Path
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_video = _Path(tmpdir) / f"input.{ext}"
            tmp_video.write_bytes(raw_bytes)
            audio_file = _Path(tmpdir) / "audio.wav"
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-i", str(tmp_video),
                "-vn", "-ar", "16000", "-ac", "1", "-f", "wav", str(audio_file),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _, aerr = await proc.communicate()
            if proc.returncode == 0 and audio_file.exists():
                audio_data = audio_file.read_bytes()
                ext = "wav"
            else:
                raise ACIError(
                    "AUDIO_EXTRACT_FAILED",
                    f"Could not extract audio track: {aerr.decode()[-200:]}",
                    422,
                )

    try:
        from app.services.whisper_service import transcribe
        result_tr = await transcribe(audio_data, f"recording.{ext}", settings.openai_api_key, language=settings.whisper_language or None)
        transcript = result_tr.text or None
        segments = result_tr.segments
        language = result_tr.language
        duration_sec = result_tr.duration_sec
        whisper_tokens = max(1, int(duration_sec or 0) * 10)
    except Exception as exc:
        raise ACIError("WHISPER_FAILED", f"Transcription failed: {exc}", 502)

    row.transcript = transcript
    row.segments = segments
    row.whisper_language = language
    if not row.duration_sec:
        row.duration_sec = duration_sec
    row.whisper_tokens = whisper_tokens
    await db.commit()
    await db.refresh(row)

    return {
        "audio_id": str(row.id),
        "transcribed": transcript is not None,
        "transcript": transcript,
        "language": language,
        "segment_count": len(segments or []),
    }


@router.delete("/sessions/{session_id}/audio/{audio_id}", status_code=204)
async def delete_audio(
    session_id: uuid.UUID,
    audio_id: uuid.UUID,
    db: DB,
    _: CurrentTeacher,
):
    result = await db.execute(
        select(SessionAudio).where(
            SessionAudio.session_id == session_id,
            SessionAudio.id == audio_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise ACIError("AUDIO_NOT_FOUND", "Recording not found", 404)
    await db.delete(row)
    await db.commit()
