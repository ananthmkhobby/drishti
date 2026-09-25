"""
AI generation service.

Entry point: run_generation()
  - When OPENAI_API_KEY is set: calls GPT-4o / GPT-4o-mini per output type
  - When OPENAI_API_KEY is empty: falls back to placeholder outputs
    (safe for tests and local dev without an API key)

Generation sequence per the skill spec:
  notes → summary → quiz → bloom (depends on quiz) → missing_concepts
  → experiments → visual_cards (depends on notes) → homework → analogies

Each step is independently retried once with a stricter prompt on parse
failure.  A failure on one step does NOT block the others.

Post-generation:
  - Persist QuizQuestion rows (quiz)
  - Persist MissingConcept rows (missing_concepts)
  - Persist ExperimentSuggestion rows (experiments)
  - Update ClassroomMemory
  - Set session.status = "ai_complete"
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_output import AIOutput
from app.models.classroom_memory import ClassroomMemory
from app.models.experiment_suggestion import ExperimentSuggestion
from app.models.job import Job
from app.models.lesson_plan import LessonPlan
from app.models.missing_concept import MissingConcept
from app.models.quiz_question import QuizQuestion
from app.models.session import Session
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output-type routing table
# ---------------------------------------------------------------------------

# model key → "default" = gpt-4o, "mini" = gpt-4o-mini
_MODEL_ROUTING: dict[str, str] = {
    "notes": "default",
    "summary": "mini",
    "quiz": "default",
    "bloom": "default",
    "missing_concepts": "default",
    "experiments": "mini",
    "visual_cards": "mini",
    "homework": "mini",
    "analogies": "mini",
    "lesson_plan_coverage": "default",
    "combined_analysis": "default",
    "session_report": "default",
    "absorption_map": "mini",
}

# max_tokens per output type
# notes: 2800 for rich JSON (markdown + mind map + curriculum analysis)
# missing_concepts: 2000 for deep pedagogical gap analysis (8 steps)
_MAX_TOKENS: dict[str, int] = {
    "notes": 2800,
    "summary": 300,
    "quiz": 1200,
    "bloom": 400,
    "missing_concepts": 2000,
    "experiments": 800,
    "visual_cards": 600,
    "homework": 500,
    "analogies": 500,
    "lesson_plan_coverage": 1200,
    "combined_analysis": 1800,
    "session_report": 600,
    "absorption_map": 1000,
}

# ---------------------------------------------------------------------------
# Placeholder constants (kept for fallback / tests)
# ---------------------------------------------------------------------------

_PLACEHOLDER_OUTPUTS: dict[str, dict] = {
    "notes": {
        "markdown": (
            "# Placeholder Notes\n\n"
            "## Topic\nBoard content will appear here after OCR + AI processing.\n\n"
            "## Key Concepts\n- Concept 1\n- Concept 2\n\n"
            "## Formulas\n- Formula = Placeholder\n"
        ),
        "metadata": {"placeholder": True},
    },
    "summary": {
        "text": (
            "This is a placeholder class summary. After real OCR and AI processing, "
            "this will contain a 3–5 sentence recap of what was taught on the board today."
        ),
        "metadata": {"placeholder": True},
    },
    "bloom": {
        "counts": {
            "remember": 3, "understand": 2, "apply": 1,
            "analyze": 0, "evaluate": 0, "create": 0,
        },
        "lower_order_dominant": True,
        "suggestions": [
            "Placeholder higher-order question 1",
            "Placeholder higher-order question 2",
        ],
        "metadata": {"placeholder": True},
    },
    "missing_concepts": {
        "prerequisite_gaps": ["Placeholder prerequisite concept"],
        "incomplete_topics": ["Placeholder incomplete topic"],
        "suggested_next": "Next topic will be suggested here after AI analysis.",
        "metadata": {"placeholder": True},
    },
    "experiments": {
        "suggestions": [
            {
                "title": "Placeholder Experiment",
                "description": "Experiment suggestions will appear here after AI analysis.",
                "materials": ["Material 1", "Material 2"],
                "steps": ["Step 1", "Step 2"],
                "xperimentor_kit": None,
            }
        ],
        "metadata": {"placeholder": True},
    },
    "visual_cards": {
        "cards": [{"title": "Placeholder Card", "content": "Key concept summary here."}],
        "metadata": {"placeholder": True},
    },
    "homework": {
        "tasks": [
            {
                "task": "Review today's notes and write down 3 things you learned.",
                "type": "practice",
                "bloom_level": "remember",
                "estimated_minutes": 15,
                "topic": "General",
            }
        ],
        "metadata": {"placeholder": True},
    },
    "analogies": {
        "analogies": [
            {
                "concept": "Placeholder Concept",
                "analogy": "Like a cricket ball being bowled — placeholder analogy.",
                "explanation": "Explanation will appear here after AI analysis.",
            }
        ],
        "metadata": {"placeholder": True},
    },
    "session_report": {
        "headline": "Placeholder — AI not configured",
        "what_was_covered": "Board content and audio transcript will be summarised here once AI is enabled.",
        "how_it_went": "Pacing and engagement observations will appear here.",
        "highlights": ["Highlight 1", "Highlight 2"],
        "gaps": ["Gap 1"],
        "next_class": "Next steps will appear here after real AI processing.",
        "sources": {"board_frames": 0, "audio": False},
        "metadata": {"placeholder": True},
    },
    "absorption_map": {
        "revision_sections": [
            {
                "level": "high",
                "heading": "Well absorbed — quick review",
                "items": [{"topic": "Placeholder Topic", "summary": "Revision notes will appear after AI analysis."}],
            }
        ],
        "insight": "Absorption map will be generated once session data is available.",
        "replan_suggestion": "Re-run generation after capturing board frames and audience metrics.",
        "metadata": {"placeholder": True},
    },
}

_PLACEHOLDER_QUIZ = [
    {
        "type": "mcq",
        "text": "Placeholder MCQ — What is the main concept taught today?",
        "options": ["Option A", "Option B", "Option C", "Option D"],
        "correct": 0,
        "bloom_level": "remember",
        "topic": "Placeholder Topic",
        "skill_tag": "recall",
    },
    {
        "type": "mcq",
        "text": "Placeholder MCQ — Which formula applies here?",
        "options": ["F = ma", "E = mc²", "V = IR", "P = IV"],
        "correct": 0,
        "bloom_level": "understand",
        "topic": "Placeholder Topic",
        "skill_tag": "identification",
    },
    {
        "type": "true_false",
        "text": "Placeholder T/F — This is a placeholder question.",
        "correct": True,
        "bloom_level": "remember",
        "topic": "Placeholder Topic",
        "skill_tag": "recall",
    },
]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_generation(
    session_id: uuid.UUID,
    output_types: list[str],
    job_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """
    Main entry point.  Falls back to placeholder when OPENAI_API_KEY is empty.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        logger.info(
            "OPENAI_API_KEY not configured — using placeholder generation for session %s",
            session_id,
        )
        return await run_placeholder_generation(session_id, output_types, job_id, db)

    await _run_real_generation(session_id, output_types, job_id, db, settings)


