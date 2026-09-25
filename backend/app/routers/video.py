"""
Video recording endpoint.

POST /sessions/{session_id}/video
  - Accept a full video blob (webm/mp4) — for small recordings
POST /sessions/{session_id}/video/chunks
  - Accept one chunk (upload_id, chunk_index, total_chunks query params)
POST /sessions/{session_id}/video/chunks/{upload_id}/assemble
  - Concatenate chunks and process (same pipeline as full upload)
GET  /sessions/{session_id}/video-analysis
  - Return video recordings with transcript + frame extraction status

Processing pipeline (same for full and chunked):
  - Extract JPEG frames every 10s with ffmpeg → queue OCR for each
  - Extract audio track → transcribe with Whisper → save as SessionAudio row
"""
import asyncio
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from fastapi import APIRouter, BackgroundTasks, File, Query, UploadFile
from sqlalchemy import select, func

from app.dependencies import CurrentTeacher, DB
from app.exceptions import ACIError
from app.models.session import Session
from app.models.frame import Frame
from app.models.job import Job
from app.models.session_audio import SessionAudio
from app.services import storage_service
from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Video"])

_ALLOWED_TYPES = {
    "video/webm": "webm",
    "video/mp4":  "mp4",
    "video/ogg":  "ogg",
}
_MAX_SIZE_MB = 500
_FRAME_INTERVAL_SEC = 10

# Temp dir for chunk assembly — created lazily, never deleted at runtime
_CHUNK_BASE = Path(tempfile.gettempdir()) / "aci_video_chunks"


# ── Shared processing logic ────────────────────────────────────────────────────

async def _process_video_data(
    session_id: uuid.UUID,
    data: bytes,
    ext: str,
    db,
    background_tasks: BackgroundTasks,
    settings,
) -> dict:
    """
    Core video pipeline called by both the full-upload and chunk-assemble routes.

    Saves the raw video, runs ffmpeg to extract frames + audio, creates DB rows,
    queues OCR and Whisper background tasks, and returns the response dict.
    """
    video_id = str(uuid.uuid4())
    video_path = await storage_service.save_video(session_id, video_id, data, ext)

    # Current frame sequence base
    seq_result = await db.execute(
        select(func.count()).where(Frame.session_id == session_id)
    )
    seq_base = seq_result.scalar() or 0

    saved_frame_ids: list[uuid.UUID] = []
    audio_bytes: bytes | None = None
    duration_sec: float | None = None

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_video = Path(tmpdir) / f"input.{ext}"
        tmp_video.write_bytes(data)
        frames_dir = Path(tmpdir) / "frames"
        frames_dir.mkdir()
        audio_file = Path(tmpdir) / "audio.wav"

        # Duration probe
        probe = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(tmp_video),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        probe_out, _ = await probe.communicate()
        try:
            duration_sec = float(probe_out.decode().strip())
        except (ValueError, TypeError):
            duration_sec = None

        # Frame extraction
        frame_proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", str(tmp_video),
            "-vf", f"fps=1/{_FRAME_INTERVAL_SEC}",
            "-q:v", "2",
            str(frames_dir / "frame_%04d.jpg"),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, ferr = await frame_proc.communicate()
        if frame_proc.returncode != 0:
            logger.warning("ffmpeg frames failed: %s", ferr.decode()[-400:])

        # Audio extraction
        audio_proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", str(tmp_video),
            "-vn", "-ar", "16000", "-ac", "1", "-f", "wav", str(audio_file),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, aerr = await audio_proc.communicate()
        if audio_proc.returncode == 0 and audio_file.exists():
            audio_bytes = audio_file.read_bytes()
        else:
            logger.warning("ffmpeg audio extract failed: %s", aerr.decode()[-400:])

        # Persist frames
        for i, fpath in enumerate(sorted(frames_dir.glob("*.jpg"))):
            frame_bytes = fpath.read_bytes()
            local_id = str(uuid.uuid4())
            img_path = await storage_service.save_frame(session_id, local_id, frame_bytes)

            frame_row = Frame(
                id=uuid.uuid4(),
                local_frame_id=local_id,
                session_id=session_id,
                sequence_no=seq_base + i + 1,
                image_path=img_path,
                image_size_kb=len(frame_bytes) // 1024,
                captured_at=datetime.now(timezone.utc),
                ocr_status="pending",
            )
            db.add(frame_row)
            await db.flush()

            job = Job(
                id=uuid.uuid4(),
                job_type="ocr_processing",
                session_id=session_id,
                frame_id=frame_row.id,
                status="queued",
            )
            db.add(job)
            saved_frame_ids.append(frame_row.id)

    # Update session frame count
    session = await db.get(Session, session_id)
    if session:
        session.frame_count = (session.frame_count or 0) + len(saved_frame_ids)

    # Create SessionAudio row (transcript fills in the background)
    count_res = await db.execute(
        select(func.count()).where(SessionAudio.session_id == session_id)
    )
    rec_number = (count_res.scalar() or 0) + 1

    audio_row = SessionAudio(
        id=uuid.uuid4(),
        session_id=session_id,
        recording_number=rec_number,
        source="video",
        file_path=video_path,
        file_type=ext,
        duration_sec=duration_sec,
        transcript=None,
        segments=None,
        whisper_language=None,
        whisper_tokens=None,
    )
    db.add(audio_row)
    await db.commit()
    audio_row_id = audio_row.id

    # Queue OCR + Whisper background tasks
    for frame_id in saved_frame_ids:
        background_tasks.add_task(_run_ocr_background, frame_id)

    if audio_bytes and settings.openai_api_key:
        background_tasks.add_task(
            _run_whisper_background, audio_row_id, audio_bytes, duration_sec
        )

    logger.info(
        "Video processed: session=%s frames=%d duration=%.1fs",
        session_id, len(saved_frame_ids), duration_sec or 0,
    )
    return {
        "video_id": video_id,
        "duration_sec": duration_sec,
        "frame_count": len(saved_frame_ids),
        "transcript": None,
        "transcribed": False,
        "language": None,
        "recording_number": rec_number,
    }


