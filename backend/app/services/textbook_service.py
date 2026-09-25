"""
Textbook upload processing (chapter detection) and live teaching-segment
generation — the "teach me this chapter like a teacher" flow.

Mirrors the extraction pattern used for lesson plans (app/routers/lesson_plans.py
:_extract_text) but keeps text PER PAGE instead of joining it into one string,
since chapter detection and mid-chapter resume both need real page numbers.
"""
import io
import logging
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.session import Session
from app.models.textbook import Textbook, TextbookChapter, TextbookFigure

logger = logging.getLogger(__name__)

# Roughly how much chapter source text to send per teaching-segment call.
# A single chapter's raw pages rarely exceed this; textbooks with unusually
# long chapters get their tail truncated rather than failing the call.
_MAX_CHAPTER_CHARS = 24000


def extract_pages(data: bytes) -> list[str]:
    """Extract text page-by-page from a PDF. Empty list on failure."""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return [page.extract_text() or "" for page in pdf.pages]
    except Exception as exc:
        logger.warning("Textbook PDF extraction failed: %s", exc)
        return []


# Below this many non-whitespace characters, treat a page's pdfplumber
# extraction as failed rather than "genuinely short" — confirmed live: a
# design-tool-exported (Canva/Figma-style) worksheet PDF can have its text
# rendered entirely as vector outlines with NO text layer, which pdfplumber
# returns as "" for every page with no error at all. Left unhandled, the
# teaching-segment generator would silently hallucinate content it never
# actually read instead of failing loudly — a worse outcome than an error.
_MIN_PAGE_TEXT_CHARS = 20
_OCR_RENDER_RESOLUTION = 150
_OCR_FENCE_RE = re.compile(r"^```\w*\s*|\s*```$", re.MULTILINE)


async def _ocr_fallback_pages(
    pdf_bytes: bytes, pages: list[str], api_key: str, model: str, timeout_sec: int,
) -> list[str]:
    """
    Returns a corrected copy of `pages`: any page whose pdfplumber text
    came back effectively empty is re-read via vision OCR instead. Pages
    that already extracted fine are returned unchanged (and cost nothing
    extra) — this only ever kicks in for the specific pages that failed.
    """
    needs_ocr = [i for i, text in enumerate(pages) if len(text.strip()) < _MIN_PAGE_TEXT_CHARS]
    if not needs_ocr:
        return pages

    from app.ai import build_page_ocr_prompt, call_openai_vision
    import pdfplumber

    corrected = list(pages)
    prompt = build_page_ocr_prompt()
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_idx in needs_ocr:
                if page_idx >= len(pdf.pages):
                    continue
                try:
                    rendered = pdf.pages[page_idx].to_image(resolution=_OCR_RENDER_RESOLUTION)
                    buf = io.BytesIO()
                    rendered.original.convert("RGB").save(buf, format="JPEG", quality=90)
                    raw_response, _ = await call_openai_vision(
                        api_key=api_key,
                        model=model,
                        system=prompt.system,
                        user_text=prompt.user,
                        image_data=buf.getvalue(),
                        image_media_type="image/jpeg",
                        max_tokens=2000,
                        timeout_sec=timeout_sec,
                        detail="high",
                    )
                    corrected[page_idx] = _OCR_FENCE_RE.sub("", raw_response).strip()
                except Exception as exc:
                    logger.warning("Page OCR fallback failed for page %d: %s", page_idx + 1, exc)
    except Exception as exc:
        logger.warning("Could not open PDF for OCR fallback: %s", exc)
    return corrected


async def _ensure_readable_pages(textbook: Textbook, pages: list[str], settings, db: AsyncSession) -> list[str]:
    """
    Runs _ocr_fallback_pages only for the pages that need it, and persists
    the correction onto textbook.raw_pages so every later read (teaching
    segments, not just this analysis call) benefits from it too. Returns
    the (possibly corrected) pages list. No-ops cheaply when every page
    already extracted real text.
    """
    if all(len(p.strip()) >= _MIN_PAGE_TEXT_CHARS for p in pages):
        return pages

    from app.services import storage_service

    try:
        pdf_bytes = await storage_service.load_frame_bytes(textbook.file_path)
    except (FileNotFoundError, OSError) as exc:
        logger.warning("Could not reload textbook PDF for OCR fallback %s: %s", textbook.id, exc)
        return pages

    corrected = await _ocr_fallback_pages(
        pdf_bytes, pages, settings.openai_api_key, settings.openai_model_default, settings.ai_request_timeout_sec,
    )
    if corrected != pages:
        textbook.raw_pages = corrected
        await db.commit()
    return corrected