# ---------------------------------------------------------------------------
# Real generation (OpenAI)
# ---------------------------------------------------------------------------

async def _run_real_generation(
    session_id: uuid.UUID,
    output_types: list[str],
    job_id: uuid.UUID,
    db: AsyncSession,
    settings,
) -> None:
    from app.ai import (
        build_notes_prompt, build_summary_prompt, build_quiz_prompt,
        build_bloom_prompt, build_missing_concepts_prompt,
        build_experiments_prompt, build_visual_cards_prompt,
        build_homework_prompt, build_analogies_prompt,
        build_lesson_plan_coverage_prompt, build_combined_analysis_prompt,
        build_session_report_prompt, build_absorption_map_prompt,
        parse_notes, parse_summary, parse_quiz, parse_bloom,
        parse_missing_concepts, parse_experiments, parse_visual_cards,
        parse_homework, parse_analogies,
        parse_lesson_plan_coverage, parse_combined_analysis,
        parse_session_report, parse_absorption_map,
        ParseError, RefusalError,
        call_openai, ContextTooLongError,
    )

    # ---- load session ----
    session = await db.get(Session, session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")

    # Capture attrs before any commit (SQLAlchemy expiry safety)
    subject = session.subject or "General"
    grade = session.grade or "Grade 8"
    board_type = session.board_type or "chalkboard"
    teacher_id = session.teacher_id

    # ---- load + prepare OCR text ----
    ocr_text = await _get_merged_ocr_text(session_id, db)

    # Strip leftover placeholder markers before measuring useful content.
    # These appear when OCR engines are unavailable or frames were invalid.
    import re as _re
    cleaned_ocr = _re.sub(
        r"\[OCR Placeholder[^\]]*\]\.?",
        "",
        ocr_text or "",
        flags=_re.IGNORECASE,
    ).strip()

    # Require at least 10 characters of real board text.
    # The hallucination filter in _get_merged_ocr_text already strips image
    # description sentences, so even small amounts (a few keywords) are usable.
    source = "board OCR"
    if not cleaned_ocr or len(cleaned_ocr) < 10:
        # No board capture / recording yet — fall back to whatever textbook
        # or concept-notes PDF was uploaded for this session before giving
        # up to placeholder generation. Same downstream prompts either way;
        # they just take a text blob, not specifically OCR'd board text.
        textbook_text = await _get_textbook_text(session_id, db)
        if textbook_text and len(textbook_text) >= 10:
            cleaned_ocr = textbook_text
            source = "uploaded textbook/concept-notes"
        else:
            logger.warning(
                "Session %s has insufficient real OCR text (%d usable chars) and no "
                "usable textbook/concept-notes upload — falling back to placeholder generation",
                session_id, len(cleaned_ocr),
            )
            return await run_placeholder_generation(session_id, output_types, job_id, db)

    logger.info(
        "Session %s: generating from %d chars of %s text",
        session_id, len(cleaned_ocr), source,
    )

    # Use the cleaned text so placeholder fragments don't pollute the prompt.
    ocr_text = cleaned_ocr

    truncated, was_truncated = _truncate_to_tokens(ocr_text, settings.ai_max_ocr_tokens)
    if was_truncated:
        logger.info("Session %s OCR text truncated to ~%d tokens", session_id, settings.ai_max_ocr_tokens)

    # ---- load classroom memory ----
    memory_topics = await _get_memory_topics(teacher_id, db)

    # ---- mark job as processing ----
    job = await db.get(Job, job_id)
    if job:
        job.status = "processing"
        job.progress = 5
    await db.commit()

    # ---- resolve models ----
    model_default = settings.openai_model_default
    model_mini = settings.openai_model_mini

    def model_for(otype: str) -> str:
        return model_default if _MODEL_ROUTING.get(otype, "mini") == "default" else model_mini

    # ---- load lesson plan topics (for lesson_plan_coverage output type) ----
    lesson_plan_topics: list[str] = []
    if "lesson_plan_coverage" in output_types:
        lp_row = await db.execute(
            select(LessonPlan).where(LessonPlan.session_id == session_id)
        )
        lp = lp_row.scalar_one_or_none()
        lesson_plan_topics = (lp.topics or []) if lp else []
        if not lesson_plan_topics:
            logger.warning(
                "lesson_plan_coverage requested for session %s but no lesson plan uploaded — skipping",
                session_id,
            )

    # ---- load audio transcript + engagement metrics (for combined_analysis / lesson_plan_coverage) ----
    audio_transcript: str = ""
    engagement_metrics: dict | None = None
    audio_sources_info: list[dict] = []  # metadata about each recording (source, duration, etc.)
    if "combined_analysis" in output_types or "lesson_plan_coverage" in output_types or "session_report" in output_types:
        from app.models.session_audio import SessionAudio
        from app.services.engagement_service import compute_engagement_metrics
        audio_rows = await db.execute(
            select(SessionAudio)
            .where(SessionAudio.session_id == session_id)
            .order_by(SessionAudio.recording_number)
        )
        audio_recordings = audio_rows.scalars().all()
        transcripts = [r.transcript for r in audio_recordings if r.transcript]
        if transcripts:
            # Join multiple recordings with a separator so the AI sees them as one stream
            audio_transcript = "\n\n---\n\n".join(transcripts)
        else:
            logger.warning(
                "combined_analysis requested for session %s but no audio transcript found — "
                "will proceed with empty transcript",
                session_id,
            )
        # Compute engagement metrics from Whisper segment timestamps (no ML needed)
        recordings_with_segments = [r for r in audio_recordings if r.segments]
        if recordings_with_segments:
            engagement_metrics = compute_engagement_metrics(recordings_with_segments)
        # Source metadata passed to the prompt so it can describe each source
        audio_sources_info = [
            {
                "source": r.source,
                "duration_sec": r.duration_sec,
                "transcribed": bool(r.transcript),
            }
            for r in audio_recordings
        ]

    # ---- load audience metrics (face analysis, Phase 2) ---------------------
    audience_data: dict | None = None
    if "combined_analysis" in output_types:
        from app.models.audience_metric import AudienceMetric
        from sqlalchemy import select as _select
        aud_rows = await db.execute(
            _select(AudienceMetric)
            .where(AudienceMetric.session_id == session_id)
            .order_by(AudienceMetric.minute_number)
        )
        aud_metrics = aud_rows.scalars().all()
        if aud_metrics:
            avg_attention = round(sum(r.attention_pct for r in aud_metrics) / len(aud_metrics), 1)
            audience_data = {
                "minute_count": len(aud_metrics),
                "avg_attention_pct": avg_attention,
                "metrics": [
                    {
                        "minute": r.minute_number,
                        "faces": r.faces_detected,
                        "attention_pct": round(r.attention_pct, 1),
                        "hand_raises": r.hand_raises,
                    }
                    for r in aud_metrics
                ],
            }

    # ---- load absorption map frame data (board content × attention, for absorption_map) ----
    absorption_frames_for_prompt: list[dict] = []
    absorption_avg_attention: float | None = None
    if "absorption_map" in output_types:
        from app.models.frame import Frame as _Frame
        from app.models.ocr_result import OCRResult as _OCRResult
        from app.models.audience_metric import AudienceMetric as _AudienceMetric
        from datetime import timezone as _tz

        _frame_rows = await db.execute(
            select(_Frame)
            .where(_Frame.session_id == session_id)
            .order_by(_Frame.sequence_no)
        )
        _abs_frames = _frame_rows.scalars().all()

        if _abs_frames:
            _ocr_rows = await db.execute(
                select(_OCRResult)
                .where(_OCRResult.frame_id.in_([f.id for f in _abs_frames]))
            )
            _ocr_map = {r.frame_id: r for r in _ocr_rows.scalars().all()}

            _aud_rows = await db.execute(
                select(_AudienceMetric)
                .where(_AudienceMetric.session_id == session_id)
            )
            _abs_aud = {m.minute_number: m for m in _aud_rows.scalars().all()}

            _timestamps = [f.captured_at for f in _abs_frames if f.captured_at]
            _sess_start = min(_timestamps) if _timestamps else None

            def _abs_level(a: float | None) -> str:
                if a is None:
                    return "unknown"
                return "high" if a >= 65 else ("medium" if a >= 35 else "low")

            for _f in _abs_frames:
                _minute = 0
                if _sess_start and _f.captured_at:
                    _fa = _f.captured_at
                    _ss = _sess_start
                    if _fa.tzinfo is None:
                        _fa = _fa.replace(tzinfo=_tz.utc)
                    if _ss.tzinfo is None:
                        _ss = _ss.replace(tzinfo=_tz.utc)
                    _minute = max(0, int((_fa - _ss).total_seconds() / 60))

                _metric = _abs_aud.get(_minute) or _abs_aud.get(_minute + 1)
                _att = round(_metric.attention_pct, 1) if _metric else None
                _ocr = _ocr_map.get(_f.id)
                _preview = (_ocr.raw_text[:300]) if _ocr and _ocr.raw_text else ""

                absorption_frames_for_prompt.append({
                    "sequence_no": _f.sequence_no,
                    "minute": _minute,
                    "ocr_preview": _preview,
                    "attention_pct": _att,
                    "absorption_level": _abs_level(_att),
                })

            _atts = [f["attention_pct"] for f in absorption_frames_for_prompt if f["attention_pct"] is not None]
            absorption_avg_attention = round(sum(_atts) / len(_atts), 1) if _atts else None

        if not absorption_frames_for_prompt:
            logger.warning(
                "absorption_map requested for session %s but no frames found", session_id
            )

    # ---- inter-step state ----
    quiz_questions: list[dict] | None = None
    notes_markdown: str | None = None

    # ---- result store ----
    results: dict[str, dict] = {}

    total = len(output_types)

    for step_idx, output_type in enumerate(output_types):
        logger.info("Generating %s for session %s", output_type, session_id)
        t0 = time.monotonic()
        status = "ready"
        tokens_used = 0

        try:
            # Bloom needs quiz; skip gracefully if quiz wasn't generated
            if output_type == "bloom" and quiz_questions is None:
                if "quiz" not in output_types:
                    # Generate quiz inline for bloom
                    quiz_questions, tokens_used = await _call_and_parse(
                        output_type="quiz",
                        first_prompt=build_quiz_prompt(
                            truncated, subject, grade, board_type,
                        ),
                        strict_prompt=build_quiz_prompt(
                            truncated, subject, grade, board_type, strict=True,
                        ),
                        parser=parse_quiz,
                        api_key=settings.openai_api_key,
                        model=model_for("quiz"),
                        max_tokens=_MAX_TOKENS["quiz"],
                        timeout=settings.ai_request_timeout_sec,
                        max_retries=settings.ai_max_retries,
                    )
                else:
                    logger.warning("Bloom requested but quiz not yet available — skipping bloom")
                    results[output_type] = {"error": "quiz not available", "_status": "skipped"}
                    continue

            # Skip absorption_map if no frames were found
            if output_type == "absorption_map" and not absorption_frames_for_prompt:
                results[output_type] = {"error": "no frames available", "_status": "skipped"}
                continue

            # Skip lesson_plan_coverage if no lesson plan was uploaded
            if output_type == "lesson_plan_coverage" and not lesson_plan_topics:
                results[output_type] = {"error": "no lesson plan uploaded", "_status": "skipped"}
                continue

            # combined_analysis / session_report run even without audio
            # visual_cards fallback: use OCR text if notes not generated
            source_for_visual = notes_markdown or truncated

            # frame count for session_report
            frame_count_val = session.frame_count or 0
            duration_val = 0
            if session.started_at and session.completed_at:
                duration_val = int((session.completed_at - session.started_at).total_seconds())

            prompt_map = {
                "notes": lambda: build_notes_prompt(truncated, subject, grade, board_type),
                "summary": lambda: build_summary_prompt(truncated, subject, grade, board_type),
                # Quiz: prefer the richer generated notes_markdown (if notes ran first),
                # fall back to raw OCR text.  This ensures quiz questions are grounded in
                # full, well-structured content even when OCR text was sparse.
                "quiz": lambda: build_quiz_prompt(
                    notes_markdown if notes_markdown else truncated,
                    subject, grade, board_type,
                ),
                "bloom": lambda: build_bloom_prompt(
                    json.dumps(quiz_questions), subject, grade, board_type
                ),
                "missing_concepts": lambda: build_missing_concepts_prompt(
                    _extract_topics(notes_markdown or truncated),
                    memory_topics, subject, grade, board_type,
                ),
                "experiments": lambda: build_experiments_prompt(
                    _extract_topics(notes_markdown or truncated),
                    subject, grade, board_type,
                ),
                "visual_cards": lambda: build_visual_cards_prompt(
                    source_for_visual, subject, grade, board_type,
                ),
                "homework": lambda: build_homework_prompt(truncated, subject, grade, board_type),
                "analogies": lambda: build_analogies_prompt(truncated, subject, grade, board_type),
                "lesson_plan_coverage": lambda: build_lesson_plan_coverage_prompt(
                    lesson_plan_topics, truncated, subject, grade, audio_transcript
                ),
                "combined_analysis": lambda: build_combined_analysis_prompt(
                    truncated, audio_transcript, lesson_plan_topics, subject, grade,
                    engagement_metrics=engagement_metrics,
                    audience_data=audience_data,
                    audio_sources=audio_sources_info,
                ),
                "session_report": lambda: build_session_report_prompt(
                    truncated, audio_transcript, subject, grade,
                    frame_count=frame_count_val,
                    duration_sec=duration_val,
                    engagement_metrics=engagement_metrics,
                ),
                "absorption_map": lambda: build_absorption_map_prompt(
                    absorption_frames_for_prompt, subject, grade,
                    avg_attention=absorption_avg_attention,
                ),
            }

            strict_prompt_map = {
                "quiz": lambda: build_quiz_prompt(
                    notes_markdown if notes_markdown else truncated,
                    subject, grade, board_type, strict=True,
                ),
                "missing_concepts": lambda: build_missing_concepts_prompt(
                    _extract_topics(notes_markdown or truncated),
                    memory_topics, subject, grade, board_type, strict=True,
                ),
                "experiments": lambda: build_experiments_prompt(
                    _extract_topics(notes_markdown or truncated),
                    subject, grade, board_type, strict=True,
                ),
                "visual_cards": lambda: build_visual_cards_prompt(
                    source_for_visual, subject, grade, board_type, strict=True,
                ),
                "homework": lambda: build_homework_prompt(
                    truncated, subject, grade, board_type, strict=True,
                ),
                "analogies": lambda: build_analogies_prompt(
                    truncated, subject, grade, board_type, strict=True,
                ),
                "lesson_plan_coverage": lambda: build_lesson_plan_coverage_prompt(
                    lesson_plan_topics, truncated, subject, grade, audio_transcript, strict=True
                ),
                "combined_analysis": lambda: build_combined_analysis_prompt(
                    truncated, audio_transcript, lesson_plan_topics, subject, grade,
                    engagement_metrics=engagement_metrics,
                    audience_data=audience_data,
                    audio_sources=audio_sources_info,
                    strict=True,
                ),
                "session_report": lambda: build_session_report_prompt(
                    truncated, audio_transcript, subject, grade,
                    frame_count=frame_count_val,
                    duration_sec=duration_val,
                    engagement_metrics=engagement_metrics,
                ),
                "absorption_map": lambda: build_absorption_map_prompt(
                    absorption_frames_for_prompt, subject, grade,
                    avg_attention=absorption_avg_attention,
                    strict=True,
                ),
            }

            parser_map = {
                "notes": parse_notes,
                "summary": parse_summary,
                "quiz": parse_quiz,
                "bloom": parse_bloom,
                "missing_concepts": parse_missing_concepts,
                "experiments": parse_experiments,
                "visual_cards": parse_visual_cards,
                "homework": parse_homework,
                "analogies": parse_analogies,
                "lesson_plan_coverage": parse_lesson_plan_coverage,
                "combined_analysis": parse_combined_analysis,
                "session_report": parse_session_report,
                "absorption_map": parse_absorption_map,
            }

            if output_type not in prompt_map:
                logger.warning("Unknown output type: %s — skipping", output_type)
                continue

            parsed, tokens_used = await _call_and_parse(
                output_type=output_type,
                first_prompt=prompt_map[output_type](),
                strict_prompt=strict_prompt_map.get(output_type, prompt_map[output_type])(),
                parser=parser_map[output_type],
                api_key=settings.openai_api_key,
                model=model_for(output_type),
                max_tokens=_MAX_TOKENS.get(output_type, 800),
                timeout=settings.ai_request_timeout_sec,
                max_retries=settings.ai_max_retries,
            )

            # Store cross-step state
            if output_type == "quiz":
                quiz_questions = parsed
            elif output_type == "notes":
                notes_markdown = parsed.get("markdown", "") if isinstance(parsed, dict) else ""
                if isinstance(parsed, dict):
                    parsed["board_diagrams"] = await _get_session_diagrams(session_id, db)

            # Wrap list outputs under a key for uniform storage
            if isinstance(parsed, list):
                content = {output_type: parsed, "_truncated": was_truncated, "_tokens_used": tokens_used}
            else:
                content = {**parsed, "_truncated": was_truncated, "_tokens_used": tokens_used}

            results[output_type] = content

        except RefusalError as exc:
            logger.warning("AI refusal for %s: %s", output_type, exc)
            results[output_type] = {"error": str(exc), "_status": "failed"}
            status = "failed"

        except ContextTooLongError as exc:
            # Already truncated — something is wrong with the model config
            logger.error("Context too long for %s even after truncation: %s", output_type, exc)
            results[output_type] = {"error": "context_too_long", "_status": "failed"}
            status = "failed"

        except ParseError as exc:
            # Second attempt failed — store partial
            logger.warning("Parse failed for %s after retry: %s", output_type, exc)
            results[output_type] = {"error": str(exc), "_status": "partial"}
            status = "partial"

        except Exception as exc:
            logger.exception("Unexpected error generating %s for session %s", output_type, session_id)
            results[output_type] = {"error": str(exc), "_status": "failed"}
            status = "failed"

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "step=%s session=%s status=%s elapsed_ms=%d",
            output_type, session_id, status, elapsed_ms,
        )

        # Stash generation metadata for _persist_outputs (popped there)
        if isinstance(results.get(output_type), dict):
            results[output_type]["_model"] = model_for(output_type)
            results[output_type]["_elapsed_ms"] = elapsed_ms

        # Update job progress (leave final 10% for DB writes)
        progress = max(5, int((step_idx + 1) / total * 85))
        # Re-fetch job to avoid stale
        job = await db.get(Job, job_id)
        if job:
            job.progress = progress
        await db.commit()

    # ---- persist all outputs ----
    await _persist_outputs(session_id, output_types, results, db)

    # ---- post-generation: classroom memory ----
    mc_data = results.get("missing_concepts", {})
    if "_status" not in mc_data and "prerequisite_gaps" in mc_data:
        await _update_classroom_memory(
            teacher_id, session_id, notes_markdown, mc_data, db,
        )

    # ---- session status ----
    session = await db.get(Session, session_id)
    if session:
        session.status = "ai_complete"

    # ---- mark job done ----
    job = await db.get(Job, job_id)
    if job:
        job.status = "completed"
        job.progress = 100
    await db.commit()
    logger.info("AI generation complete for session %s", session_id)


