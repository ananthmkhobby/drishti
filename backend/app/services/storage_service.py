"""
Storage service — saves uploaded frame images.

MVP: local filesystem under UPLOAD_DIR.
Phase 2: swap to S3 by setting USE_S3=true.
"""
import uuid
import os
import aiofiles
from pathlib import Path
from app.config import get_settings


async def save_frame(session_id: uuid.UUID, frame_local_id: str, data: bytes) -> str:
    """Persist a frame image and return its storage path."""
    settings = get_settings()

    if settings.use_s3:
        return await _save_to_s3(session_id, frame_local_id, data)
    return await _save_to_local(session_id, frame_local_id, data)


async def _save_to_local(session_id: uuid.UUID, frame_local_id: str, data: bytes) -> str:
    settings = get_settings()
    base = Path(settings.upload_dir) / "sessions" / str(session_id) / "frames"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{frame_local_id}.jpg"
    async with aiofiles.open(path, "wb") as f:
        await f.write(data)
    return str(path)


async def _save_to_s3(session_id: uuid.UUID, frame_local_id: str, data: bytes) -> str:
    # TODO Phase 2: upload to S3, return s3://bucket/key
    import boto3
    settings = get_settings()
    key = f"sessions/{session_id}/frames/{frame_local_id}.jpg"
    s3 = boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    s3.put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType="image/jpeg")
    return f"s3://{settings.s3_bucket}/{key}"


async def delete_blob(path: str | None) -> None:
    """
    Best-effort delete of a file previously saved by this module (local disk
    or S3), by whatever path was stored on the owning row. Never raises —
    deleting a database row shouldn't fail just because its file was already
    gone or storage is briefly unreachable; this is cleanup, not the
    source of truth (the DB row's removal is what actually matters).
    """
    if not path:
        return
    try:
        if path.startswith("s3://"):
            import boto3
            settings = get_settings()
            without_prefix = path[len("s3://"):]
            bucket, _, key = without_prefix.partition("/")
            s3 = boto3.client(
                "s3",
                region_name=settings.aws_region,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
            )
            s3.delete_object(Bucket=bucket, Key=key)
        else:
            Path(path).unlink(missing_ok=True)
    except Exception:
        pass


async def load_frame_bytes(image_path: str) -> bytes:
    """
    Load image bytes from storage (local filesystem or S3).
    `image_path` is the value stored in Frame.image_path.
    """
    if image_path.startswith("s3://"):
        return await _load_from_s3(image_path)
    async with aiofiles.open(image_path, "rb") as f:
        return await f.read()


async def _load_from_s3(s3_path: str) -> bytes:
    """Download object from S3. s3_path format: s3://bucket/key"""
    import io
    import boto3
    settings = get_settings()
    # Parse s3://bucket/key
    without_prefix = s3_path[len("s3://"):]
    bucket, _, key = without_prefix.partition("/")
    s3 = boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    buf = io.BytesIO()
    s3.download_fileobj(bucket, key, buf)
    return buf.getvalue()


async def _save_blob_to_s3(session_id: uuid.UUID, file_id: str, data: bytes, ext: str, subfolder: str) -> str:
    """Upload any blob (audio/video/lesson-plan) to S3 and return the s3:// path."""
    import boto3
    settings = get_settings()
    content_types = {
        "webm": "video/webm", "mp4": "video/mp4", "ogg": "audio/ogg",
        "wav": "audio/wav", "m4a": "audio/mp4", "pdf": "application/pdf",
        "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    }
    key = f"sessions/{session_id}/{subfolder}/{file_id}.{ext}"
    s3 = boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    s3.put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=data,
        ContentType=content_types.get(ext.lower(), "application/octet-stream"),
    )
    return f"s3://{settings.s3_bucket}/{key}"


async def _save_blob_to_local(session_id: uuid.UUID, file_id: str, data: bytes, ext: str, subfolder: str) -> str:
    settings = get_settings()
    base = Path(settings.upload_dir) / "sessions" / str(session_id) / subfolder
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{file_id}.{ext}"
    async with aiofiles.open(path, "wb") as f:
        await f.write(data)
    return str(path)


