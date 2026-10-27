"""
Tests for the "productive struggle" counter-question step — on a student's
FIRST genuine mistake on a question, the system now asks them to explain
their own reasoning BEFORE handing them a hint, instead of going straight
to Gate G. Implements the NBER field-experiment finding (6,000+ middle-
school students) that AI support is most effective intervening with a
reflection prompt right after a mistake, not by immediately becoming more
helpful.

Coverage:
  - generate_counter_question/evaluate_explanation/generate_safe_hint unit
    behavior (mocked LLM, real prompt content)
  - process_attempt: a FIRST mistake sets counter_question and leaves
    hint_text null; a SECOND mistake on the same question (help_streak=1)
    skips the counter-question and goes straight to a normal hint
  - counter-question generation failing or leaking falls back to an
    immediate hint rather than leaving the student with nothing
"""
from __future__ import annotations

import json
import types
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


def _mock_openai_client(payload: dict):
    calls: list[dict] = []

    async def create(**kwargs):
        calls.append(kwargs)
        message = types.SimpleNamespace(content=json.dumps(payload))
        choice = types.SimpleNamespace(message=message)
        return types.SimpleNamespace(choices=[choice])

    fake_client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create))
    )
    return fake_client, calls


def _make_question(**overrides):
    base = dict(text="Evaluate: lim(x->0) sin(3x)/x", subject="Mathematics", answer_domain="numeric")
    base.update(overrides)
    return PracticeQuestion(session_id=None, **base)


@pytest.mark.asyncio
async def test_generate_counter_question_asks_about_reasoning_not_correctness():
    question = _make_question()
    fake_client, calls = _mock_openai_client({"counter_question": "What identity did you use to expand sin(3x)?"})
    with patch("openai.AsyncOpenAI", return_value=fake_client):
        result = await practice_service.generate_counter_question(
            question, "sin(3x) = 3sinx - 2sin^3x",
            ollama_base_url="http://unreachable.invalid:1", ollama_model="unused",
            openai_api_key="test-key", local_enabled=False,
        )
    assert result["counter_question"] == "What identity did you use to expand sin(3x)?"
    system_prompt_sent = calls[0]["messages"][0]["content"]
    assert "not a hint itself" in system_prompt_sent.lower()
    assert "never state or imply the correct answer" in system_prompt_sent.lower()


@pytest.mark.asyncio
async def test_evaluate_explanation_self_corrected():
    question = _make_question()
    fake_client, _ = _mock_openai_client({
        "outcome": "self_corrected",
        "encouragement": "Sounds like you've spotted it — go ahead and fix it up.",
    })
    with patch("openai.AsyncOpenAI", return_value=fake_client):
        result = await practice_service.evaluate_explanation(
            question, "What identity did you use?", "Oh wait, I think I used the wrong formula for sin(3x).",
            ollama_base_url="http://unreachable.invalid:1", ollama_model="unused",
            openai_api_key="test-key", local_enabled=False,
        )
    assert result["outcome"] == "self_corrected"
    assert "spotted it" in result["encouragement"]


@pytest.mark.asyncio
async def test_evaluate_explanation_confirmed_misconception_has_no_encouragement():
    question = _make_question()
    fake_client, _ = _mock_openai_client({
        "outcome": "confirmed_misconception",
        "encouragement": "this should be discarded by the caller",
    })
    with patch("openai.AsyncOpenAI", return_value=fake_client):
        result = await practice_service.evaluate_explanation(
            question, "What identity did you use?", "I used sin(3x) = 3sinx - 2sin^3x, that's the formula.",
            ollama_base_url="http://unreachable.invalid:1", ollama_model="unused",
            openai_api_key="test-key", local_enabled=False,
        )
    assert result["outcome"] == "confirmed_misconception"
    assert result["encouragement"] == ""  # encouragement only ever kept for self_corrected


@pytest.mark.asyncio
async def test_evaluate_explanation_empty_transcript_is_unclear_without_a_call():
    question = _make_question()
    result = await practice_service.evaluate_explanation(
        question, "What identity did you use?", "   ",
        ollama_base_url="http://unreachable.invalid:1", ollama_model="unused",
        openai_api_key="test-key", local_enabled=False,
    )
    assert result == {"outcome": "unclear", "encouragement": ""}


@pytest.mark.asyncio
async def test_generate_safe_hint_falls_back_on_leak():
    question = _make_question(final_answer={"text": "1"})
    with patch.object(practice_service, "generate_hint", new=AsyncMock(return_value={"hint_text": "the answer is 1", "source": "cloud"})), \
         patch.object(practice_service, "check_hint_leakage", new=AsyncMock(return_value=True)):
        hint_text, level = await practice_service.generate_safe_hint(
            question, 1, {"validation_status": "arithmetic_slip", "misconception_code": None},
            ollama_base_url="unused", ollama_model="unused", openai_api_key="unused", local_enabled=False,
        )
    assert level == 1
    assert "re-checking" in hint_text.lower()


# ---------------------------------------------------------------------------
# process_attempt integration — real Gate D/pipeline plumbing, mocked LLM gates
# ---------------------------------------------------------------------------

def _valid_test_image_bytes() -> bytes:
    img = np.random.randint(80, 200, (400, 600, 3), dtype=np.uint8)
    cv2.rectangle(img, (50, 50), (550, 350), (0, 0, 0), 3)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