# ---------------------------------------------------------------------------
# Single output: call → parse → retry once with strict prompt
# ---------------------------------------------------------------------------

async def _call_and_parse(
    *,
    output_type: str,
    first_prompt,
    strict_prompt,
    parser,
    api_key: str,
    model: str,
    max_tokens: int,
    timeout: int,
    max_retries: int,
):
    from app.ai import call_openai, ParseError

    # First attempt
    raw, tokens = await call_openai(
        api_key=api_key,
        model=model,
        system=first_prompt.system,
        user=first_prompt.user,
        max_tokens=max_tokens,
        timeout_sec=timeout,
        max_retries=max_retries,
    )

    try:
        return parser(raw), tokens
    except ParseError as first_err:
        logger.warning(
            "Parse failed for %s (first attempt): %s — retrying with strict prompt",
            output_type, first_err,
        )

    # Second attempt with strict prompt
    raw2, tokens2 = await call_openai(
        api_key=api_key,
        model=model,
        system=strict_prompt.system,
        user=strict_prompt.user,
        max_tokens=max_tokens,
        timeout_sec=timeout,
        max_retries=1,  # one more shot only
    )
    return parser(raw2), tokens + tokens2  # raises ParseError on second failure → caller handles


# ---------------------------------------------------------------------------
# Persist outputs to DB
# ---------------------------------------------------------------------------