async def _apply_subject_if_unset(session_id: uuid.UUID, subject: str | None, db: AsyncSession) -> None:
    """
    Fills in Session.subject from a textbook/concept-notes analysis, but
    only when the teacher hasn't already set one — a manual entry always
    wins over an inferred one.
    """
    if not subject:
        return
    session = await db.get(Session, session_id)
    if session and not session.subject:
        session.subject = subject


async def detect_chapters(textbook_id: uuid.UUID, db: AsyncSession) -> None:
    """
    Background task: run chapter detection over an already-uploaded
    textbook's raw_pages and persist the detected TextbookChapter rows.
    Sets textbook.status to "ready" or "failed".

    For content_type == "concept_notes" (a short single-topic worksheet
    rather than a formal textbook), delegates to _analyze_concept_notes
    instead — no chapter-boundary detection needed, and the resulting
    single chapter is taught with "quest" pedagogy. The "textbook" path
    below this check is untouched from before content_type existed.
    """
    textbook = await db.get(Textbook, textbook_id)
    if not textbook:
        return

    if textbook.content_type == "concept_notes":
        await _analyze_concept_notes(textbook, db)
        return

    from app.ai import build_chapter_detection_prompt, parse_textbook_analysis, call_openai

    settings = get_settings()
    pages = textbook.raw_pages or []
    if not pages or not settings.openai_api_key:
        textbook.status = "failed"
        textbook.error_message = (
            "No extractable text found in this PDF." if not pages
            else "AI features are not configured (missing OpenAI API key)."
        )
        await db.commit()
        return

    try:
        pages = await _ensure_readable_pages(textbook, pages, settings, db)
        paginated = "\n\n".join(f"[PAGE {i + 1}]\n{text}" for i, text in enumerate(pages))
        prompt = build_chapter_detection_prompt(paginated, title_hint=textbook.title)
        raw_response, _ = await call_openai(
            api_key=settings.openai_api_key,
            model=settings.openai_model_default,
            system=prompt.system,
            user=prompt.user,
            max_tokens=4000,
            timeout_sec=settings.ai_request_timeout_sec,
        )
        analysis = parse_textbook_analysis(raw_response)
        chapters = analysis["chapters"]
        if not chapters:
            textbook.status = "failed"
            textbook.error_message = "Could not detect any chapters in this textbook."
            await db.commit()
            return

        textbook.language_code = analysis["language_code"]
        textbook.language_name = analysis["language_name"]
        await _apply_subject_if_unset(textbook.session_id, analysis["subject"], db)

        page_count = len(pages)
        for idx, ch in enumerate(chapters):
            start = max(1, min(ch["start_page"], page_count))
            end = max(start, min(ch["end_page"], page_count))
            db.add(TextbookChapter(
                id=uuid.uuid4(),
                textbook_id=textbook.id,
                order_index=idx,
                title=ch["title"],
                start_page=start,
                end_page=end,
            ))
        textbook.status = "ready"
        textbook.error_message = None
        await db.commit()
    except Exception as exc:
        logger.exception("Chapter detection failed for textbook %s", textbook_id)
        textbook.status = "failed"
        textbook.error_message = str(exc)[:500]
        await db.commit()


