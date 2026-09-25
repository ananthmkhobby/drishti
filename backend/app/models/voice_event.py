import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, func, Uuid, ForeignKey, Text, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

_JsonType = JSONB().with_variant(JSON(), "sqlite")


class VoiceEvent(Base):
    """
    Local log of every voice-assistant interaction (question, intent,
    answer, timing, which model answered). Not synced anywhere yet — this
    exists so interaction history isn't lost and so a future cloud-sync
    layer has something to sync from, without building that layer now.
    """
    __tablename__ = "voice_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False, index=True
    )

    transcript: Mapped[str] = mapped_column(Text, default="")
    intent: Mapped[str] = mapped_column(String(50), default="unknown")
    params: Mapped[dict | None] = mapped_column(_JsonType, nullable=True)
    intent_source: Mapped[str] = mapped_column(String(20), default="none")  # local|cloud|none

    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_source: Mapped[str | None] = mapped_column(String(20), nullable=True)  # local|cloud|none
    needs_clarification: Mapped[bool] = mapped_column(default=False)

    processing_ms: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