async def _persist_outputs(
    session_id: uuid.UUID,
    output_types: list[str],
    results: dict[str, dict],
    db: AsyncSession,
) -> None:
    for output_type in output_types:
        if output_type not in results:
            continue

        content = results[output_type]
        inner_status = content.pop("_status", "ready")
        tokens_used = content.pop("_tokens_used", 0)
        model_used = content.pop("_model", None)
        elapsed_ms = content.pop("_elapsed_ms", 0)
        status = inner_status if inner_status in ("failed", "partial", "skipped") else "ready"

        # Upsert AIOutput row
        existing = (
            await db.execute(
                select(AIOutput).where(
                    AIOutput.session_id == session_id,
                    AIOutput.output_type == output_type,
                )
            )
        ).scalar_one_or_none()

        if existing:
            existing.status = status
            existing.content_json = content
            existing.tokens_used = tokens_used
            existing.model_used = model_used
            existing.generation_ms = elapsed_ms
        else:
            row = AIOutput(
                id=uuid.uuid4(),
                session_id=session_id,
                output_type=output_type,
                status=status,
                content_json=content,
                tokens_used=tokens_used,
                model_used=model_used,
                generation_ms=elapsed_ms,
            )
            db.add(row)

        await db.flush()

        if status != "ready":
            continue

        # ---- per-type model rows ----
        ai_output_id = existing.id if existing else row.id  # type: ignore[possibly-undefined]

        if output_type == "quiz":
            questions = content.get("quiz") or []
            await _persist_quiz_questions(session_id, ai_output_id, questions, db)

        elif output_type == "missing_concepts":
            await _persist_missing_concepts(session_id, ai_output_id, content, db)

        elif output_type == "experiments":
            experiments = content.get("experiments") or []
            await _persist_experiments(session_id, ai_output_id, experiments, db)

    await db.commit()


