import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, func, Uuid, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class Classroom(Base):
    """
    A physical classroom inside a school.

    Referred to as 'classes' in the API surface but 'classrooms' in the
    data model to avoid collision with the Python keyword 'class'.
    """

    __tablename__ = "classrooms"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    grade: Mapped[str | None] = mapped_column(String(50), nullable=True)
    section: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # chalkboard | whiteboard | smartboard
    board_type: Mapped[str] = mapped_column(String(50), default="chalkboard")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
