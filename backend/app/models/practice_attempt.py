import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Float, DateTime, Text, func, Uuid, ForeignKey
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

_JsonType = JSONB().with_variant(JSON(), "sqlite")


class PracticeAttempt(Base):
    """
    One notebook capture of a student's work on a PracticeQuestion, and the
    result of running it through Gates A-H. A question is typically attempted
    more than once (attempt_no increments) as the student responds to nudges —
    Gate H's post-hint re-check is just the next attempt on the same question.
    """

    __tablename__ = "practice_attempts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    question_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("practice_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Denormalized for direct session-scoped queries (same pattern as
    # Frame/QuizQuestion), avoids a join through practice_questions.
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Nullable: preserves the original manual-capture path (a teacher/student
    # taps Capture once, no station involved). Populated automatically for
    # attempts produced by a station's periodic auto-capture loop.
    station_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("practice_stations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Free-text, e.g. "Row 3 - Aditi" or a desk number. No student roster
    # exists in this app yet, so this is optional and unvalidated by design.
    student_label: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # "image" (photographed notebook work, the original path) or "audio" (a
    # spoken answer — for theory/conceptual questions with no handwritten
    # work to photograph). Exactly one of image_path/audio_path is set,
    # matching this. Kept as an explicit column rather than inferred from
    # which path is non-null so a future third input type doesn't have to
    # re-derive it from column presence.
    input_type: Mapped[str] = mapped_column(String(10), nullable=False, default="image")
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_size_kb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Gate A
    capture_quality_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    capture_quality_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Gates B/C
    recognized_steps: Mapped[list | None] = mapped_column(_JsonType, nullable=True)
    recognition_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    normalized_step: Mapped[dict | None] = mapped_column(_JsonType, nullable=True)
    # A short factual description of the QUESTION's own labeled figure
    # (circuit, geometric diagram, graph, ...), read off the same photo as
    # recognized_steps — never the student's own work, that stays in
    # recognized_steps. Added 2026-09-30: validate_step only ever sees
    # transcribed text, never the photo itself, so a diagram's own labeled
    # values (a circuit's resistor values, a triangle's angle) were
    # invisible to grading whenever the question's own text didn't happen
    # to restate every value — confirmed live: with sparse question
    # metadata, grading correctly caught a wrong final answer but couldn't
    # diagnose WHY once nothing else in its context mentioned the value
    # that was actually being ignored. Null for audio attempts, and for
    # image attempts with no diagram (the common case).
    diagram_context: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Gate D
    gate_d_result: Mapped[dict | None] = mapped_column(_JsonType, nullable=True)

    # Gates E/F — valid_progress | alternative_valid_method | incomplete |
    # arithmetic_slip | conceptual_misconception | ambiguous | unsupported
    validation_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    validation_reason_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    misconception_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 0-based index into recognized_steps — the specific step the error was
    # first pinpointed at. Null when there's no error to point at (valid
    # progress, still incomplete, ambiguous) — see practice_service.validate_step.
    error_step_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # progressing | uncertain | stuck | misconception | ambiguous | teacher_required
    student_state: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Counter-question — a "productive struggle" step BEFORE Gate G's hint,
    # only on a student's FIRST genuine mistake on a question (help_streak
    # transitioning 0->1). Asks the student to explain their own reasoning
    # rather than immediately handing them a hint — the NBER field-
    # experiment finding this implements: AI should intervene after a
    # mistake by first prompting reflection, not by immediately being more
    # helpful. Repeated mistakes on the same question skip straight to the
    # normal L1-L4 hint ladder — re-asking a question that didn't resolve
    # things once already reads as repetitive, not supportive.
    counter_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Transcribed from the student's spoken response to counter_question —
    # set once they've answered (or explicitly skipped, see below).
    student_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    # self_corrected | confirmed_misconception | unclear | skipped | null
    # (null = counter_question was asked but not yet answered)
    explanation_outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Gates G/H
    hint_level: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0 (silence) - 5 (teacher handoff)
    hint_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    hint_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    post_hint_outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)  # resolved | still_stuck | escalated_to_teacher

    latency_ms_breakdown: Mapped[dict | None] = mapped_column(_JsonType, nullable=True)

    # Generated on demand (not automatically — see practice_service.
    # generate_attempt_review) once a student/teacher asks to see the full
    # correction: {"conceptual_error": str, "perfect_answer": list[str],
    # "tip": str}. Deliberately separate from hint_text/Gates G/H — hints
    # are guard-railed to NEVER reveal the final answer while a student is
    # still actively working (see check_hint_leakage); this is the opposite
    # intent, a post-hoc "here's what you missed and what a full answer
    # looks like" review, so it must never be shown during in-progress
    # hinting, only alongside a finished attempt. Cached here once generated
    # so re-opening the same attempt's review doesn't re-call the LLM.
    review: Mapped[dict | None] = mapped_column(_JsonType, nullable=True)

    teacher_override: Mapped[dict | None] = mapped_column(_JsonType, nullable=True)
    teacher_feedback: Mapped[str | None] = mapped_column(String(20), nullable=True)  # approve | reject

    # processing | awaiting_review | complete | failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="processing")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
