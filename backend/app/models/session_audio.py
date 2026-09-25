import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import String, Float, ForeignKey, JSON, Text, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SessionAudio(Base):
    __tablename__ = "session_audios"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recording_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="audio")  # 'audio' | 'video'

    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False, default="webm")
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Whisper output
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    segments: Mapped[Any | None] = mapped_column(JSON, nullable=True)  # list[{start, end, text}]
    whisper_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    whisper_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Confirmed live 2026-09-21: without an explicit timezone=True here,
    # SQLAlchemy infers a plain (naive) DateTime column from the
    # `Mapped[datetime]` annotation, while the actual default value below is
    # timezone-aware (datetime.now(timezone.utc)) — SQLite never cared, but
    # Postgres does, and rejected the INSERT outright with "can't subtract
    # offset-naive and offset-aware datetimes". The real Postgres column
    # (created by migration 0006) was always TIMESTAMP WITH TIME ZONE; only
    # this Python-side annotation was wrong.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
