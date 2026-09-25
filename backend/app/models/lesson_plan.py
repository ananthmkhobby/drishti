import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import String, DateTime, func, Uuid, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class LessonPlan(Base):
    __tablename__ = "lesson_plans"
    __table_args__ = (UniqueConstraint("session_id", name="uq_lesson_plan_session"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    file_path: Mapped[str] = mapped_column(String(500))
    file_type: Mapped[str] = mapped_column(String(10))   # "pdf" | "image"
    raw_text: Mapped[str | None] = mapped_column(String, nullable=True)
    topics: Mapped[Any | None] = mapped_column(JSON, nullable=True)  # list[str]

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
