import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Text, func, Uuid, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class PracticeStation(Base):
    """
    One persistent capture channel for ONE student/desk/notebook, for the
    lifetime of a ThinkStep guided-practice session. A station is what makes
    multi-student capture practical: instead of a teacher manually tapping
    "capture" once per help request, a device is propped over one notebook
    and left running — it auto-captures on capture_interval_sec, and every
    resulting PracticeAttempt is tagged with this station_id, so the teacher
    dashboard can group a student's ongoing work into one "folder" rather
    than a flat, unattributed list of photos.

    Deliberately NOT tied to any student-identity/roster system (this app
    has none, and doesn't do face recognition — faces get blurred, not
    identified, everywhere else in the pipeline). The "identity" here is
    just "whichever device is propped over this notebook" — the teacher
    assigns the human-readable label, not the system.
    """

    __tablename__ = "practice_stations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)

    active_question_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("practice_questions.id", ondelete="SET NULL"), nullable=True
    )

    capture_interval_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    # idle (device not currently capturing) | capturing (auto-capture loop running)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="idle")
    last_capture_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # How this station's camera is physically positioned relative to the
    # notebook — "front" (default): a normal front/rear-facing camera
    # propped up facing the page, no correction needed. "desk": an
    # overhead/downward-facing camera mounted above the desk (e.g. fixed
    # just below or above a laptop, looking straight down at the notebook)
    # — this orientation reliably comes out rotated 90° and mirrored
    # left-right relative to how the page actually reads, since the camera
    # sensor's own "up" doesn't match the page's "up" when looking straight
    # down at it. Applied server-side (see practice_engine.apply_mount_correction)
    # right before any vision call — both the graded-attempt pipeline and
    # the AI Tutor — rather than something the student has to work around
    # by physically repositioning a fixed-mount camera every time (reported
    # 2026-09-24).
    camera_mount: Mapped[str] = mapped_column(String(20), nullable=False, default="front")

    # Teacher's free-text instruction to this specific student, surfaced on
    # their station view alongside/instead of the automated hint — this is
    # the "click a folder and give instructions" escape hatch for whenever
    # the automated gates aren't enough.
    teacher_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