async def save_audio(session_id: uuid.UUID, file_id: str, data: bytes, ext: str) -> str:
    """Persist a session audio recording and return its storage path."""
    settings = get_settings()
    if settings.use_s3:
        return await _save_blob_to_s3(session_id, file_id, data, ext, "audio")
    return await _save_blob_to_local(session_id, file_id, data, ext, "audio")


async def save_video(session_id: uuid.UUID, file_id: str, data: bytes, ext: str) -> str:
    """Persist a session video recording and return its storage path."""
    settings = get_settings()
    if settings.use_s3:
        return await _save_blob_to_s3(session_id, file_id, data, ext, "videos")
    return await _save_blob_to_local(session_id, file_id, data, ext, "videos")


async def save_lesson_plan(session_id: uuid.UUID, file_id: str, data: bytes, ext: str) -> str:
    """Persist a lesson plan file and return its storage path."""
    settings = get_settings()
    if settings.use_s3:
        return await _save_blob_to_s3(session_id, file_id, data, ext, "lesson_plans")
    return await _save_blob_to_local(session_id, file_id, data, ext, "lesson_plans")


async def save_textbook(session_id: uuid.UUID, file_id: str, data: bytes, ext: str) -> str:
    """Persist an uploaded textbook PDF and return its storage path."""
    settings = get_settings()
    if settings.use_s3:
        return await _save_blob_to_s3(session_id, file_id, data, ext, "textbooks")
    return await _save_blob_to_local(session_id, file_id, data, ext, "textbooks")


async def save_textbook_figure(session_id: uuid.UUID, textbook_id: uuid.UUID, page_number: int, index: int, data: bytes) -> str:
    """Persist a cropped, vision-verified textbook diagram and return its storage path."""
    settings = get_settings()
    file_id = f"{textbook_id}_p{page_number}_{index}"
    if settings.use_s3:
        return await _save_blob_to_s3(session_id, file_id, data, "jpg", "textbook_figures")
    return await _save_blob_to_local(session_id, file_id, data, "jpg", "textbook_figures")


async def save_diagram(session_id: uuid.UUID, frame_id: str, index: int, data: bytes) -> str:
    """Persist a cropped board-diagram image and return its storage path."""
    settings = get_settings()
    file_id = f"{frame_id}_diagram{index}"
    if settings.use_s3:
        return await _save_blob_to_s3(session_id, file_id, data, "jpg", "diagrams")
    return await _save_blob_to_local(session_id, file_id, data, "jpg", "diagrams")


async def save_practice_attempt_image(session_id: uuid.UUID, attempt_id: str, data: bytes) -> str:
    """Persist a ThinkStep guided-practice notebook capture and return its storage path."""
    settings = get_settings()
    if settings.use_s3:
        return await _save_blob_to_s3(session_id, attempt_id, data, "jpg", "practice_attempts")
    return await _save_blob_to_local(session_id, attempt_id, data, "jpg", "practice_attempts")


async def save_practice_attempt_audio(session_id: uuid.UUID, attempt_id: str, data: bytes) -> str:
    """Persist a ThinkStep guided-practice spoken answer and return its storage path."""
    settings = get_settings()
    if settings.use_s3:
        return await _save_blob_to_s3(session_id, attempt_id, data, "webm", "practice_attempts")
    return await _save_blob_to_local(session_id, attempt_id, data, "webm", "practice_attempts")


async def save_practice_tutor_image(session_id: uuid.UUID, message_id: str, data: bytes) -> str:
    """Persist a frame sent alongside one AI-tutor conversation turn (see
    PracticeTutorMessage) — same convention as save_practice_attempt_image,
    separate subfolder since these aren't graded attempts."""
    settings = get_settings()
    if settings.use_s3:
        return await _save_blob_to_s3(session_id, message_id, data, "jpg", "practice_tutor")
    return await _save_blob_to_local(session_id, message_id, data, "jpg", "practice_tutor")


def presigned_upload_url(session_id: uuid.UUID, frame_local_id: str) -> str:
    """Generate a presigned S3 URL for direct device upload (used by bulk sync)."""
    settings = get_settings()
    if not settings.use_s3:
        return f"/v1/sessions/{session_id}/frames"  # Fall back to normal upload endpoint
    import boto3
    key = f"sessions/{session_id}/frames/{frame_local_id}.jpg"
    s3 = boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    return s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.s3_bucket, "Key": key, "ContentType": "image/jpeg"},
        ExpiresIn=3600,
    )
