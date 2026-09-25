import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AudienceMetric(Base):
    __tablename__ = "audience_metrics"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    minute_number: Mapped[int] = mapped_column(Integer, nullable=False)
    faces_detected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attention_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)   # 0-100
    hand_raises: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Emotion breakdown — % of inference frames where each emotion was dominant
    happy_pct:      Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confused_pct:   Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    surprised_pct:  Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    disengaged_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Per-zone breakdown stored by the backend audience analysis pipeline.
    # Shape: {front: {count, attention_pct, dominant_emotion, emotions: {...}},
    #         middle: {...}, back: {...}}
    zone_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # See session_audio.py for why timezone=True is required here — same
    # bug, same fix: the migration already created this column as TIMESTAMP
    # WITH TIME ZONE; this annotation just needs to agree with it.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
