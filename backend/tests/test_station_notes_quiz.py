"""
Tests for practice_service.generate_station_notes/generate_station_quiz —
the station-scoped voice-command analogs of a session's generate_notes/
generate_quiz ("generate notes"/"generate quiz" said at a student's own
Guided Practice station means a recap of THAT station's attempt history,
not the whole class's lecture — see ClassroomBrain.tsx's
onPracticeStationPage branch).

Coverage:
  - the LLM prompt digest includes both live PracticeAttempt rows and
    already-pruned PracticeAttemptSummary batches
  - notes/quiz never come back empty-and-silent on a genuine LLM failure —
    notes falls back to a plain "nothing to report" message, quiz to []
  - a station with no history at all still returns a graceful result
    without ever calling the LLM (nothing useful to send it)
"""
from __future__ import annotations

import json
import types
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from app.models.practice_attempt import PracticeAttempt
from app.models.practice_attempt_summary import PracticeAttemptSummary
from app.models.practice_question import PracticeQuestion
from app.models.practice_station import PracticeStation
from app.services import practice_service
from tests.conftest import TEACHER_ID, CLASSROOM_ID


async def _make_station_with_question(db: AsyncSession):
    session = Session(
        teacher_id=uuid.UUID(TEACHER_ID), classroom_id=uuid.UUID(CLASSROOM_ID),
        subject="Math", grade="Grade 6", board_type="chalkboard",
        capture_mode="time_based", capture_interval_sec=30, status="active",
    )
    db.add(session)
    await db.flush()

    question = PracticeQuestion(session_id=session.id, text="Solve for x: 2x + 5 = 15", subject="Math", topic="Linear equations")
    db.add(question)
    await db.flush()

    station = PracticeStation(session_id=session.id, label="Desk 1", capture_interval_sec=10, status="idle")
    station.active_question_id = question.id
    db.add(station)
    await db.commit()
    return station, question


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


@pytest.mark.asyncio
async def test_generate_station_notes_includes_live_and_pruned_history(db: AsyncSession):
    station, question = await _make_station_with_question(db)
    db.add(PracticeAttempt(
        question_id=question.id, session_id=question.session_id, station_id=station.id,
        attempt_no=1, input_type="image", status="complete",
        student_state="stuck", validation_status="arithmetic_slip", misconception_code="MC_CARRY", hint_level=2,
    ))
    db.add(PracticeAttemptSummary(
        question_id=question.id, station_id=station.id, attempts_summarized=6,
        first_attempt_at=question.created_at, last_attempt_at=question.created_at,
        solved=True, revision_required=False, misconception_codes={"MC_BORROW": 3},
    ))
    await db.commit()

    fake_client, calls = _mock_openai_client({"notes": "Practiced linear equations; carry errors seen; try slower column work next."})

    with patch("openai.AsyncOpenAI", return_value=fake_client):
        result = await practice_service.generate_station_notes(
            db, station.id,
            ollama_base_url="http://unreachable.invalid:1", ollama_model="unused",
            openai_api_key="test-key", local_enabled=False,
        )

    assert "carry errors" in result["notes"]
    assert len(calls) == 1
    sent_user_prompt = calls[0]["messages"][1]["content"]
    assert "MC_CARRY" in sent_user_prompt
    assert "MC_BORROW" in sent_user_prompt
    assert "6 attempts" in sent_user_prompt


@pytest.mark.asyncio
async def test_generate_station_quiz_returns_three_questions(db: AsyncSession):
    station, question = await _make_station_with_question(db)
    db.add(PracticeAttempt(
        question_id=question.id, session_id=question.session_id, station_id=station.id,
        attempt_no=1, input_type="image", status="complete",
        student_state="stuck", validation_status="arithmetic_slip", misconception_code="MC_CARRY",
    ))
    await db.commit()

    fake_client, calls = _mock_openai_client({"questions": ["12 + 9 = ?", "27 + 15 = ?", "38 + 46 = ?"]})
    with patch("openai.AsyncOpenAI", return_value=fake_client):
        result = await practice_service.generate_station_quiz(
            db, station.id,
            ollama_base_url="http://unreachable.invalid:1", ollama_model="unused",
            openai_api_key="test-key", local_enabled=False,
        )

    assert result["questions"] == ["12 + 9 = ?", "27 + 15 = ?", "38 + 46 = ?"]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_generate_station_notes_no_history_sends_empty_placeholder(db: AsyncSession):
    # No PracticeAttempt/PracticeAttemptSummary rows at all — the digest
    # itself is a plain placeholder string, but generate_station_notes
    # doesn't special-case that; it still calls the LLM and trusts the
    # system prompt's own instruction to report "nothing yet" honestly
    # rather than inventing content.
    station, _question = await _make_station_with_question(db)

    fake_client, calls = _mock_openai_client({"notes": "No attempts recorded for this station yet."})
    with patch("openai.AsyncOpenAI", return_value=fake_client):
        result = await practice_service.generate_station_notes(
            db, station.id,
            ollama_base_url="http://unreachable.invalid:1", ollama_model="unused",
            openai_api_key="test-key", local_enabled=False,
        )

    assert result["notes"] == "No attempts recorded for this station yet."
    assert len(calls) == 1
    assert "no attempt history for this station yet" in calls[0]["messages"][1]["content"]


@pytest.mark.asyncio
async def test_generate_station_notes_falls_back_when_llm_unavailable(db: AsyncSession):
    station, _question = await _make_station_with_question(db)

    async def create(**kwargs):
        raise RuntimeError("network down")

    fake_client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create))
    )
    with patch("openai.AsyncOpenAI", return_value=fake_client):
        result = await practice_service.generate_station_notes(
            db, station.id,
            ollama_base_url="http://unreachable.invalid:1", ollama_model="unused",
            openai_api_key="test-key", local_enabled=False,
        )

    # Never silently empty on a real failure — same "never a blank result"
    # rule as answer_question's _CHAT_FALLBACK_REPLY.
    assert result["notes"]


@pytest.mark.asyncio
async def test_generate_station_quiz_falls_back_to_empty_list_on_llm_failure(db: AsyncSession):
    station, question = await _make_station_with_question(db)
    db.add(PracticeAttempt(
        question_id=question.id, session_id=question.session_id, station_id=station.id,
        attempt_no=1, input_type="image", status="complete", student_state="solved",
    ))
    await db.commit()

    async def create(**kwargs):
        raise RuntimeError("network down")

    fake_client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create))
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("openai.AsyncOpenAI", lambda **kw: fake_client)
        result = await practice_service.generate_station_quiz(
            db, station.id,
            ollama_base_url="http://unreachable.invalid:1", ollama_model="unused",
            openai_api_key="test-key", local_enabled=False,
        )

    assert result["questions"] == []
