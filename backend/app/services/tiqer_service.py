"""
TiQer export service.

Owns all transformation logic for converting ACI quiz questions into the
canonical TiQer JSON format.  Designed to be called from the outputs router.

Replacement note (Phase 2):
    Replace ``_push_to_tiqer_api`` with a real HTTP call to TiQer once the
    integration credentials are available.  The payload shape is stable.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone

from app.models.quiz_question import QuizQuestion
from app.models.session import Session
from app.schemas.tiqer import (
    TiQerExportMetadata,
    TiQerExportPayload,
    TiQerOption,
    TiQerQuestion,
)

logger = logging.getLogger(__name__)

# ── Lookup tables ─────────────────────────────────────────────────────────────

_IDX_TO_KEY: dict[int, str] = {0: "A", 1: "B", 2: "C", 3: "D"}

_BLOOM_DIFFICULTY: dict[str, str] = {
    "remember":  "easy",
    "understand": "easy",
    "apply":     "medium",
    "analyze":   "medium",
    "evaluate":  "hard",
    "create":    "hard",
}

_BLOOM_LEVELS = ("remember", "understand", "apply", "analyze", "evaluate", "create")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _normalise_skill_tag(raw: str) -> str:
    """Slugify: lowercase, replace spaces/apostrophes/special chars with hyphens."""
    slug = raw.lower().strip()
    slug = re.sub(r"['\"]", "", slug)
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:80]


def _skill_tag_for(q: QuizQuestion) -> str:
    """Return persisted skill_tag, or derive from topic, or fall back to 'general'."""
    if q.skill_tag:
        return _normalise_skill_tag(q.skill_tag)
    if q.topic:
        return _normalise_skill_tag(q.topic)
    return "general"


def _correct_answer_for(q: QuizQuestion) -> str:
    """
    Convert the DB ``correct_answer`` JSON to the TiQer string format.

    DB stores:
        MCQ:  {"value": 0}   (index 0–3)
        T/F:  {"value": True} or {"value": False}
    """
    if not q.correct_answer:
        return "A"  # safe default

    value = q.correct_answer.get("value")

    if q.question_type == "mcq":
        if isinstance(value, int) and value in _IDX_TO_KEY:
            return _IDX_TO_KEY[value]
        # Tolerate strings "A"-"D" stored directly
        if isinstance(value, str) and value.upper() in _IDX_TO_KEY.values():
            return value.upper()
        return "A"

    if q.question_type == "true_false":
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            return "true" if value.lower() in ("true", "1", "yes") else "false"
        return "false"

    return str(value)


def _bloom_level_for(q: QuizQuestion) -> str:
    bl = (q.bloom_level or "remember").lower()
    return bl if bl in _BLOOM_DIFFICULTY else "remember"


def _topic_for(q: QuizQuestion, session: Session) -> str:
    return q.topic or session.subject or "General"


# ── Build payload ─────────────────────────────────────────────────────────────

def build_tiqer_payload(
    session: Session,
    teacher_id: uuid.UUID,
    questions: list[QuizQuestion],
    tiqer_class_id: str,
    export_id: str | None = None,
) -> TiQerExportPayload:
    """
    Convert a list of QuizQuestion ORM rows + Session into a TiQerExportPayload.

    This function is pure (no DB calls) so it can be unit-tested in isolation.
    """
    subject  = session.subject or "General"
    grade    = session.grade   or "Unknown Grade"
    now      = datetime.now(timezone.utc)
    eid      = export_id or str(uuid.uuid4())

    tiqer_questions: list[TiQerQuestion] = []
    bloom_dist: dict[str, int] = {level: 0 for level in _BLOOM_LEVELS}
    mcq_count = tf_count = 0

    for i, q in enumerate(questions, start=1):
        bloom    = _bloom_level_for(q)
        diff     = _BLOOM_DIFFICULTY.get(bloom, "medium")
        skill    = _skill_tag_for(q)
        correct  = _correct_answer_for(q)
        topic    = _topic_for(q, session)

        if q.question_type == "mcq":
            opts: list[TiQerOption] | None = None
            if q.options and isinstance(q.options, list):
                opts = [
                    TiQerOption(key=_IDX_TO_KEY[j], text=str(opt_text))
                    for j, opt_text in enumerate(q.options)
                    if j in _IDX_TO_KEY
                ]
            mcq_count += 1
        else:
            opts = None
            tf_count += 1

        bloom_dist[bloom] = bloom_dist.get(bloom, 0) + 1

        tiqer_questions.append(
            TiQerQuestion(
                question_id=str(q.id),
                sequence=i,
                type=q.question_type,   # type: ignore[arg-type]
                text=q.text,
                options=opts,
                correct_answer=correct,
                bloom_level=bloom,
                skill_tag=skill,
                topic=topic,
                grade=grade,
                subject=subject,
                difficulty=diff,         # type: ignore[arg-type]
            )
        )

    metadata = TiQerExportMetadata(
        bloom_distribution=bloom_dist,
        mcq_count=mcq_count,
        true_false_count=tf_count,
    )

    return TiQerExportPayload(
        export_id=eid,
        tiqer_class_id=tiqer_class_id,
        session_id=str(session.id),
        exported_at=now,
        teacher_id=str(teacher_id),
        subject=subject,
        grade=grade,
        question_count=len(questions),
        questions=tiqer_questions,
        metadata=metadata,
    )


# ── Phase 2 stub: real TiQer API call ────────────────────────────────────────

async def push_to_tiqer_api(payload: TiQerExportPayload) -> str:
    """
    Push the export payload to the TiQer platform API.

    Phase 2 TODO: Replace this stub with the real HTTP call.
    Returns the TiQer-assigned session ID.
    """
    # Stub: generate a deterministic-looking session ID for the MVP demo
    logger.info(
        "TiQer export (stub): class=%s questions=%d",
        payload.tiqer_class_id,
        payload.question_count,
    )
    stub_id = f"TQR-{payload.tiqer_class_id.upper()}-{payload.export_id[:8].upper()}"
    return stub_id


# ── Serialise payload for storage / download ──────────────────────────────────

def serialise_payload(payload: TiQerExportPayload) -> str:
    """Return the payload as a nicely-formatted JSON string."""
    return payload.model_dump_json(indent=2)


def payload_to_dict(payload: TiQerExportPayload) -> dict:
    return json.loads(serialise_payload(payload))