# ── Full single-blob upload ────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/video", status_code=201)
async def upload_video(
    session_id: uuid.UUID,
    background_tasks: BackgroundTasks,
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
        raise ACIError("FILE_TOO_LARGE", f"Video exceeds {_MAX_SIZE_MB} MB", 400)
    if len(data) < 1000:
        raise ACIError("FILE_EMPTY", "Video file appears empty", 400)

    return await _process_video_data(session_id, data, ext, db, background_tasks, settings)


# ── Chunked upload ─────────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/video/chunks", status_code=200)
async def upload_video_chunk(
    session_id: uuid.UUID,
    db: DB,
    _: CurrentTeacher,
    upload_id: str = Query(...),
    chunk_index: int = Query(..., ge=0),
    total_chunks: int = Query(..., ge=1),
    file: UploadFile = File(...),
):
    """Store one chunk. Returns progress info. Call assemble when all chunks are sent."""
    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    chunk_dir = _CHUNK_BASE / upload_id
    chunk_dir.mkdir(parents=True, exist_ok=True)

    chunk_data = await file.read()
    if not chunk_data:
        raise ACIError("CHUNK_EMPTY", "Received empty chunk", 400)

    chunk_path = chunk_dir / f"chunk_{chunk_index:05d}"
    chunk_path.write_bytes(chunk_data)

    received = len(list(chunk_dir.glob("chunk_*")))
    logger.info(
        "Chunk %d/%d received for upload_id=%s session=%s (%.1f KB)",
        chunk_index + 1, total_chunks, upload_id, session_id, len(chunk_data) / 1024,
    )
    return {
        "upload_id": upload_id,
        "chunk_index": chunk_index,
        "chunks_received": received,
        "total_chunks": total_chunks,
        "complete": received >= total_chunks,
    }


@router.post("/sessions/{session_id}/video/chunks/{upload_id}/assemble", status_code=201)
async def assemble_video_chunks(
    session_id: uuid.UUID,
    upload_id: str,
    background_tasks: BackgroundTasks,
    db: DB,
    _: CurrentTeacher,
    total_chunks: int = Query(..., ge=1),
    content_type: str = Query(default="video/webm"),
):
    """Concatenate stored chunks and run the video processing pipeline."""
    settings = get_settings()

    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    chunk_dir = _CHUNK_BASE / upload_id
    if not chunk_dir.exists():
        raise ACIError("CHUNKS_NOT_FOUND", "No chunks found for this upload_id — upload chunks first", 404)

    chunks = sorted(chunk_dir.glob("chunk_*"))
    if len(chunks) < total_chunks:
        raise ACIError(
            "CHUNKS_INCOMPLETE",
            f"Expected {total_chunks} chunks, only {len(chunks)} received",
            400,
        )

    # Concatenate in order
    data = b"".join(c.read_bytes() for c in chunks)

    # Clean up chunks dir immediately
    shutil.rmtree(chunk_dir, ignore_errors=True)

    size_mb = len(data) / (1024 * 1024)
    if size_mb > _MAX_SIZE_MB:
        raise ACIError("FILE_TOO_LARGE", f"Assembled video exceeds {_MAX_SIZE_MB} MB", 400)

    ct_clean = content_type.split(";")[0].strip().lower()
    ext = _ALLOWED_TYPES.get(ct_clean, "webm")

    logger.info(
        "Assembling %d chunks (%.1f MB) for session=%s upload_id=%s",
        total_chunks, size_mb, session_id, upload_id,
    )
    return await _process_video_data(session_id, data, ext, db, background_tasks, settings)


# ── Video analysis view ────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/video-analysis")
async def get_video_analysis(session_id: uuid.UUID, db: DB, _: CurrentTeacher):
    """
    Return all video recordings for a session with transcript and frame data.
    Shows what data was extracted from each video upload.
    """
    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    # Video-sourced audio rows
    video_rows = (
        await db.execute(
            select(SessionAudio)
            .where(
                SessionAudio.session_id == session_id,
                SessionAudio.source == "video",
            )
            .order_by(SessionAudio.recording_number)
        )
    ).scalars().all()

    # Frames extracted from video (those created near video upload times)
    # We approximate by returning total frame count — frames don't store their source
    frame_count_result = await db.execute(
        select(func.count()).where(Frame.session_id == session_id)
    )
    total_frames = frame_count_result.scalar() or 0

    recordings = []
    for row in video_rows:
        recordings.append({
            "audio_id": str(row.id),
            "recording_number": row.recording_number,
            "source": row.source,
            "file_type": row.file_type,
            "duration_sec": row.duration_sec,
            "transcribed": bool(row.transcript),
            "transcript": row.transcript,
            "language": row.whisper_language,
            "segment_count": len(row.segments or []),
        })

    return {
        "session_id": str(session_id),
        "video_recording_count": len(video_rows),
        "total_frames_in_session": total_frames,
        "frame_interval_sec": _FRAME_INTERVAL_SEC,
        "recordings": recordings,
        "has_transcripts": any(r["transcribed"] for r in recordings),
    }


# ── Background helpers ─────────────────────────────────────────────────────────

async def _run_ocr_background(frame_id: uuid.UUID):
    from app.database import _get_session_factory
    from app.ocr import ocr_service
    factory = _get_session_factory()
    async with factory() as db:
        try:
            await ocr_service.run_ocr_for_frame(frame_id, db)
        except Exception:
            logger.exception("Background OCR failed for video frame %s", frame_id)
            try:
                frame = await db.get(Frame, frame_id)
                if frame and frame.ocr_status not in ("done", "failed"):
                    frame.ocr_status = "failed"
                    await db.commit()
            except Exception:
                pass


async def _run_whisper_background(
    audio_row_id: uuid.UUID,
    audio_bytes: bytes,
    duration_sec: float | None,
) -> None:
    from app.database import _get_session_factory
    from app.config import get_settings
    from app.services.whisper_service import transcribe
    from app.services.event_service import emit as emit_event

    settings = get_settings()
    try:
        result = await transcribe(audio_bytes, "audio.wav", settings.openai_api_key, language=settings.whisper_language or None)
        transcript = result.text or None
        segments   = result.segments
        language   = result.language
        tokens     = max(1, int(result.duration_sec or duration_sec or 0) * 10)
    except Exception as exc:
        logger.warning("Background Whisper failed for audio_row %s: %s", audio_row_id, exc)
        return

    factory = _get_session_factory()
    async with factory() as db:
        row = await db.get(SessionAudio, audio_row_id)
        if not row:
            return
        row.transcript       = transcript
        row.segments         = segments
        row.whisper_language = language
        row.whisper_tokens   = tokens
        await db.commit()
        logger.info(
            "Background Whisper done: audio_row=%s chars=%d lang=%s",
            audio_row_id, len(transcript or ""), language,
        )
        try:
            await emit_event(
                db, "AUDIO_TRANSCRIBED",
                session_id=row.session_id,
                payload={"audio_id": str(audio_row_id), "transcribed": transcript is not None},
            )
        except Exception:
            pass
