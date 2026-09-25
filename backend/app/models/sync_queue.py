import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime, func, Uuid, ForeignKey
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

_JsonType = JSONB().with_variant(JSON(), "sqlite")


class SyncQueue(Base):
    """
    Server-side record of each entity a device has attempted to upload.

    One row per entity (session_meta or frame) per device.
    Mirrors the mobile SQLite sync_queue table, but lives on the server
    so the dashboard can show per-device sync health and operations staff
    can investigate stuck uploads.

    device_id is nullable: populated once the device is formally registered
    via POST /devices. MVP: identified by teacher_id + device_fingerprint.
    """

    __tablename__ = "sync_queue"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Nullable until device is formally registered in the devices table
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Raw string from the request (e.g., Android fingerprint)
    device_fingerprint: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Denormalised for fast dashboard queries without joining to sessions
    teacher_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)

    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # session_meta | frame
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # The client-generated UUID from the mobile device
    local_entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Set once the server has accepted the upload
    remote_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)

    # pending | uploading | done | failed | skipped
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # JSON metadata payload from the device (session/frame metadata)
    payload: Mapped[dict | None] = mapped_column(_JsonType, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
