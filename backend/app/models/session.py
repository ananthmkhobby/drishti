import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import String, Integer, DateTime, func, Uuid, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    classroom_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("classrooms.id", ondelete="SET NULL"), nullable=True, index=True
    )

    local_session_id: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)

    subject: Mapped[str | None] = mapped_column(String(100), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(50), nullable=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Free-text "who's teaching this" — deliberately NOT tied to the real
    # teacher_id/Teacher-account system, since this app runs as a single
    # shared device (skip_auth, one dev_teacher_id) used by multiple actual
    # instructors throughout the day. This is how a teacher tags/finds their
    # own sessions without a real per-person login.
    instructor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    board_type: Mapped[str] = mapped_column(String(50), default="chalkboard")
    capture_mode: Mapped[str] = mapped_column(String(50), default="time_based")
    capture_interval_sec: Mapped[int] = mapped_column(Integer, default=30)

    # active | completed | processing | failed
    status: Mapped[str] = mapped_column(String(30), default="active")
    frame_count: Mapped[int] = mapped_column(Integer, default=0)
    # pending | syncing | synced | failed
    sync_status: Mapped[str] = mapped_column(String(30), default="pending")

    # Board ROI calibration — stores 4 corner points [[x,y], ...] in pixel coordinates
    # of the original frame size.  When set, board_detector skips auto-detection
    # and uses these corners directly for perspective warp.
    board_roi: Mapped[Any | None] = mapped_column(JSON, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Soft delete: set instead of removing the row (and its frames/OCR/AI
    # output data) outright. Deleted sessions are excluded from every listing
    # and lookup query but the underlying data is preserved.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