async def _analyze_concept_notes(textbook: Textbook, db: AsyncSession) -> None:
    """
    The content_type == "concept_notes" counterpart to the chapter-boundary
    detection above — a short single-topic document always becomes exactly
    one TextbookChapter (the whole document), taught with "quest" pedagogy.
    """
    from app.ai import build_concept_notes_analysis_prompt, parse_concept_notes_analysis, call_openai

    settings = get_settings()
    pages = textbook.raw_pages or []
    if not pages or not settings.openai_api_key:
        textbook.status = "failed"
        textbook.error_message = (
            "No extractable text found in this PDF." if not pages
            else "AI features are not configured (missing OpenAI API key)."
        )
        await db.commit()
        return

    try:
        pages = await _ensure_readable_pages(textbook, pages, settings, db)
        paginated = "\n\n".join(f"[PAGE {i + 1}]\n{text}" for i, text in enumerate(pages))
        prompt = build_concept_notes_analysis_prompt(paginated, title_hint=textbook.title)
        raw_response, _ = await call_openai(
            api_key=settings.openai_api_key,
            model=settings.openai_model_default,
            system=prompt.system,
            user=prompt.user,
            max_tokens=500,
            timeout_sec=settings.ai_request_timeout_sec,
        )
        analysis = parse_concept_notes_analysis(raw_response)

        textbook.language_code = analysis["language_code"]
        textbook.language_name = analysis["language_name"]
        await _apply_subject_if_unset(textbook.session_id, analysis["subject"], db)

        db.add(TextbookChapter(
            id=uuid.uuid4(),
            textbook_id=textbook.id,
            order_index=0,
            title=analysis["topic_title"],
            start_page=1,
            end_page=len(pages),
            pedagogy="quest",
        ))
        textbook.status = "ready"
        textbook.error_message = None
        await db.commit()
    except Exception as exc:
        logger.exception("Concept notes analysis failed for textbook %s", textbook.id)
        textbook.status = "failed"
        textbook.error_message = str(exc)[:500]
        await db.commit()


# ---------------------------------------------------------------------------
# Figures — extraction from the PDF + content-safety classification
#
# This is the ONLY source of imagery a student ever sees (per product
# decision: PDF-extracted diagrams + deterministic generated diagrams, no
# stock photo search, no AI image generation, no video). Every candidate
# crop passes through classify_and_caption_figure before it can ever reach
# TextbookFigure — a row existing in that table IS the safety record.
# ---------------------------------------------------------------------------

# Skip crops smaller than this in either dimension — icons, QR codes, tiny
# decorative marks are never useful teaching diagrams and aren't worth a
# vision call to rule out.
_MIN_FIGURE_PX = 90
# Skip crops covering almost the whole page — these are page backgrounds/
# watermarks, not content figures (confirmed live: NCERT sample PDFs embed
# a full-page watermark image on every single page).
_MAX_FIGURE_PAGE_FRACTION = 0.92
_RENDER_RESOLUTION = 150
# Hard ceiling on vision-classification calls per textbook upload — bounds
# cost/latency on a large PDF regardless of how many embedded images it has.
_MAX_FIGURE_CANDIDATES = 25


