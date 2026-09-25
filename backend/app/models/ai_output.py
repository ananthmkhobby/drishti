import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, func, Uuid, ForeignKey, UniqueConstraint
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

_JsonType = JSONB().with_variant(JSON(), "sqlite")


class AIOutput(Base):
    __tablename__ = "ai_outputs"
    __table_args__ = (
        UniqueConstraint("session_id", "output_type", name="uq_output_session_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # notes | summary | bloom | missing_concepts | experiments | visual_cards
    output_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content_json: Mapped[dict | None] = mapped_column(_JsonType, nullable=True)
    content_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # pending | processing | ready | failed
    status: Mapped[str] = mapped_column(String(30), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
