import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, func, Uuid, ForeignKey, Text
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

_JsonType = JSONB().with_variant(JSON(), "sqlite")


class ClassroomMemory(Base):
    __tablename__ = "classroom_memory"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    last_session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    topics_covered: Mapped[list | None] = mapped_column(_JsonType, nullable=True)
    pending_concepts: Mapped[list | None] = mapped_column(_JsonType, nullable=True)
    suggested_next: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