def _extract_candidate_figures(pdf_bytes: bytes) -> list[tuple[int, bytes]]:
    """
    Returns [(page_number 1-based, jpeg_bytes), ...] for crops worth
    sending to the vision classifier. Page-template images (identical
    bounding box repeated across most pages — watermarks, background art)
    are filtered out first since they're never page-specific content.
    """
    import pdfplumber
    from collections import Counter

    candidates: list[tuple[int, bytes]] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            sig_counts: Counter = Counter()
            for page in pdf.pages:
                for img in page.images:
                    sig = (round(img["x0"]), round(img["top"]), round(img["x1"]), round(img["bottom"]))
                    sig_counts[sig] += 1
            repeated_threshold = max(3, len(pdf.pages) // 4)
            template_sigs = {sig for sig, count in sig_counts.items() if count >= repeated_threshold}

            scale = _RENDER_RESOLUTION / 72
            for page_idx, page in enumerate(pdf.pages):
                if len(candidates) >= _MAX_FIGURE_CANDIDATES:
                    break
                rendered = None
                for img in page.images:
                    if len(candidates) >= _MAX_FIGURE_CANDIDATES:
                        break
                    sig = (round(img["x0"]), round(img["top"]), round(img["x1"]), round(img["bottom"]))
                    if sig in template_sigs:
                        continue
                    w, h = img["x1"] - img["x0"], img["bottom"] - img["top"]
                    if w < _MIN_FIGURE_PX or h < _MIN_FIGURE_PX:
                        continue
                    if w > page.width * _MAX_FIGURE_PAGE_FRACTION or h > page.height * _MAX_FIGURE_PAGE_FRACTION:
                        continue
                    if rendered is None:
                        rendered = page.to_image(resolution=_RENDER_RESOLUTION)
                    box = (img["x0"] * scale, img["top"] * scale, img["x1"] * scale, img["bottom"] * scale)
                    try:
                        cropped = rendered.original.crop(box).convert("RGB")
                    except Exception:
                        continue
                    buf = io.BytesIO()
                    cropped.save(buf, format="JPEG", quality=88)
                    candidates.append((page_idx + 1, buf.getvalue()))
    except Exception as exc:
        logger.warning("Textbook figure candidate extraction failed: %s", exc)
    return candidates


async def _classify_and_caption_figure(image_bytes: bytes, api_key: str, model: str, timeout_sec: int) -> dict:
    """One vision call: approve/reject a candidate crop, with a caption if approved."""
    from app.ai import build_figure_classification_prompt, parse_figure_classification, call_openai_vision

    prompt = build_figure_classification_prompt()
    try:
        raw_response, _ = await call_openai_vision(
            api_key=api_key,
            model=model,
            system=prompt.system,
            user_text=prompt.user,
            image_data=image_bytes,
            image_media_type="image/jpeg",
            max_tokens=200,
            timeout_sec=timeout_sec,
        )
    except Exception as exc:
        logger.warning("Figure classification call failed: %s", exc)
        return {"approve": False, "caption": None, "reason": "classification call failed"}
    return parse_figure_classification(raw_response)


async def extract_figures(textbook_id: uuid.UUID, db: AsyncSession) -> None:
    """
    Background task: crop candidate diagrams out of the textbook PDF, run
    each through the content-safety classifier, and persist only the ones
    that pass as TextbookFigure rows. Runs after chapter detection — a
    textbook with no safe figures found is still perfectly usable (teaching
    just proceeds text+generated-diagram-only), so failures here never
    touch Textbook.status.
    """
    from app.services import storage_service

    textbook = await db.get(Textbook, textbook_id)
    if not textbook:
        return
    settings = get_settings()
    if not settings.openai_api_key:
        return

    try:
        pdf_bytes = await storage_service.load_frame_bytes(textbook.file_path)
    except (FileNotFoundError, OSError) as exc:
        logger.warning("Could not reload textbook PDF for figure extraction %s: %s", textbook_id, exc)
        return

    candidates = _extract_candidate_figures(pdf_bytes)
    for index, (page_number, image_bytes) in enumerate(candidates):
        result = await _classify_and_caption_figure(
            image_bytes, settings.openai_api_key, settings.openai_model_default, settings.ai_request_timeout_sec,
        )
        if not result["approve"]:
            continue
        try:
            image_path = await storage_service.save_textbook_figure(
                textbook.session_id, textbook.id, page_number, index, image_bytes,
            )
        except Exception as exc:
            logger.warning("Failed to save textbook figure for %s page %d: %s", textbook_id, page_number, exc)
            continue
        db.add(TextbookFigure(
            id=uuid.uuid4(),
            textbook_id=textbook.id,
            page_number=page_number,
            image_path=image_path,
            caption=result["caption"],
        ))
    await db.commit()


async def get_figures_for_chapter(textbook_id: uuid.UUID, chapter: TextbookChapter, db: AsyncSession) -> list[TextbookFigure]:
    result = await db.execute(
        select(TextbookFigure).where(
            TextbookFigure.textbook_id == textbook_id,
            TextbookFigure.page_number >= chapter.start_page,
            TextbookFigure.page_number <= chapter.end_page,
        )
    )
    return list(result.scalars().all())


_LOCATE_STOPWORDS = {
    "ok", "okay", "alright", "lets", "let", "start", "starting", "begin",
    "beginning", "grade", "class", "chapter", "chapters", "the", "and",
    "of", "a", "an", "to", "on", "in", "with", "from", "is", "are", "we",
    "please", "now", "today", "revise", "continue", "next", "teach", "me",
}


def _content_words(text: str) -> list[str]:
    import re
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _LOCATE_STOPWORDS and len(w) > 2]