async def _persist_quiz_questions(
    session_id: uuid.UUID,
    ai_output_id: uuid.UUID,
    questions: list[dict],
    db: AsyncSession,
) -> None:
    # Delete existing questions for this session to avoid duplicates on re-generation
    from sqlalchemy import delete
    await db.execute(
        delete(QuizQuestion).where(QuizQuestion.session_id == session_id)
    )
    for q in questions:
        db.add(
            QuizQuestion(
                id=uuid.uuid4(),
                session_id=session_id,
                ai_output_id=ai_output_id,
                question_type=q["type"],
                text=q["text"],
                options=q.get("options"),
                correct_answer={"value": q["correct"]},
                bloom_level=q.get("bloom_level"),
                topic=q.get("topic"),
                skill_tag=q.get("skill_tag"),
            )
        )


async def _persist_missing_concepts(
    session_id: uuid.UUID,
    ai_output_id: uuid.UUID,
    data: dict,
    db: AsyncSession,
) -> None:
    gaps = data.get("prerequisite_gaps") or []
    incomplete = data.get("incomplete_topics") or []

    for concept_text in gaps:
        db.add(
            MissingConcept(
                id=uuid.uuid4(),
                session_id=session_id,
                ai_output_id=ai_output_id,
                concept=concept_text,
                concept_type="prerequisite_gap",
            )
        )

    for concept_text in incomplete:
        db.add(
            MissingConcept(
                id=uuid.uuid4(),
                session_id=session_id,
                ai_output_id=ai_output_id,
                concept=concept_text,
                concept_type="incomplete_topic",
            )
        )


