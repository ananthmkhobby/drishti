import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, func, Uuid, ForeignKey, Text
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

_JsonType = JSONB().with_variant(JSON(), "sqlite")


class ExperimentSuggestion(Base):
    """
    Low-cost classroom experiment suggested by AI for a topic detected in a session.

    Kept as a separate table (not embedded JSONB in ai_outputs) so the dashboard
    can query by topic, difficulty, or teacher-approval status without JSON unpacking.
    See ADR-011.
    """

    __tablename__ = "experiment_suggestions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ai_output_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_outputs.id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    topic: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # easy | medium | hard — relative to rural classroom resources
    difficulty: Mapped[str | None] = mapped_column(String(30), nullable=True)

    materials: Mapped[list | None] = mapped_column(_JsonType, nullable=True)
    steps: Mapped[list | None] = mapped_column(_JsonType, nullable=True)
    expected_outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    safety_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Teacher feedback
    teacher_approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
