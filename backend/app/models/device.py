import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, func, Uuid, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class Device(Base):
    """
    Registered Android/iOS/web client for a teacher.

    device_fingerprint is a stable client-generated ID (e.g., Android ANDROID_ID
    or a UUID stored in SharedPreferences on first launch).

    push_token is the FCM token for push notifications — used in Phase 2.
    """

    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_fingerprint: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # android | ios | web
    platform: Mapped[str] = mapped_column(String(30), nullable=False)
    os_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # FCM token for Phase 2 push notifications
    push_token: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