async def _persist_experiments(
    session_id: uuid.UUID,
    ai_output_id: uuid.UUID,
    experiments: list[dict],
    db: AsyncSession,
) -> None:
    for exp in experiments:
        db.add(
            ExperimentSuggestion(
                id=uuid.uuid4(),
                session_id=session_id,
                ai_output_id=ai_output_id,
                title=exp.get("title", "Untitled"),
                topic=exp.get("topic"),
                difficulty=exp.get("difficulty", "medium"),
                materials=exp.get("materials", []),
                steps=exp.get("steps", []),
                expected_outcome=exp.get("expected_outcome"),
                safety_note=exp.get("safety_note"),
            )
        )


# ---------------------------------------------------------------------------
# Classroom memory update
# ---------------------------------------------------------------------------

async def _update_classroom_memory(
    teacher_id: uuid.UUID,
    session_id: uuid.UUID,
    notes_markdown: str | None,
    missing_data: dict,
    db: AsyncSession,
) -> None:
    # Load or create memory record
    memory = (
        await db.execute(
            select(ClassroomMemory).where(ClassroomMemory.teacher_id == teacher_id)
        )
    ).scalar_one_or_none()

    new_topics = _extract_headings(notes_markdown or "")
    suggested_next = missing_data.get("suggested_next", "")
    pending = (
        (missing_data.get("prerequisite_gaps") or [])
        + (missing_data.get("incomplete_topics") or [])
    )

    if memory:
        existing_topics: list = list(memory.topics_covered or [])
        # Add new topics (dedup)
        for t in new_topics:
            if t not in existing_topics:
                existing_topics.append(t)
        memory.topics_covered = existing_topics
        memory.pending_concepts = pending
        memory.suggested_next = suggested_next
        memory.last_session_id = session_id
    else:
        db.add(
            ClassroomMemory(
                id=uuid.uuid4(),
                teacher_id=teacher_id,
                last_session_id=session_id,
                topics_covered=new_topics,
                pending_concepts=pending,
                suggested_next=suggested_next,
            )
        )
    await db.commit()


