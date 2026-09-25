import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, Text, func, Uuid, ForeignKey
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

_JsonType = JSONB().with_variant(JSON(), "sqlite")


class PracticeQuestion(Base):
    """
    A ThinkStep guided-practice question, generated from a lecture session's
    board/notebook OCR content. Distinct from QuizQuestion (MCQ/TF/poll,
    generated for quick recall checks) — this carries a full accepted-solution
    graph and known misconceptions so a student's handwritten work can be
    validated against it, not just multiple-choice-matched.
    """

    __tablename__ = "practice_questions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ai_output_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_outputs.id", ondelete="SET NULL"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    subject: Mapped[str | None] = mapped_column(String(100), nullable=True)
    topic: Mapped[str | None] = mapped_column(String(255), nullable=True)
    skill_tag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    difficulty: Mapped[str | None] = mapped_column(String(20), nullable=True)  # easy | medium | hard

    text: Mapped[str] = mapped_column(Text, nullable=False)

    # numeric | algebraic | conceptual | diagram | other — routes Gate D:
    # only "numeric"/"algebraic" get a deterministic check, everything else
    # goes straight to the LLM solution-graph validator (Gate E).
    answer_domain: Mapped[str] = mapped_column(String(20), nullable=False, default="other")

    # Ordered list of accepted approaches, each a list of normalized steps.
    # Never sent to the client as-is outside the teacher review screen — the
    # leakage guard checks candidate hints against this, it doesn't source them.
    expected_solution_graph: Mapped[list | None] = mapped_column(_JsonType, nullable=True)
    # Canonical final answer(s), used only for the answer-leakage check.
    final_answer: Mapped[dict | None] = mapped_column(_JsonType, nullable=True)
    # [{code, description, trigger_pattern}]
    known_misconceptions: Mapped[list | None] = mapped_column(_JsonType, nullable=True)

    # ai_generated for MVP; teacher_authored reserved for a later phase.
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="ai_generated")
    generated_from_ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # pending_review | approved | rejected | archived — teacher must approve
    # an AI-generated question (and the solution graph it will be validated
    # against) before a student ever sees it.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending_review")
    teacher_edited: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
