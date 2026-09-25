import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, func, Uuid, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class Frame(Base):
    __tablename__ = "frames"
    __table_args__ = (
        UniqueConstraint("session_id", "local_frame_id", name="uq_frame_local_id"),
        UniqueConstraint("session_id", "sequence_no", name="uq_frame_seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    local_frame_id: Mapped[str] = mapped_column(String(100), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_size_kb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # pending | processing | done | failed
    ocr_status: Mapped[str] = mapped_column(String(30), default="pending")
    ai_status: Mapped[str] = mapped_column(String(30), default="pending")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