def find_chapter_by_query(chapters: list[TextbookChapter], query: str) -> TextbookChapter | None:
    """
    Match a spoken phrase (e.g. "ok let's start grade 6 light chapter")
    against detected chapter titles. No LLM call — this runs synchronously
    inline with voice-intent handling.

    Scored by how much of the QUERY's own content is accounted for by a
    chapter's title (not the reverse) — a short spoken query like "light"
    only needs to hit ONE distinctive word in a longer title such as
    "Light, Shadows and Reflections" to identify it unambiguously, whereas
    scoring by fraction-of-title-words-matched would unfairly punish that
    same match for the title's other, unmentioned words.
    """
    import difflib

    if not chapters or not query:
        return None
    q_lower = query.strip().lower()

    # exact whole-phrase match wins outright
    for ch in chapters:
        if q_lower == ch.title.strip().lower():
            return ch

    q_words = _content_words(query)
    if not q_words:
        return None

    best: tuple[float, TextbookChapter | None] = (0.0, None)
    for ch in chapters:
        t_words = _content_words(ch.title)
        if not t_words:
            continue
        hits = sum(
            1 for qw in q_words
            if qw in t_words or any(difflib.SequenceMatcher(None, qw, tw).ratio() >= 0.82 for tw in t_words)
        )
        score = hits / len(q_words)
        if score > best[0]:
            best = (score, ch)
    return best[1] if best[0] >= 0.5 else None


def _chapter_source_text(textbook: Textbook, chapter: TextbookChapter) -> str:
    pages = textbook.raw_pages or []
    excerpt = pages[chapter.start_page - 1: chapter.end_page]
    text = "\n\n".join(excerpt)
    if len(text) > _MAX_CHAPTER_CHARS:
        text = text[:_MAX_CHAPTER_CHARS]
    return text


# A teaching segment (100-220 spoken words) covers roughly this many
# characters of dense source prose. Used only to bound runaway generation
# — confirmed live that the model, left unguided, keeps inventing
# plausible-but-not-in-the-book content indefinitely rather than stopping
# (see build_teaching_segment_prompt's docstring).
_CHARS_PER_SEGMENT = 300
_MIN_SEGMENT_BUDGET = 3
_MAX_SEGMENT_BUDGET = 20
_HARD_CAP_SLACK = 3  # extra segments allowed past the budget before forcing a stop


def _segment_budget(chapter_text: str) -> int:
    import math
    raw = math.ceil(max(len(chapter_text), 1) / _CHARS_PER_SEGMENT)
    return max(_MIN_SEGMENT_BUDGET, min(_MAX_SEGMENT_BUDGET, raw))


