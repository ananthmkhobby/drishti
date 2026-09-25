import uuid
from datetime import datetime
from sqlalchemy import Integer, Boolean, DateTime, func, Uuid, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

_JsonType = JSONB().with_variant(JSON(), "sqlite")


class PracticeAttemptSummary(Base):
    """
    A consolidated record of a BATCH of older PracticeAttempt rows that got
    pruned to keep the raw attempt history bounded (see
    practice_service.prune_old_attempts_with_summary — only the most recent
    _KEEP_RECENT_ATTEMPTS per question are kept as full rows/images; an
    unattended auto-capture station can easily generate hundreds of
    attempts for one question, most of them redundant or off-topic re-reads
    of the same page — see process_attempt's own "stop auto-capture once
    solved" fix for real measured evidence of that: 51% of one question's
    full attempt history turned out to be wasted "off_topic_content" reads).

    This is deliberately a SUMMARY, not an archive — the raw images and
    per-attempt detail are genuinely deleted (that's the point: bounding
    storage growth), but the fact that a student struggled, how much, and
    whether they ultimately got there, survives. One row per prune event —
    a question pruned multiple times over a session accumulates multiple
    summary rows, each covering the batch deleted at that point, so the
    full history (summaries + the current last-10 raw attempts) is never
    silently lost, just consolidated the moment it stops being "recent".
    """

    __tablename__ = "practice_attempt_summaries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    question_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("practice_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Nullable + SET NULL: the summary should outlive the station itself
    # being removed — it's a record of the STUDENT'S work on this
    # question, not really "about" the capture device.
    station_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("practice_stations.id", ondelete="SET NULL"), nullable=True, index=True
    )

    attempts_summarized: Mapped[int] = mapped_column(Integer, nullable=False)
    first_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Did any attempt IN THIS BATCH reach "solved"? (If a later batch — or
    # the still-live recent 10 — eventually solves it, that's a separate
    # summary/row; this one is honest about what actually happened in the
    # window it covers.)
    solved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Heuristic flag for "this batch suggests the student needs another
    # pass at this concept" — see prune_old_attempts_with_summary for the
    # exact rule (not solved, OR escalated to teacher_required, OR 2+
    # distinct misconceptions surfaced). A teacher scanning summaries can
    # use this to spot who needs a revisit without reading every row.
    revision_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # {misconception_code: count} over the batch — which known
    # misconceptions actually showed up and how often, not just IF one did.
    misconception_codes: Mapped[dict | None] = mapped_column(_JsonType, nullable=True)
    # {"1": count, "2": count, ...} — hint_level distribution over the
    # batch, a cheap proxy for how much help was actually needed.
    hint_levels_seen: Mapped[dict | None] = mapped_column(_JsonType, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
