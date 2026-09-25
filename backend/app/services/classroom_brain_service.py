"""
Classroom Brain — grounded Q&A over a teacher's classroom memory + recent
session history. Powers voice queries like "help me summarise where we
stopped yesterday" or "what should I teach next".

Not full RAG over lesson content (yet) — grounds on the same ClassroomMemory
row the dashboard already exposes (topics_covered, pending_concepts,
suggested_next, kept up to date by _update_classroom_memory in ai_service.py)
plus a short list of recent session titles/subjects/dates. For a general
subject-matter question with no session-specific angle ("explain photo-
synthesis simply"), the model just answers from its own knowledge — that's
what makes this work for any subject/grade without a curriculum database.

Same local-first pattern as voice_intent_service: Qwen via Ollama first,
OpenAI as fallback.

Disambiguation: ClassroomMemory is one row per TEACHER (not per subject), so
topics_covered/pending_concepts are a single blob spanning every subject
they've ever taught. For a recap-style question ("where did we stop") with
no subject/grade named and more than one distinct subject taught recently,
we ask a clarifying question instead of guessing which class they mean —
rather than silently blending unrelated subjects together.
"""
from __future__ import annotations

import logging
import re
import uuid

import httpx
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.classroom_memory import ClassroomMemory
from app.models.session import Session

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the Classroom Brain, a voice assistant built into a \
classroom capture app. A teacher is asking you a question out loud, between \
classes. If asked who you are or what you can do, say you're their \
Classroom Brain — you help them recap what a class covered, see what's \
pending, suggest what to teach next, and answer subject questions for any \
grade 1-10 topic.

Answer length: default to 1-3 sentences. Only go longer (up to ~5 sentences) \
if the question explicitly asks for detail, a list, or a multi-part \
explanation. Never pad with filler or repeat the question back. This will \
be read aloud, so avoid bullet points, markdown, or headers.

You may be given CONTEXT about their recent classes (topics already \
covered, concepts flagged as not-yet-understood, a suggested next topic, \
and recent session titles). Use it when the question is about their \
classes ("where did we stop", "what's pending", "what should I teach \
next"). If the question is a general subject-matter question unrelated to \
their specific classes (e.g. "explain photosynthesis simply", "give an \
example of Newton's third law"), just answer it directly using your own \
knowledge — you don't need the context for that, and it's fine if there \
isn't any yet."""

# Heuristic for "this question is about recapping/continuing a specific
# class" vs. a general subject question or identity question. Two jobs:
#   1. Only recap-style questions need subject/grade disambiguation.
#   2. Only recap-style questions get the classroom-context block in the
#      prompt at all — a small local model doesn't reliably ignore context
#      it's handed even when told to ("what's 2+2" was answering correctly
#      THEN spontaneously appending an unrelated topics-covered summary,
#      because the context was there to comment on). Gating this in code,
#      not relying on the model's judgment, is what actually fixes it.
_RECAP_PATTERN = re.compile(
    r"\b(yesterday|last class|last session|where.*(stop|leave)|"
    r"what.*(pending|covered|left|taught)|teach next|next topic|recap|catch up|"
    r"my (class|classes|session|sessions|students)|progress)\b",
    re.IGNORECASE,
)


async def _fetch_context(teacher_id: uuid.UUID, db: AsyncSession) -> dict:
    memory = (
        await db.execute(select(ClassroomMemory).where(ClassroomMemory.teacher_id == teacher_id))
    ).scalar_one_or_none()

    recent_sessions = (
        await db.execute(
            select(Session)
            .where(Session.teacher_id == teacher_id, Session.deleted_at.is_(None))
            .order_by(desc(Session.created_at))
            .limit(8)
        )
    ).scalars().all()

    return {
        "topics_covered": (memory.topics_covered if memory else []) or [],
        "pending_concepts": (memory.pending_concepts if memory else []) or [],
        "suggested_next": (memory.suggested_next if memory else "") or "",
        "recent_sessions": [
            {
                "title": s.title or s.subject or "Untitled session",
                "subject": s.subject,
                "grade": s.grade,
                "date": s.created_at.isoformat() if s.created_at else None,
            }
            for s in recent_sessions
        ],
    }


def _check_ambiguity(
    question: str, context: dict, subject: str | None, grade: str | None
) -> str | None:
    """
    Returns a clarification question to ask the teacher, or None if the
    question is unambiguous (either it's not a recap-style question, a
    subject/grade was already given, or there's only one recent class).
    """
    if subject or grade:
        return None
    if not _RECAP_PATTERN.search(question):
        return None

    sessions = context["recent_sessions"]
    if len(sessions) <= 1:
        return None

    distinct = {(s["subject"] or "unknown subject", s["grade"] or "unknown grade") for s in sessions[:3]}
    if len(distinct) <= 1:
        return None

    options = ", ".join(f"{subj} ({grd})" for subj, grd in distinct)
    return (
        f"I found a few different recent classes — {options}. "
        f"Which one did you mean? You can just say the subject or grade."
    )


