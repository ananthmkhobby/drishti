"""
Regression test for the "once we get the answer right, hint is not
accurate" report (2026-09-24). Real production data showed the auto-
capture loop kept firing after a question was already solved, and the
very next capture — a genuinely worse/no-longer-relevant frame — could
flip a correct "solved" verdict back to a false misconception on a
question that was actually done; on one question's real history this
alone accounted for over half of all captures being wasted
"off_topic_content" reads.

Fix: process_attempt now sets the station's status back to "idle" (same
field the student's own Pause button sets) the moment a question is
graded "solved", stopping the loop before it can capture that next,
irrelevant frame.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import cv2
import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from app.models.practice_question import PracticeQuestion
from app.models.practice_station import PracticeStation
from app.models.practice_attempt import PracticeAttempt
from app.ocr import practice_engine
from app.services import practice_service, storage_service
from tests.conftest import TEACHER_ID, CLASSROOM_ID


def _valid_test_image_bytes() -> bytes:
    """A real JPEG large enough and with enough variance to clear Gate A's
    size/blur/brightness checks (image_preprocessor.MIN_*)."""
    img = np.random.randint(80, 200, (400, 600, 3), dtype=np.uint8)
    cv2.rectangle(img, (50, 50), (550, 350), (0, 0, 0), 3)  # real edges -> real Laplacian variance
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


async def _make_solvable_attempt(db: AsyncSession, station_status: str):
    session = Session(
        teacher_id=uuid.UUID(TEACHER_ID), classroom_id=uuid.UUID(CLASSROOM_ID),
        subject="Math", grade="Grade 3", board_type="chalkboard",
        capture_mode="time_based", capture_interval_sec=10, status="active",
    )
    db.add(session)
    await db.flush()

    question = PracticeQuestion(
        session_id=session.id, text="47 + 58 = ?", subject="Math", topic="Addition",
        final_answer={"text": "105"}, status="approved",
    )
    db.add(question)
    await db.flush()

    station = PracticeStation(
        session_id=session.id, label="Desk 1", capture_interval_sec=10, status=station_status,
    )
    station.active_question_id = question.id
    db.add(station)
    await db.flush()

    image_bytes = _valid_test_image_bytes()
    attempt_id = uuid.uuid4()
    image_path = await storage_service.save_practice_attempt_image(session.id, str(attempt_id), image_bytes)

    attempt = PracticeAttempt(
        id=attempt_id, question_id=question.id, session_id=session.id, station_id=station.id,
        attempt_no=1, input_type="image", image_path=image_path, status="processing",
    )
    db.add(attempt)
    await db.commit()
    return attempt, station


@pytest.mark.asyncio
async def test_solved_attempt_stops_a_capturing_station(db: AsyncSession):
    attempt, station = await _make_solvable_attempt(db, station_status="capturing")

    with patch.object(practice_engine, "extract_steps", new=AsyncMock(return_value={
             "steps": [{"text": "47+58=105", "bbox": None, "confidence": 0.95}],
             "overall_confidence": 0.95, "empty_reason": "none",
         })), \
         patch.object(practice_service, "validate_step", new=AsyncMock(return_value={
             "validation_status": "solved", "error_step_index": None, "misconception_code": None,
             "reason_code": "correct_final_answer", "confidence": 1.0, "source": "cloud", "column_hint": None,
         })):
        result = await practice_service.process_attempt(attempt.id, db)

    assert result.student_state == "solved"
    refreshed_station = await db.get(PracticeStation, station.id)
    assert refreshed_station.status == "idle"


@pytest.mark.asyncio
async def test_non_solved_attempt_leaves_a_capturing_station_running(db: AsyncSession):
    attempt, station = await _make_solvable_attempt(db, station_status="capturing")

    with patch.object(practice_engine, "extract_steps", new=AsyncMock(return_value={
             "steps": [{"text": "47+58=103", "bbox": None, "confidence": 0.95}],
             "overall_confidence": 0.95, "empty_reason": "none",
         })), \
         patch.object(practice_service, "validate_step", new=AsyncMock(return_value={
             "validation_status": "arithmetic_slip", "error_step_index": 0, "misconception_code": None,
             "reason_code": "wrong_sum", "confidence": 0.9, "source": "cloud", "column_hint": None,
         })):
        result = await practice_service.process_attempt(attempt.id, db)

    assert result.student_state != "solved"
    refreshed_station = await db.get(PracticeStation, station.id)
    assert refreshed_station.status == "capturing"  # untouched — still working on it


@pytest.mark.asyncio
async def test_solved_attempt_on_an_already_idle_station_is_a_no_op(db: AsyncSession):
    # An already-idle station (e.g. a manual capture, or already stopped)
    # shouldn't error or need special-casing — just stays idle.
    attempt, station = await _make_solvable_attempt(db, station_status="idle")

    with patch.object(practice_engine, "extract_steps", new=AsyncMock(return_value={
             "steps": [{"text": "47+58=105", "bbox": None, "confidence": 0.95}],
             "overall_confidence": 0.95, "empty_reason": "none",
         })), \
         patch.object(practice_service, "validate_step", new=AsyncMock(return_value={
             "validation_status": "solved", "error_step_index": None, "misconception_code": None,
             "reason_code": "correct_final_answer", "confidence": 1.0, "source": "cloud", "column_hint": None,
         })):
        result = await practice_service.process_attempt(attempt.id, db)

    assert result.student_state == "solved"
    refreshed_station = await db.get(PracticeStation, station.id)
    assert refreshed_station.status == "idle"