async def generate_next_segment(
    textbook: Textbook, chapter: TextbookChapter, db: AsyncSession,
) -> dict:
    """
    Returns the next teaching segment for `chapter`, advancing its
    bookmark. Segments already generated (current_segment_index <
    len(segments)) are never re-teaching — that path only exists if a
    future feature explicitly rewinds the bookmark; today the bookmark
    and the cache length always move together, so this call always
    generates fresh content.
    """
    from app.ai import (
        build_teaching_segment_prompt, build_quest_teaching_segment_prompt,
        parse_teaching_segment, call_openai,
    )
    from datetime import datetime, timezone

    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("AI features are not configured (missing OpenAI API key)")

    segments = list(chapter.segments or [])
    taught_log = list(chapter.taught_log or [])
    chapter_text = _chapter_source_text(textbook, chapter)
    budget = _segment_budget(chapter_text)

    figures = await get_figures_for_chapter(textbook.id, chapter, db)
    available_figures = [{"figure_id": str(f.id), "caption": f.caption} for f in figures]

    is_first_segment = chapter.current_segment_index == 0
    nearing_budget = len(segments) >= budget - 1
    if chapter.pedagogy == "quest":
        quest_phase_history = [s["quest_phase"] for s in segments if s.get("quest_phase")]
        prompt = build_quest_teaching_segment_prompt(
            chapter_title=chapter.title,
            chapter_text=chapter_text,
            taught_log=taught_log,
            quest_phase_history=quest_phase_history,
            is_first_segment=is_first_segment,
            nearing_budget=nearing_budget,
            available_figures=available_figures,
            language_name=textbook.language_name or "English",
        )
    else:
        prompt = build_teaching_segment_prompt(
            chapter_title=chapter.title,
            chapter_text=chapter_text,
            taught_log=taught_log,
            is_first_segment=is_first_segment,
            nearing_budget=nearing_budget,
            available_figures=available_figures,
            language_name=textbook.language_name or "English",
        )
    raw_response, _ = await call_openai(
        api_key=settings.openai_api_key,
        model=settings.openai_model_default,
        system=prompt.system,
        user=prompt.user,
        json_mode=True,
        max_tokens=800,
        timeout_sec=settings.ai_request_timeout_sec,
    )
    segment = parse_teaching_segment(raw_response)

    # Defensive: never trust a figure_id the model returned without
    # checking it's actually one we offered — a hallucinated id should
    # silently become "no figure," not a broken image reference.
    figures_by_id = {f["figure_id"]: f["caption"] for f in available_figures}
    figure_caption = figures_by_id.get(segment["figure_id"]) if segment["figure_id"] else None
    if segment["figure_id"] and figure_caption is None:
        segment["figure_id"] = None
    segment["figure_caption"] = figure_caption

    # Hard safety net: the prompt asks the model to wrap up near the
    # budget, but a prompt is a request, not a guarantee — force the stop
    # rather than let a chapter run away indefinitely.
    if len(segments) + 1 >= budget + _HARD_CAP_SLACK:
        segment["is_last_segment"] = True

    segments.append(segment)
    if segment["taught_summary"]:
        taught_log.append(segment["taught_summary"])

    chapter.segments = segments
    chapter.taught_log = taught_log
    chapter.current_segment_index = len(segments)
    chapter.last_taught_at = datetime.now(timezone.utc)

    if is_first_segment:
        session = await db.get(Session, textbook.session_id)
        if session and not session.title:
            session.title = chapter.title

    await db.commit()
    await db.refresh(chapter)

    return {
        "segment_index": chapter.current_segment_index - 1,
        "segment_text": segment["segment_text"],
        "is_last_segment": segment["is_last_segment"],
        "figure_id": segment["figure_id"],
        "figure_caption": segment["figure_caption"],
        "diagram_spec": segment["diagram_spec"],
        "quest_phase": segment["quest_phase"],
    }


class _SegmentTextStreamExtractor:
    """
    Incrementally extracts the (unescaped) value of the "segment_text" key
    out of a raw, still-arriving OpenAI json_mode stream, so the router can
    forward just the lesson prose to the browser as it's generated instead
    of the teacher watching a spinner for the whole ~5-10s call. Relies on
    "segment_text" being the FIRST key the model writes — true today for
    both build_teaching_segment_prompt and build_quest_teaching_segment_prompt,
    which list it first in the schema they hand the model, and json_mode
    reliably follows a schema's given key order.

    This is a best-effort PREVIEW only. The actual source of truth is
    always the complete buffer re-parsed by parse_teaching_segment() once
    the stream ends (see generate_next_segment_streaming) — if this
    extractor ever mis-tracks (an escape sequence split awkwardly across
    chunks, "segment_text" not actually first for some future prompt
    change), the very worst case is the live-typing preview lags or skips
    a few characters; the final committed segment is unaffected, since it
    never comes from this class.
    """

    def __init__(self) -> None:
        self.buffer = ""
        self._value_start: int | None = None
        self._emitted_len = 0
        self.finished = False

    def feed(self, chunk: str) -> str:
        """Returns newly-available UNESCAPED text to show, or "" if none yet."""
        import json as _json

        self.buffer += chunk
        if self.finished:
            return ""

        if self._value_start is None:
            key_idx = self.buffer.find('"segment_text"')
            if key_idx == -1:
                return ""
            colon_idx = self.buffer.find(":", key_idx)
            if colon_idx == -1:
                return ""
            quote_idx = self.buffer.find('"', colon_idx + 1)
            if quote_idx == -1:
                return ""
            self._value_start = quote_idx + 1

        # Scan for the terminating unescaped quote, treating a backslash as
        # always escaping the next character (so `\"` never ends the string).
        i = self._value_start
        n = len(self.buffer)
        end = None
        while i < n:
            c = self.buffer[i]
            if c == "\\":
                i += 2
                continue
            if c == '"':
                end = i
                break
            i += 1

        raw = self.buffer[self._value_start: end if end is not None else n]
        # A raw value ending mid-escape-sequence (an odd trailing run of
        # backslashes) would make json.loads fail on this partial string —
        # trim it and pick it back up once the next chunk completes it.
        stripped = raw.rstrip("\\")
        if (len(raw) - len(stripped)) % 2 == 1:
            raw = raw[:-1]

        try:
            unescaped = _json.loads(f'"{raw}"')
        except (ValueError, TypeError):
            return ""  # incomplete escape — try again once more data arrives

        new_text = unescaped[self._emitted_len:]
        self._emitted_len = len(unescaped)
        if end is not None:
            self.finished = True
        return new_text


