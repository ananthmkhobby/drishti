import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime, func, Uuid, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class TiQerExportLog(Base):
    """Audit log of every TiQer export — one row per export action."""

    __tablename__ = "tiqer_export_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    tiqer_class_id: Mapped[str] = mapped_column(String(255), nullable=False)
    tiqer_session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, default=0)
    schedule_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Full serialised TiQer payload — stored for replay / audit
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    exported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