# ---------------------------------------------------------------------------
# OCR text loading
# ---------------------------------------------------------------------------

async def _get_session_diagrams(session_id: uuid.UUID, db: AsyncSession) -> list[dict]:
    """
    Collect every board-diagram crop + correctness validation across the
    session's frames (populated during OCR — see crop_and_validate_diagrams
    in app/ocr/ocr_engine.py), ordered by when they were captured, for
    display in the Notes output's "Board Diagrams" section.
    """
    from app.models.ocr_result import OCRResult
    from app.models.frame import Frame

    rows = (
        await db.execute(
            select(Frame, OCRResult)
            .join(OCRResult, OCRResult.frame_id == Frame.id)
            .where(Frame.session_id == session_id)
            .where(Frame.ocr_status == "done")
            .order_by(Frame.sequence_no)
        )
    ).all()

    diagrams: list[dict] = []
    for frame, ocr in rows:
        if not ocr or not ocr.structured_json:
            continue
        for d in ocr.structured_json.get("diagrams") or []:
            diagrams.append({
                "frame_id": str(frame.id),
                "index": d.get("index", 0),
                "description": d.get("description", ""),
                "validation": d.get("validation") or {},
            })
    return diagrams


async def _get_textbook_text(session_id: uuid.UUID, db: AsyncSession) -> str:
    """
    Fallback content source for notes/quiz/homework/etc. generation when the
    session has no usable board-capture OCR text yet — e.g. a teacher who
    uploaded a textbook chapter or a concept-notes worksheet under the
    Textbook tab and wants AI outputs generated straight from that, without
    first having to capture or photograph anything. Joins every page of
    every non-failed Textbook row for this session (both content_type=
    "textbook" and "concept_notes" are fair game here — either is real
    teaching material) in upload order, page order within each.
    """
    from app.models.textbook import Textbook

    rows = (
        await db.execute(
            select(Textbook)
            .where(Textbook.session_id == session_id, Textbook.status != "failed")
            .order_by(Textbook.created_at)
        )
    ).scalars().all()

    parts = []
    for tb in rows:
        pages = [p for p in (tb.raw_pages or []) if p and p.strip()]
        if not pages:
            continue
        label = tb.title or ("Concept notes" if tb.content_type == "concept_notes" else "Textbook")
        parts.append(f"--- {label} ---\n" + "\n\n".join(pages))

    return "\n\n".join(parts).strip()