async def generate_next_segment_streaming(textbook: Textbook, chapter: TextbookChapter, db: AsyncSession):
    """
    Streaming twin of generate_next_segment — same prompt selection, same
    figure handling, same DB commit and hard safety cap at the end, just
    delivered as an async generator of NDJSON lines instead of one blocking
    JSON response, so the router can start forwarding lesson text to the
    browser within roughly one round trip instead of the full generation
    time. Yields:
      - {"type": "delta", "text": "..."}   — a chunk of segment_text, as
        soon as the underlying extractor can confirm it (see
        _SegmentTextStreamExtractor)
      - {"type": "done", ...}              — exactly once, last: the full
        finalized segment response (same shape generate_next_segment
        returns), only after the DB commit has actually happened
      - {"type": "error", "message": "..."} — instead of "done", if
        anything failed; the router turns this into the same HTTP error
        generate_next_segment's callers already handle

    Deliberately does NOT reuse generate_next_segment's own code (some
    duplication below) — this stays a fully separate, independently
    readable path so the existing, already-relied-on non-streaming
    function is never at risk of a regression from this change.
    """
    from datetime import datetime, timezone
    from app.ai import (
        build_teaching_segment_prompt, build_quest_teaching_segment_prompt,
        parse_teaching_segment, call_openai_streaming,
    )

    settings = get_settings()
    if not settings.openai_api_key:
        yield {"type": "error", "message": "AI features are not configured (missing OpenAI API key)"}
        return

    segments = list(chapter.segments or [])
    taught_log = list(chapter.taught_log or [])
    chapter_text = _chapter_source_text(textbook, chapter)
    budget = _segment_budget(chapter_text)

    figures = await get_figures_for_chapter(textbook.id, chapter, db)
    available_figures = [{"figure_id": str(f.id), "caption": f.caption} for f in figures]

    is_first_segment = chapter.current_segment_index == 0
    nearing_budget = len(segments) >= budget - 1
    if chapter.pedagogy == "quest":
        quest_phase_history = [s["quest_phase"] for s in segments if s.get("quest_phase")]
        prompt = build_quest_teaching_segment_prompt(
            chapter_title=chapter.title,
            chapter_text=chapter_text,
            taught_log=taught_log,
            quest_phase_history=quest_phase_history,
            is_first_segment=is_first_segment,
            nearing_budget=nearing_budget,
            available_figures=available_figures,
            language_name=textbook.language_name or "English",
        )
    else:
        prompt = build_teaching_segment_prompt(
            chapter_title=chapter.title,
            chapter_text=chapter_text,
            taught_log=taught_log,
            is_first_segment=is_first_segment,
            nearing_budget=nearing_budget,
            available_figures=available_figures,
            language_name=textbook.language_name or "English",
        )

    extractor = _SegmentTextStreamExtractor()
    try:
        async for raw_chunk in call_openai_streaming(
            api_key=settings.openai_api_key,
            model=settings.openai_model_default,
            system=prompt.system,
            user=prompt.user,
            json_mode=True,
            max_tokens=800,
            timeout_sec=settings.ai_request_timeout_sec,
        ):
            delta = extractor.feed(raw_chunk)
            if delta:
                yield {"type": "delta", "text": delta}
    except Exception:
        logger.exception("Streaming teaching segment generation failed for chapter %s", chapter.id)
        yield {"type": "error", "message": "Could not generate the next segment"}
        return

    try:
        segment = parse_teaching_segment(extractor.buffer)
    except Exception:
        logger.exception("Failed to parse streamed teaching segment for chapter %s", chapter.id)
        yield {"type": "error", "message": "Could not generate the next segment"}
        return

    figures_by_id = {f["figure_id"]: f["caption"] for f in available_figures}
    figure_caption = figures_by_id.get(segment["figure_id"]) if segment["figure_id"] else None
    if segment["figure_id"] and figure_caption is None:
        segment["figure_id"] = None
    segment["figure_caption"] = figure_caption

    if len(segments) + 1 >= budget + _HARD_CAP_SLACK:
        segment["is_last_segment"] = True

    segments.append(segment)
    if segment["taught_summary"]:
        taught_log.append(segment["taught_summary"])

    chapter.segments = segments
    chapter.taught_log = taught_log
    chapter.current_segment_index = len(segments)
    chapter.last_taught_at = datetime.now(timezone.utc)

    if is_first_segment:
        session = await db.get(Session, textbook.session_id)
        if session and not session.title:
            session.title = chapter.title

    await db.commit()
    await db.refresh(chapter)

    yield {
        "type": "done",
        "segment_index": chapter.current_segment_index - 1,
        "segment_text": segment["segment_text"],
        "is_last_segment": segment["is_last_segment"],
        "figure_id": segment["figure_id"],
        "figure_caption": segment["figure_caption"],
        "diagram_spec": segment["diagram_spec"],
        "quest_phase": segment["quest_phase"],
    }


