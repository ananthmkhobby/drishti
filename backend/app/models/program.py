import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, func, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class Program(Base):
    """CSR / NGO / Government program that sponsors school deployments."""

    __tablename__ = "programs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # csr | ngo | government
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    org_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