def _filter_sessions(context: dict, subject: str | None, grade: str | None) -> list[dict]:
    sessions = context["recent_sessions"]
    if not (subject or grade):
        return sessions
    subj_l = (subject or "").lower()
    grade_l = (grade or "").lower()
    filtered = [
        s for s in sessions
        if (not subj_l or subj_l in (s["subject"] or "").lower())
        and (not grade_l or grade_l in (s["grade"] or "").lower())
    ]
    return filtered or sessions


def _build_user_prompt(
    question: str, context: dict, matched_sessions: list[dict], include_context: bool
) -> str:
    lines = [f"Question: {question}", ""]
    has_context = include_context and (
        context["topics_covered"] or context["pending_concepts"]
        or context["suggested_next"] or matched_sessions
    )
    if has_context:
        lines.append("CONTEXT about this teacher's recent classes:")
        if matched_sessions:
            lines.append("Relevant sessions (most recent first):")
            for s in matched_sessions:
                lines.append(
                    f"  - {s['title']} ({s['subject'] or 'unknown subject'}, "
                    f"{s['grade'] or 'unknown grade'}) on {s['date']}"
                )
        if context["topics_covered"]:
            lines.append(f"Topics covered so far: {', '.join(context['topics_covered'])}")
        if context["pending_concepts"]:
            lines.append(
                f"Concepts flagged as not-yet-understood / pending: "
                f"{', '.join(context['pending_concepts'])}"
            )
        if context["suggested_next"]:
            lines.append(f"Suggested next topic: {context['suggested_next']}")
    elif include_context:
        lines.append("(No class history available yet for this teacher.)")
    # else: question isn't about their classes — no context block at all,
    # so the model has nothing irrelevant to comment on.
    return "\n".join(lines)


async def _ask_local(prompt: str, base_url: str, model: str, timeout: int) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{base_url}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.4},
                    "keep_alive": -1,  # see voice_intent_service._classify_local for why
                },
            )
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content", "").strip()
            return content or None
    except Exception as exc:
        logger.warning("Classroom Brain: local Ollama call failed: %s", exc)
        return None


async def _ask_cloud(prompt: str, api_key: str, timeout: int) -> str | None:
    try:
        from openai import AsyncOpenAI
    except ImportError:
        return None
    client = AsyncOpenAI(api_key=api_key)
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=250,
            temperature=0.4,
            timeout=timeout,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        return (resp.choices[0].message.content or "").strip() or None
    except Exception as exc:
        logger.warning("Classroom Brain: OpenAI fallback failed: %s", exc)
        return None


async def answer_question(
    question: str,
    *,
    teacher_id: uuid.UUID,
    db: AsyncSession,
    ollama_base_url: str,
    ollama_model: str,
    openai_api_key: str,
    subject: str | None = None,
    grade: str | None = None,
    timeout_sec: int = 30,
    local_enabled: bool = True,
) -> dict:
    """
    Returns {"answer": str, "topics_covered": list, "pending_concepts": list,
    "suggested_next": str, "source": "local"|"cloud"|"none",
    "needs_clarification": bool}.
    """
    context = await _fetch_context(teacher_id, db)

    clarification = _check_ambiguity(question, context, subject, grade)
    if clarification:
        return {
            "answer": clarification,
            "topics_covered": [],
            "pending_concepts": [],
            "suggested_next": "",
            "source": "local",
            "needs_clarification": True,
        }

    include_context = bool(_RECAP_PATTERN.search(question))
    matched_sessions = _filter_sessions(context, subject, grade) if include_context else []
    prompt = _build_user_prompt(question, context, matched_sessions, include_context)

    answer = await _ask_local(prompt, ollama_base_url, ollama_model, timeout_sec) if local_enabled else None
    source = "local"
    if answer is None and openai_api_key:
        answer = await _ask_cloud(prompt, openai_api_key, timeout_sec)
        source = "cloud"
    if answer is None:
        answer = (
            "I couldn't reach either the local or online assistant right now — "
            "please try again in a moment."
        )
        source = "none"

    return {
        "answer": answer,
        # Only surface these alongside answers that actually used them —
        # otherwise the UI would show "Pending: ..." chips under an answer
        # to an unrelated question like "what's 2+2".
        "topics_covered": context["topics_covered"] if include_context else [],
        "pending_concepts": context["pending_concepts"] if include_context else [],
        "suggested_next": context["suggested_next"] if include_context else "",
        "source": source,
        "needs_clarification": False,
    }
