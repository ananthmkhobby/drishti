import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, func, Uuid, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # ocr_processing | ai_generation
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    frame_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # queued | processing | completed | failed
    status: Mapped[str] = mapped_column(String(30), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    result_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