async def generate_check_understanding(textbook: Textbook, chapter: TextbookChapter) -> dict:
    """
    Teacher-triggered mid-lesson MCQ, grounded only in chapter.taught_log
    (what's actually been taught so far) — never touches segments/
    current_segment_index/taught_log, so it has no effect on the normal
    teaching bookmark and can be called at any point without disturbing it.
    Works identically for "standard" and "quest" pedagogy chapters.
    """
    from app.ai import build_check_understanding_prompt, parse_check_understanding, call_openai

    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("AI features are not configured (missing OpenAI API key)")

    taught_log = list(chapter.taught_log or [])
    if not taught_log:
        raise ValueError("Nothing has been taught yet in this chapter")

    prompt = build_check_understanding_prompt(
        chapter_title=chapter.title,
        taught_log=taught_log,
        language_name=textbook.language_name or "English",
    )
    raw_response, _ = await call_openai(
        api_key=settings.openai_api_key,
        model=settings.openai_model_default,
        system=prompt.system,
        user=prompt.user,
        json_mode=True,
        max_tokens=500,
        timeout_sec=settings.ai_request_timeout_sec,
    )
    return parse_check_understanding(raw_response)


async def generate_revision_recap(textbook: Textbook, chapter: TextbookChapter) -> dict:
    """
    Condensed "here's what we covered" bullet list, grounded only in
    chapter.taught_log — same non-destructive contract as
    generate_check_understanding (never touches segments/
    current_segment_index/taught_log). Meant to be shown once when a
    teacher resumes a chapter that already has progress, before moving on
    to new material — see the /revise route.
    """
    from app.ai import build_revision_recap_prompt, parse_revision_recap, call_openai

    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("AI features are not configured (missing OpenAI API key)")

    taught_log = list(chapter.taught_log or [])
    if not taught_log:
        raise ValueError("Nothing has been taught yet in this chapter")

    prompt = build_revision_recap_prompt(
        chapter_title=chapter.title,
        taught_log=taught_log,
        language_name=textbook.language_name or "English",
    )
    raw_response, _ = await call_openai(
        api_key=settings.openai_api_key,
        model=settings.openai_model_default,
        system=prompt.system,
        user=prompt.user,
        json_mode=True,
        max_tokens=400,
        timeout_sec=settings.ai_request_timeout_sec,
    )
    return parse_revision_recap(raw_response)
