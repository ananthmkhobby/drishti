"""
Tests for practice_service.prune_old_attempts_with_summary — keeps only the
most recent _KEEP_RECENT_ATTEMPTS completed attempts per question, folding
anything older into one PracticeAttemptSummary row first (see that model's
docstring). This genuinely deletes rows and blobs, so it needs real
coverage: the boundary (exactly at the cap = no-op), the aggregation
(misconception counts, revision_required heuristic), and that the deleted
rows' image files are actually removed, not just the DB rows.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from app.models.practice_question import PracticeQuestion
from app.models.practice_station import PracticeStation
from app.models.practice_attempt import PracticeAttempt
from app.models.practice_attempt_summary import PracticeAttemptSummary
from app.services import practice_service
from tests.conftest import TEACHER_ID, CLASSROOM_ID


async def _make_question_and_station(db: AsyncSession):
    session = Session(
        teacher_id=uuid.UUID(TEACHER_ID), classroom_id=uuid.UUID(CLASSROOM_ID),
        subject="Math", grade="Grade 5", board_type="chalkboard",
        capture_mode="time_based", capture_interval_sec=10, status="active",
    )
    db.add(session)
    await db.flush()
    question = PracticeQuestion(session_id=session.id, text="2+2=?", subject="Math", topic="Addition")
    db.add(question)
    await db.flush()
    station = PracticeStation(session_id=session.id, label="Desk 1", capture_interval_sec=10, status="idle")
    db.add(station)
    await db.flush()
    return question, station


async def _add_attempts(
    db: AsyncSession, question, station, n: int, *,
    student_states=None, misconception_codes=None, hint_levels=None, with_blob=False,
):
    """Adds `n` completed attempts, oldest first, spaced a minute apart so
    ordering/time-taken math is unambiguous. `student_states`/
    `misconception_codes`/`hint_levels` (if given) are cycled per-attempt."""
    base_time = datetime.now(timezone.utc) - timedelta(hours=1)
    attempts = []
    for i in range(n):
        image_path = None
        if with_blob:
            image_path = f"/tmp/aci-test-uploads/prune-test-{uuid.uuid4()}.jpg"
            Path(image_path).parent.mkdir(parents=True, exist_ok=True)
            Path(image_path).write_bytes(b"fake-image")
        a = PracticeAttempt(
            question_id=question.id, session_id=question.session_id, station_id=station.id,
            attempt_no=i + 1, input_type="image", image_path=image_path, status="complete",
            student_state=(student_states[i % len(student_states)] if student_states else "progressing"),
            misconception_code=(misconception_codes[i % len(misconception_codes)] if misconception_codes else None),
            hint_level=(hint_levels[i % len(hint_levels)] if hint_levels else None),
        )
        db.add(a)
        await db.flush()
        a.created_at = base_time + timedelta(minutes=i)
        attempts.append(a)
    await db.commit()
    return attempts


@pytest.mark.asyncio
async def test_at_or_under_the_cap_is_a_no_op(db: AsyncSession):
    question, station = await _make_question_and_station(db)
    await _add_attempts(db, question, station, 10)

    await practice_service.prune_old_attempts_with_summary(db, question.id, station.id)

    remaining = (await db.execute(select(PracticeAttempt).where(PracticeAttempt.question_id == question.id))).scalars().all()
    summaries = (await db.execute(select(PracticeAttemptSummary).where(PracticeAttemptSummary.question_id == question.id))).scalars().all()
    assert len(remaining) == 10
    assert len(summaries) == 0


@pytest.mark.asyncio
async def test_over_the_cap_prunes_the_oldest_and_keeps_the_most_recent_ten(db: AsyncSession):
    question, station = await _make_question_and_station(db)
    attempts = await _add_attempts(db, question, station, 13)

    await practice_service.prune_old_attempts_with_summary(db, question.id, station.id)

    remaining = (await db.execute(select(PracticeAttempt).where(PracticeAttempt.question_id == question.id))).scalars().all()
    assert len(remaining) == 10
    remaining_ids = {a.id for a in remaining}
    # The 10 most recently created (last 10 of the 13) must survive.
    assert remaining_ids == {a.id for a in attempts[3:]}

    summaries = (await db.execute(select(PracticeAttemptSummary).where(PracticeAttemptSummary.question_id == question.id))).scalars().all()
    assert len(summaries) == 1
    assert summaries[0].attempts_summarized == 3
    assert summaries[0].station_id == station.id


@pytest.mark.asyncio
async def test_summary_aggregates_misconceptions_hints_and_solved_flag(db: AsyncSession):
    question, station = await _make_question_and_station(db)
    # 12 attempts: the first 2 (which get pruned, cap=10) are a
    # misconception followed by a solve.
    await _add_attempts(
        db, question, station, 12,
        student_states=["misconception", "solved"] + ["progressing"] * 10,
        misconception_codes=["MC_CARRY", "MC_CARRY"] + [None] * 10,
        hint_levels=[2, 0] + [0] * 10,
    )

    await practice_service.prune_old_attempts_with_summary(db, question.id, station.id)

    summary = (await db.execute(select(PracticeAttemptSummary).where(PracticeAttemptSummary.question_id == question.id))).scalar_one()
    assert summary.attempts_summarized == 2
    assert summary.solved is True  # the 2nd of the pruned batch was "solved"
    assert summary.misconception_codes == {"MC_CARRY": 2}  # both pruned attempts hit it
    assert summary.hint_levels_seen == {"2": 1, "0": 1}
    assert summary.revision_required is False  # solved, single misconception code — no red flag
    assert summary.first_attempt_at < summary.last_attempt_at


@pytest.mark.asyncio
async def test_revision_required_when_never_solved(db: AsyncSession):
    question, station = await _make_question_and_station(db)
    await _add_attempts(
        db, question, station, 11,
        student_states=["misconception"] + ["progressing"] * 10,
        misconception_codes=["MC_CARRY"] + [None] * 10,
    )

    await practice_service.prune_old_attempts_with_summary(db, question.id, station.id)

    summary = (await db.execute(select(PracticeAttemptSummary).where(PracticeAttemptSummary.question_id == question.id))).scalar_one()
    assert summary.attempts_summarized == 1
    assert summary.solved is False
    assert summary.revision_required is True  # never solved in this batch


@pytest.mark.asyncio
async def test_revision_required_when_teacher_required_even_if_later_solved(db: AsyncSession):
    question, station = await _make_question_and_station(db)
    # 12 attempts, cap 10 -> the oldest 2 get pruned; put BOTH the
    # escalation and the eventual solve inside that pruned batch.
    await _add_attempts(
        db, question, station, 12,
        student_states=["teacher_required", "solved"] + ["progressing"] * 10,
    )

    await practice_service.prune_old_attempts_with_summary(db, question.id, station.id)

    summary = (await db.execute(select(PracticeAttemptSummary).where(PracticeAttemptSummary.question_id == question.id))).scalar_one()
    assert summary.attempts_summarized == 2
    assert summary.solved is True
    assert summary.revision_required is True  # escalated to teacher at some point in the batch


@pytest.mark.asyncio
async def test_pruned_attempts_image_blobs_are_actually_deleted(db: AsyncSession):
    question, station = await _make_question_and_station(db)
    attempts = await _add_attempts(db, question, station, 11, with_blob=True)
    pruned_path = attempts[0].image_path
    kept_path = attempts[-1].image_path
    assert Path(pruned_path).exists()
    assert Path(kept_path).exists()

    await practice_service.prune_old_attempts_with_summary(db, question.id, station.id)

    assert not Path(pruned_path).exists()
    assert Path(kept_path).exists()


@pytest.mark.asyncio
async def test_multiple_prune_events_accumulate_separate_summaries(db: AsyncSession):
    question, station = await _make_question_and_station(db)
    await _add_attempts(db, question, station, 11)
    await practice_service.prune_old_attempts_with_summary(db, question.id, station.id)
    await _add_attempts(db, question, station, 3)  # now 13 total, 3 new on top of the kept 10
    await practice_service.prune_old_attempts_with_summary(db, question.id, station.id)

    summaries = (await db.execute(select(PracticeAttemptSummary).where(PracticeAttemptSummary.question_id == question.id))).scalars().all()
    assert len(summaries) == 2  # one per prune event, not merged into one

    remaining = (await db.execute(select(PracticeAttempt).where(PracticeAttempt.question_id == question.id))).scalars().all()
    assert len(remaining) == 10