async def _make_attempt(db: AsyncSession, attempt_no: int = 1):
    session = Session(
        teacher_id=uuid.UUID(TEACHER_ID), classroom_id=uuid.UUID(CLASSROOM_ID),
        subject="Math", grade="Grade 8", board_type="chalkboard",
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

    station = PracticeStation(session_id=session.id, label="Desk 1", capture_interval_sec=10, status="capturing")
    station.active_question_id = question.id
    db.add(station)
    await db.flush()

    image_bytes = _valid_test_image_bytes()
    attempt_id = uuid.uuid4()
    image_path = await storage_service.save_practice_attempt_image(session.id, str(attempt_id), image_bytes)

    attempt = PracticeAttempt(
        id=attempt_id, question_id=question.id, session_id=session.id, station_id=station.id,
        attempt_no=attempt_no, input_type="image", image_path=image_path, status="processing",
    )
    db.add(attempt)
    await db.commit()
    return attempt, station, question


@pytest.mark.asyncio
async def test_first_mistake_sets_counter_question_not_hint_text(db: AsyncSession):
    attempt, station, question = await _make_attempt(db, attempt_no=1)

    with patch.object(practice_engine, "extract_steps", new=AsyncMock(return_value={
             "steps": [{"text": "47+58=103", "bbox": None, "confidence": 0.95}],
             "overall_confidence": 0.95, "empty_reason": "none", "diagram_context": None,
         })), \
         patch.object(practice_service, "validate_step", new=AsyncMock(return_value={
             "validation_status": "arithmetic_slip", "error_step_index": 0, "misconception_code": None,
             "reason_code": "wrong_sum", "confidence": 0.9, "source": "cloud", "column_hint": None,
         })), \
         patch.object(practice_service, "generate_counter_question", new=AsyncMock(return_value={
             "counter_question": "How did you add the ones digits?", "source": "cloud",
         })), \
         patch.object(practice_service, "check_hint_leakage", new=AsyncMock(return_value=False)):
        result = await practice_service.process_attempt(attempt.id, db)

    assert result.hint_level == 1
    assert result.counter_question == "How did you add the ones digits?"
    assert result.hint_text is None
    assert result.explanation_outcome is None


@pytest.mark.asyncio
async def test_second_mistake_skips_counter_question_goes_straight_to_hint(db: AsyncSession):
    # A prior arithmetic_slip attempt on the same question -> help_streak=1
    # -> hint_level=2 -> normal hint path, no counter-question at all.
    # NOTE: the test DB is session-scoped (conftest.py's setup_database),
    # accumulating committed rows across every test in the run — an
    # unscoped `select(PracticeAttempt)` would grab some earlier test's
    # leftover row, not necessarily this one. Use the object _make_attempt
    # already handed back instead of re-querying for it blind.
    prior, station, question = await _make_attempt(db, attempt_no=1)
    prior.status = "complete"
    prior.validation_status = "arithmetic_slip"
    await db.commit()

    image_bytes = _valid_test_image_bytes()
    attempt_id = uuid.uuid4()
    image_path = await storage_service.save_practice_attempt_image(prior.session_id, str(attempt_id), image_bytes)
    attempt2 = PracticeAttempt(
        id=attempt_id, question_id=question.id, session_id=prior.session_id, station_id=station.id,
        attempt_no=2, input_type="image", image_path=image_path, status="processing",
    )
    db.add(attempt2)
    await db.commit()

    with patch.object(practice_engine, "extract_steps", new=AsyncMock(return_value={
             "steps": [{"text": "47+58=103", "bbox": None, "confidence": 0.95}],
             "overall_confidence": 0.95, "empty_reason": "none", "diagram_context": None,
         })), \
         patch.object(practice_service, "validate_step", new=AsyncMock(return_value={
             "validation_status": "arithmetic_slip", "error_step_index": 0, "misconception_code": None,
             "reason_code": "wrong_sum", "confidence": 0.9, "source": "cloud", "column_hint": None,
         })), \
         patch.object(practice_service, "generate_counter_question", new=AsyncMock(
             side_effect=AssertionError("counter-question should not be generated on a repeated mistake"),
         )), \
         patch.object(practice_service, "generate_hint", new=AsyncMock(return_value={"hint_text": "a real L2 hint", "source": "cloud"})), \
         patch.object(practice_service, "check_hint_leakage", new=AsyncMock(return_value=False)):
        result = await practice_service.process_attempt(attempt2.id, db)

    assert result.hint_level == 2
    assert result.hint_text == "a real L2 hint"
    assert result.counter_question is None


@pytest.mark.asyncio
async def test_counter_question_failure_falls_back_to_immediate_hint(db: AsyncSession):
    attempt, station, question = await _make_attempt(db, attempt_no=1)

    with patch.object(practice_engine, "extract_steps", new=AsyncMock(return_value={
             "steps": [{"text": "47+58=103", "bbox": None, "confidence": 0.95}],
             "overall_confidence": 0.95, "empty_reason": "none", "diagram_context": None,
         })), \
         patch.object(practice_service, "validate_step", new=AsyncMock(return_value={
             "validation_status": "arithmetic_slip", "error_step_index": 0, "misconception_code": None,
             "reason_code": "wrong_sum", "confidence": 0.9, "source": "cloud", "column_hint": None,
         })), \
         patch.object(practice_service, "generate_counter_question", new=AsyncMock(return_value={
             "counter_question": "", "source": "none",  # generation failed
         })), \
         patch.object(practice_service, "generate_hint", new=AsyncMock(return_value={"hint_text": "fallback hint", "source": "cloud"})), \
         patch.object(practice_service, "check_hint_leakage", new=AsyncMock(return_value=False)):
        result = await practice_service.process_attempt(attempt.id, db)

    assert result.counter_question is None
    assert result.hint_text == "fallback hint"
    assert result.hint_level == 1
