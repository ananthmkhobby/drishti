import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import String, Integer, DateTime, Text, func, Uuid, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class Textbook(Base):
    """
    A full textbook PDF attached to a session — distinct from LessonPlan
    (a single lesson's plan, one per session, short) in scale and purpose:
    this is the source material a "teach me this chapter" AI-tutor flow
    reads from, so it keeps raw text PER PAGE (not flattened into one
    string) — chapter detection and "which page did we stop on" both need
    page-level granularity that a flat join would lose.
    """
    __tablename__ = "textbooks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    title: Mapped[str | None] = mapped_column(String(300), nullable=True)  # e.g. "Grade 6 Science" — inferred or teacher-set
    file_path: Mapped[str] = mapped_column(String(500))
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # list[str], one entry per PDF page (index 0 = page 1) — extraction
    # keeps this shape deliberately; see the module docstring above.
    raw_pages: Mapped[Any | None] = mapped_column(JSON, nullable=True)

    # pending (uploaded, not yet processed) | processing (chapter detection
    # running) | ready | failed — chapter detection is an LLM call over the
    # whole book and runs as a background task, same pattern as practice
    # question generation.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Detected alongside chapters (same LLM call) so teaching can be
    # written/narrated in the book's own language instead of defaulting to
    # English. language_code is one of the app's supported UI locales
    # (en/hi/kn/te/mr/ta) when the detected language matches one, else null
    # (language_name is still set either way, e.g. "Bengali") — code drives
    # SpeechRecognition's `lang` and the localized "continue" voice command,
    # name drives what the teaching-segment prompt is told to write in.
    language_code: Mapped[str | None] = mapped_column(String(5), nullable=True)
    language_name: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # "textbook" (default — a formal multi-chapter book; chapter detection
    # and teaching pedagogy behave EXACTLY as before this field existed) or
    # "concept_notes" (a short single-topic worksheet/activity sheet, e.g.
    # a hands-on lab sheet). concept_notes skips chapter-boundary detection
    # (there's only one topic) and teaches with "quest" pedagogy instead of
    # "standard" — see TextbookChapter.pedagogy and textbook_service.py.
    content_type: Mapped[str] = mapped_column(String(20), nullable=False, default="textbook")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TextbookFigure(Base):
    """
    One diagram/illustration cropped out of the textbook PDF itself —
    deliberately the ONLY source of photographic/illustrated imagery this
    feature ever shows a student. Every candidate image extracted from a
    page is discarded unless a vision-classification pass (see
    textbook_service.classify_and_caption_figure) confirms it is a genuine
    educational diagram, not decorative art, a watermark, an icon, or
    anything with a safety concern — rows here are the ones that passed,
    so the mere existence of a row is itself the guardrail record.
    """
    __tablename__ = "textbook_figures"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    textbook_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("textbooks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-based, matches start_page/end_page
    image_path: Mapped[str] = mapped_column(String(500))
    caption: Mapped[str] = mapped_column(Text)  # from the vision classifier — used both to display and to let the teaching-segment LLM pick a relevant figure

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TextbookChapter(Base):
    """
    One detected chapter within a Textbook, and the running "how far has
    this been taught" bookmark for it.

    segments/current_segment_index/taught_log exist now (Phase 1) even
    though cross-day resume + "revise yesterday's class" (Phase 2) isn't
    built yet, so that Phase 2 is additive later rather than needing a
    schema change: segments caches each generated teaching segment (so
    re-visiting a chapter doesn't re-call the LLM for content already
    taught), current_segment_index is the bookmark "teach me the next
    part" reads and advances, and taught_log is a short per-segment note
    (not the full segment text) cheap enough to feed into a future recap
    prompt without re-summarizing everything from scratch.
    """
    __tablename__ = "textbook_chapters"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    textbook_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("textbooks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)  # position within the textbook, 0-based
    title: Mapped[str] = mapped_column(String(300), nullable=False)  # e.g. "Light"
    start_page: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-based index into Textbook.raw_pages
    end_page: Mapped[int] = mapped_column(Integer, nullable=False)  # inclusive

    # "standard" (default — the original explain-it-progressively style,
    # untouched by this field's addition) or "quest" (guess -> investigate
    # -> observe -> infer, for content_type="concept_notes" chapters). Set
    # once at chapter-creation time from the parent Textbook.content_type;
    # see textbook_service.generate_next_segment for the dispatch.
    pedagogy: Mapped[str] = mapped_column(String(20), nullable=False, default="standard")

    current_segment_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # list[{"text": str, "narration_text": str}] — cached once generated;
    # narration_text can differ slightly from the displayed text (e.g. a
    # spoken-out-loud rephrasing of a symbol/formula the display shows as
    # notation), though Phase 1 keeps them identical.
    segments: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    # list[str] — one short note per taught segment, e.g. "Explained what
    # light is and that it travels in straight lines." Feeds a future
    # "revise in bullet points" recap without re-reading full segment text.
    taught_log: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    last_taught_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
