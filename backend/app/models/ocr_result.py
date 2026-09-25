import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Float, DateTime, func, Uuid, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from app.models.base import Base

_JsonType = JSONB().with_variant(JSON(), "sqlite")


class OCRResult(Base):
    __tablename__ = "ocr_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    frame_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("frames.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured_json: Mapped[dict | None] = mapped_column(_JsonType, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    engine_used: Mapped[str | None] = mapped_column(String(50), nullable=True)
    processing_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
