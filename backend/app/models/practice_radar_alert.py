import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, UniqueConstraint, func, Uuid
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

_JsonType = JSONB().with_variant(JSON(), "sqlite")


class PracticeRadarAlert(Base):
    """
    A cross-desk misconception alert: several desks working the same
    question made the same mistake (see services/radar_service.py for the
    thresholds). One row per (session, question, misconception code) so a
    nudge doesn't re-fire, a dismissal sticks, and "not what's happening"
    can be counted later as the radar's precision signal.

    status: new | dismissed | false_alarm | acted | resolved
      resolved = the cluster no longer qualifies (desks recovered) while the
      alert was still untouched.
    """

    __tablename__ = "practice_radar_alerts"
    __table_args__ = (UniqueConstraint("session_id", "question_id", "code", name="uq_radar_session_question_code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("practice_questions.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    desk_ids: Mapped[list] = mapped_column(_JsonType, nullable=False)  # station ids in the cluster at last evaluation
    desk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    attempting_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