async def _get_merged_ocr_text(session_id: uuid.UUID, db: AsyncSession) -> str:
    """
    Load merged OCR text for the session.
    First tries the ai_outputs table (if a prior merge was stored).
    Falls back to concatenating all OCRResult rows ordered by frame sequence.
    """
    from app.models.ocr_result import OCRResult
    from app.models.frame import Frame

    # Try stored merge
    stored = (
        await db.execute(
            select(AIOutput).where(
                AIOutput.session_id == session_id,
                AIOutput.output_type == "ocr_merge",
            )
        )
    ).scalar_one_or_none()
    if stored and stored.content_json and stored.content_json.get("merged_text"):
        return stored.content_json["merged_text"]

    # Build from individual OCR results
    rows = (
        await db.execute(
            select(Frame, OCRResult)
            .outerjoin(OCRResult, OCRResult.frame_id == Frame.id)
            .where(Frame.session_id == session_id)
            .where(Frame.ocr_status == "done")
            .order_by(Frame.sequence_no)
        )
    ).all()

    # Hallucination patterns — sentences that describe the image/room rather than
    # transcribing board text.  These are stripped line-by-line before joining.
    import re as _re2
    _HALLU_LINE_RE = _re2.compile(
        r"\bthis (?:appears?|seems?) to be\b"
        r"|\bi (?:can see|notice|observe|detect)\b"
        r"|\bthe (?:board|image|photo|picture|chalkboard|whiteboard) (?:shows?|contains?|appears?)\b"
        r"|\broom setup\b"
        r"|\bfeaturing .{0,30}(?:bed|chair|desk|table|sofa|couch|mattress|furniture)\b"
        r"|\b(?:bunk|twin|double|single) bed\b"
        r"|\bfabric[- ]covered\b"
        r"|\bsetup featuring\b"
        r"|\b(?:in|of) the (?:image|photo|picture|room|background)\b"
        r"|\bvisible in the\b"
        r"|\bthe image (?:shows?|depicts?|features?|contains?)\b"
        r"|\bthe photo (?:shows?|depicts?|features?|contains?)\b",
        _re2.IGNORECASE,
    )

    def _clean_frame_text(raw: str) -> str:
        """Strip hallucinated image-description sentences, keep real board lines."""
        lines = raw.split("\n")
        clean = [ln for ln in lines if not _HALLU_LINE_RE.search(ln)]
        return "\n".join(clean).strip()

    parts = []
    for frame, ocr in rows:
        if not ocr or not ocr.raw_text:
            continue
        # Skip frames whose OCR was produced by the placeholder engine —
        # these contain no real board content and would cause hallucination.
        if ocr.engine_used in ("placeholder", "none"):
            continue
        text = ocr.raw_text.strip()
        # Skip empty or pure-placeholder strings
        if not text or text.startswith("[OCR Placeholder"):
            continue
        # Strip hallucinated image-description sentences line by line
        text = _clean_frame_text(text)
        if not text:
            continue
        parts.append(text)

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Classroom memory helper
# ---------------------------------------------------------------------------

async def _get_memory_topics(teacher_id: uuid.UUID, db: AsyncSession) -> str:
    memory = (
        await db.execute(
            select(ClassroomMemory).where(ClassroomMemory.teacher_id == teacher_id)
        )
    ).scalar_one_or_none()
    if not memory or not memory.topics_covered:
        return ""
    topics = memory.topics_covered
    # Return last 15 topics as a readable list
    return ", ".join(str(t) for t in topics[-15:])


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)


def _extract_headings(markdown: str) -> list[str]:
    return [m.group(1).strip() for m in _HEADING_RE.finditer(markdown)]


def _extract_topics(text: str) -> str:
    """
    Extract topic keywords from markdown notes or OCR text.
    Headings are the best signal; otherwise return first 300 chars.
    """
    headings = _extract_headings(text)
    if headings:
        return ", ".join(headings[:10])
    # Fallback: first 300 chars with newlines collapsed
    return " ".join(text[:300].split())


def _truncate_to_tokens(text: str, max_tokens: int) -> tuple[str, bool]:
    """
    Estimate token count as len(text) / 4.
    Returns (truncated_text, was_truncated).
    """
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text, False
    truncated = text[:max_chars]
    # Snap to last sentence boundary to avoid cutting mid-sentence
    last_period = truncated.rfind(".")
    if last_period > max_chars // 2:
        truncated = truncated[: last_period + 1]
    return truncated + "\n[OCR text truncated for token budget]", True


# ---------------------------------------------------------------------------
# Placeholder generation (fallback / no API key)
# ---------------------------------------------------------------------------

async def run_placeholder_generation(
    session_id: uuid.UUID,
    output_types: list[str],
    job_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """
    Produce deterministic placeholder outputs.
    Called when OPENAI_API_KEY is empty or OCR text is insufficient.
    Kept for backward compat — existing tests call this directly.
    """
    ai_output_id_for_quiz: uuid.UUID | None = None

    for output_type in output_types:
        if output_type == "quiz":
            content = {"questions": _PLACEHOLDER_QUIZ, "metadata": {"placeholder": True}}
        else:
            content = dict(_PLACEHOLDER_OUTPUTS.get(output_type, {"placeholder": True}))

        existing = (
            await db.execute(
                select(AIOutput).where(
                    AIOutput.session_id == session_id,
                    AIOutput.output_type == output_type,
                )
            )
        ).scalar_one_or_none()

        if existing:
            existing.status = "ready"
            existing.content_json = content
            existing.model_used = "placeholder"
            existing.tokens_used = 0
            existing.generation_ms = 0
        else:
            row = AIOutput(
                id=uuid.uuid4(),
                session_id=session_id,
                output_type=output_type,
                status="ready",
                content_json=content,
                model_used="placeholder",
                tokens_used=0,
                generation_ms=0,
            )
            db.add(row)
            if output_type == "quiz":
                await db.flush()
                ai_output_id_for_quiz = row.id

    # Placeholder quiz questions
    if "quiz" in output_types and ai_output_id_for_quiz:
        for q in _PLACEHOLDER_QUIZ:
            db.add(
                QuizQuestion(
                    id=uuid.uuid4(),
                    session_id=session_id,
                    ai_output_id=ai_output_id_for_quiz,
                    question_type=q["type"],
                    text=q["text"],
                    options=q.get("options"),
                    correct_answer={"value": q["correct"]},
                    bloom_level=q.get("bloom_level"),
                    topic=q.get("topic"),
                    skill_tag=q.get("skill_tag"),
                )
            )

    job = await db.get(Job, job_id)
    if job:
        job.status = "completed"
        job.progress = 100

    await db.commit()
