import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime, func, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class Misconception(Base):
    """
    A curated, versioned library entry for a recurring student misconception
    — the controlled vocabulary the grader picks from instead of inventing a
    new free-form code per question (previously every question's
    known_misconceptions was LLM-authored at creation time, so the same real
    misconception got a different label each time and nothing could be
    aggregated or checked).

    source_type: "research" = traces to a published study/instrument named in
    source_citation; "convention" = a widely recognised classroom-error
    pattern without a single canonical citation. review_status starts
    "unreviewed" for everything seeded from the literature and only becomes
    "teacher_confirmed" when a teacher signs off — nothing here is claimed as
    verified for a given curriculum until then.
    """

    __tablename__ = "misconceptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    subject_key: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    grade_min: Mapped[int] = mapped_column(Integer, nullable=False)
    grade_max: Mapped[int] = mapped_column(Integer, nullable=False)
    topic: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    typical_work: Mapped[str] = mapped_column(Text, nullable=False)
    source_citation: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(12), nullable=False, default="research")
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unreviewed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
