import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, func, Uuid, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class Teacher(Base):
    """
    Users / teachers — the primary human actor in the system.

    Roles:
      teacher     — captures sessions, views own AI outputs
      admin       — school-level admin, views all sessions in their school
      superadmin  — Xperimentor staff, full access

    password_hash stores a bcrypt hash. Auth endpoints live in Phase 2.
    """

    __tablename__ = "teachers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("schools.id", ondelete="SET NULL"), nullable=True, index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # Optional — WhatsApp/SMS auth for rural teachers without email access
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, unique=True)

    # Stored as bcrypt hash via passlib. Null until teacher sets password.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # teacher | admin | superadmin
    role: Mapped[str] = mapped_column(String(50), default="teacher")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # True once email/phone is verified
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
