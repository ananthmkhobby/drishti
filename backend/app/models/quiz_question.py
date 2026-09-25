import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, func, Uuid, ForeignKey, Text
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

_JsonType = JSONB().with_variant(JSON(), "sqlite")


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ai_output_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_outputs.id", ondelete="SET NULL"), nullable=True
    )
    # mcq | true_false | poll
    question_type: Mapped[str] = mapped_column(String(20), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list | None] = mapped_column(_JsonType, nullable=True)
    correct_answer: Mapped[dict | None] = mapped_column(_JsonType, nullable=True)
    # remember | understand | apply | analyze | evaluate | create
    # remember | understand | apply | analyze | evaluate | create
    bloom_level: Mapped[str | None] = mapped_column(String(30), nullable=True)
    topic: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # AI-generated skill identifier — used by TiQer for skill-level tracking
    skill_tag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    teacher_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    tiqer_exported: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
