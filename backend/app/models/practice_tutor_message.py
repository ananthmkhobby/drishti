import uuid
from datetime import datetime
from sqlalchemy import String, Text, Boolean, DateTime, func, Uuid, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class PracticeTutorMessage(Base):
    """
    One turn (student or tutor) in a Guided Practice "Ask AI Tutor" voice
    conversation — see practice_service.tutor_turn(). Append-only log, not a
    conversation-state store: the live chat itself is stateless server-side
    (the client resends the running history each call, same shape as a
    normal chat API) — this table exists purely so a later report ("how many
    times was the AI asked, what was asked") has real data to read, without
    needing a schema change when that report is built. Same reasoning
    already used for TextbookChapter.taught_log, built ahead of the
    cross-day feature that reads it.

    Deliberately NOT linked to any student-identity concept — this app has
    none (see PracticeStation's own docstring). A future revision-mode
    feature that needs to key history by student will decide how; this
    table only needs station_id for now.
    """

    __tablename__ = "practice_tutor_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    station_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("practice_stations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Nullable — a tutoring conversation can happen with no question assigned
    # yet (a student exploring a concept before one is picked).
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("practice_questions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)  # "student" | "tutor"
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Only ever set on a "student" turn — the frame sent along with that
    # turn's audio. Same storage convention as PracticeAttempt.image_path
    # (see storage_service.save_practice_attempt_image).
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    had_image: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
