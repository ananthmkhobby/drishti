import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, func, Uuid, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class MissingConcept(Base):
    """
    A prerequisite gap or incomplete topic detected by AI during session analysis.

    Separate table (not embedded JSONB in ai_outputs) so operations staff can track
    which concepts have been revisited/resolved across sessions.  See ADR-011.
    """

    __tablename__ = "missing_concepts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ai_output_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_outputs.id", ondelete="SET NULL"), nullable=True
    )

    concept: Mapped[str] = mapped_column(String(500), nullable=False)
    # prerequisite_gap | incomplete_topic | skipped
    concept_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_remediation: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Marked True when a later session covers this concept
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_in_session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
