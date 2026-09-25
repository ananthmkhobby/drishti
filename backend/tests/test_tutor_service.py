"""
Tests for practice_service.tutor_turn() — Guided Practice's Learning-mode
AI Tutor (voice + vision, the one genuinely multi-turn conversation in the
app). Mocks the vision call and whisper transcription; asserts:
  - prior conversation history is included in the prompt sent to the model
  - the system prompt never instructs the model to hand over the final answer
  - both sides of each exchange get persisted to PracticeTutorMessage
  - a missing/failed vision call falls back to a plain, honest reply rather
    than raising
"""
from __future__ import annotations

import json
import types
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from app.models.practice_question import PracticeQuestion
from app.models.practice_station import PracticeStation
from app.models.practice_tutor_message import PracticeTutorMessage
from app.services import practice_service
from tests.conftest import TEACHER_ID, CLASSROOM_ID


def _fake_settings(**overrides):
    base = dict(
        local_whisper_enabled=False,
        local_whisper_url="http://localhost:8080",
        whisper_language=None,
        openai_api_key="test-key",
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


async def _make_station(db: AsyncSession, with_question: bool = True):
    session = Session(
        teacher_id=uuid.UUID(TEACHER_ID), classroom_id=uuid.UUID(CLASSROOM_ID),
        subject="Math", grade="Grade 6", board_type="chalkboard",
        capture_mode="time_based", capture_interval_sec=30, status="active",
    )
    db.add(session)
    await db.flush()

    question = None
    if with_question:
        question = PracticeQuestion(session_id=session.id, text="Solve for x: 2x + 5 = 15", subject="Math", topic="Linear equations")
        db.add(question)
        await db.flush()

    station = PracticeStation(session_id=session.id, label="Desk 1", capture_interval_sec=10, status="idle")
    if question:
        station.active_question_id = question.id
    db.add(station)
    await db.commit()
    return station, question


def _mock_openai_client(reply_text: str):
    """Builds a fake AsyncOpenAI()-shaped object whose chat.completions.create
    returns a response with the given reply already JSON-encoded, and
    records every call it received for assertions."""
    calls: list[dict] = []

    async def create(**kwargs):
        calls.append(kwargs)
        message = types.SimpleNamespace(content=json.dumps({"reply": reply_text}))
        choice = types.SimpleNamespace(message=message)
        return types.SimpleNamespace(choices=[choice])

    fake_client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create))
    )
    return fake_client, calls


@pytest.mark.asyncio
async def test_tutor_turn_includes_history_and_persists_both_sides(db: AsyncSession):
    station, question = await _make_station(db)
    fake_client, calls = _mock_openai_client("Nice — what do you get when you subtract 5 from both sides?")

    history = [
        {"role": "student", "text": "I'm stuck on this equation"},
        {"role": "tutor", "text": "What's the first step you'd take to isolate x?"},
    ]

    with patch.object(practice_service, "whisper_transcribe", new=AsyncMock(
             return_value=types.SimpleNamespace(text="I don't know where to start")
         )), \
         patch("openai.AsyncOpenAI", return_value=fake_client):
        result = await practice_service.tutor_turn(
            db, station, question, history,
            audio_bytes=b"fake-audio", image_bytes=b"\xff\xd8\xff\xe0fake-jpeg",
            settings=_fake_settings(),
        )

    assert result["transcript"] == "I don't know where to start"
    assert "subtract 5" in result["reply"]

    # The prompt actually sent to the model includes the prior turns, not
    # just the newest message — this is the one genuinely multi-turn call
    # in the app, so losing history here would be a real regression.
    assert len(calls) == 1
    sent_messages = calls[0]["messages"]
    roles_and_text = [(m["role"], m["content"]) for m in sent_messages if isinstance(m["content"], str)]
    assert ("user", "I'm stuck on this equation") in roles_and_text
    assert ("assistant", "What's the first step you'd take to isolate x?") in roles_and_text

    # System prompt never instructs the model to hand over the answer —
    # same guardrail spirit as the existing hint/chat leakage guards.
    system_content = sent_messages[0]["content"]
    assert "never just give the final answer" in system_content.lower()

    # Both sides of the exchange got persisted (append-only log for a later
    # report — see PracticeTutorMessage's docstring).
    from sqlalchemy import select
    rows = (await db.execute(
        select(PracticeTutorMessage).where(PracticeTutorMessage.station_id == station.id)
    )).scalars().all()
    assert len(rows) == 2
    student_row = next(r for r in rows if r.role == "student")
    tutor_row = next(r for r in rows if r.role == "tutor")
    assert student_row.text == "I don't know where to start"
    assert student_row.had_image is True
    assert student_row.image_path is not None
    assert tutor_row.text == result["reply"]
    assert tutor_row.had_image is False


@pytest.mark.asyncio
async def test_tutor_turn_withholds_final_answer_on_first_turn(db: AsyncSession):
    """On the student's first message, the prompt must not contain the
    actual final answer at all — defense in depth so an eager model can't
    leak it before the student has genuinely tried, same reasoning as
    answer_question()'s own leakage guard."""
    station, question = await _make_station(db)
    question.final_answer = {"text": "x = 5"}
    await db.commit()
    await db.refresh(question)
    fake_client, calls = _mock_openai_client("What's the first step to isolate x?")

    with patch.object(practice_service, "whisper_transcribe", new=AsyncMock(
             return_value=types.SimpleNamespace(text="I'm stuck on this")
         )), \
         patch("openai.AsyncOpenAI", return_value=fake_client):
        await practice_service.tutor_turn(
            db, station, question, [], audio_bytes=b"fake-audio", image_bytes=None,
            settings=_fake_settings(),
        )

    system_content = calls[0]["messages"][0]["content"]
    assert "x = 5" not in system_content
    assert "too early to reveal" in system_content


@pytest.mark.asyncio
async def test_tutor_turn_reveals_final_answer_after_repeated_exchanges(db: AsyncSession):
    """After a couple of exchanges, the model IS handed the actual answer
    (reference-only — it still decides whether the student is actually
    asking) — this is the "give up and ask for the answer" reveal path,
    which needs the real answer available to give accurately, matching
    what Gate E/F itself would grade against."""
    station, question = await _make_station(db)
    question.final_answer = {"text": "x = 5"}
    question.expected_solution_graph = [{"label": "standard", "steps": []}]
    await db.commit()
    await db.refresh(question)
    fake_client, calls = _mock_openai_client("x = 5 — here's why: subtracting 5 from both sides gives 2x = 10, then dividing by 2. For example, if you had 2x + 5 = 15 apples...")

    history = [
        {"role": "student", "text": "I'm stuck on this equation"},
        {"role": "tutor", "text": "What's the first step you'd take to isolate x?"},
        {"role": "student", "text": "I still don't get it"},
        {"role": "tutor", "text": "Let's try it a different way — what does isolating x mean to you?"},
    ]

    with patch.object(practice_service, "whisper_transcribe", new=AsyncMock(
             return_value=types.SimpleNamespace(text="I give up, just tell me the answer")
         )), \
         patch("openai.AsyncOpenAI", return_value=fake_client):
        result = await practice_service.tutor_turn(
            db, station, question, history, audio_bytes=b"fake-audio", image_bytes=None,
            settings=_fake_settings(),
        )

    system_content = calls[0]["messages"][0]["content"]
    assert "x = 5" in system_content
    assert "authorized to give it" in system_content
    assert "x = 5" in result["reply"]


@pytest.mark.asyncio
async def test_tutor_turn_works_with_no_active_question(db: AsyncSession):
    station, _ = await _make_station(db, with_question=False)
    fake_client, calls = _mock_openai_client("Sure — what are you working on today?")

    with patch.object(practice_service, "whisper_transcribe", new=AsyncMock(
             return_value=types.SimpleNamespace(text="Can you help me with fractions")
         )), \
         patch("openai.AsyncOpenAI", return_value=fake_client):
        result = await practice_service.tutor_turn(
            db, station, None, [], audio_bytes=b"fake-audio", image_bytes=None,
            settings=_fake_settings(),
        )

    assert result["reply"] == "Sure — what are you working on today?"
    sent_messages = calls[0]["messages"]
    # No image attached this turn — the user content should be a plain
    # string, not a multi-part content list.
    assert isinstance(sent_messages[-1]["content"], str)


@pytest.mark.asyncio
async def test_tutor_turn_falls_back_gracefully_on_vision_failure(db: AsyncSession):
    station, question = await _make_station(db)

    async def broken_create(**kwargs):
        raise RuntimeError("simulated OpenAI outage")

    fake_client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=broken_create))
    )

    with patch.object(practice_service, "whisper_transcribe", new=AsyncMock(
             return_value=types.SimpleNamespace(text="What's next?")
         )), \
         patch("openai.AsyncOpenAI", return_value=fake_client):
        result = await practice_service.tutor_turn(
            db, station, question, [], audio_bytes=b"fake-audio", image_bytes=None,
            settings=_fake_settings(),
        )

    # Never raises — falls back to a plain, honest reply, same as
    # answer_question's own fallback behavior.
    assert result["reply"] == practice_service._TUTOR_FALLBACK_REPLY
    assert result["transcript"] == "What's next?"


@pytest.mark.asyncio
async def test_tutor_turn_transcribes_short_replies_not_just_long_ones(db: AsyncSession):
    """
    Regression test for the "AI Tutor keeps saying 'I didn't catch that'"
    report (2026-09-24): whisper_transcribe's own min_duration_sec defaults
    to 2.0s (tuned for long-form lecture recording), which would silently
    blank a short-but-real conversational reply ("yes", "I don't get it")
    that a VAD-stopped recording routinely produces under 2s. The tutor
    path must override this the same way the graded audio-answer path
    already does — assert the override is actually passed through, not
    just that a long clip happens to transcribe.
    """
    station, question = await _make_station(db)
    mock_transcribe = AsyncMock(return_value=types.SimpleNamespace(text="yes"))
    fake_client, _ = _mock_openai_client("Great — what's your reasoning?")

    with patch.object(practice_service, "whisper_transcribe", new=mock_transcribe), \
         patch("openai.AsyncOpenAI", return_value=fake_client):
        result = await practice_service.tutor_turn(
            db, station, question, [], audio_bytes=b"short-clip", image_bytes=None,
            settings=_fake_settings(),
        )

    assert result["transcript"] == "yes"
    assert mock_transcribe.await_args.kwargs.get("min_duration_sec") == 0.5


@pytest.mark.asyncio
async def test_tutor_turn_never_uses_local_whisper(db: AsyncSession):
    """
    Regression test for the actual root cause behind "I didn't catch that"
    firing the MAJORITY of the time (reported 2026-09-24), not just the
    min_duration_sec gap fixed earlier the same day. local_whisper_enabled
    defaults to True (config.py), and that local path is documented there
    as scoped to short voice COMMANDS specifically because whisper.cpp's
    basic /inference response has no confidence-score filtering — the AI
    Tutor's free-form conversational replies need cloud Whisper the same
    way process_attempt's own spoken-answer path already does. Assert
    transcribe_local is never even attempted, regardless of the setting —
    this must hold even with local_whisper_enabled=True, the actual
    real-world default.
    """
    station, question = await _make_station(db)
    fake_client, _ = _mock_openai_client("Let's break that down together.")
    mock_local = AsyncMock(side_effect=AssertionError("local whisper should never be called for the AI Tutor"))

    with patch("app.services.whisper_service.transcribe_local", new=mock_local), \
         patch.object(practice_service, "whisper_transcribe", new=AsyncMock(
             return_value=types.SimpleNamespace(text="I don't understand this part")
         )), \
         patch("openai.AsyncOpenAI", return_value=fake_client):
        result = await practice_service.tutor_turn(
            db, station, question, [], audio_bytes=b"fake-audio", image_bytes=None,
            settings=_fake_settings(local_whisper_enabled=True),
        )

    mock_local.assert_not_called()
    assert result["transcript"] == "I don't understand this part"


@pytest.mark.asyncio
async def test_tutor_turn_handles_blank_transcript(db: AsyncSession):
    station, question = await _make_station(db)

    with patch.object(practice_service, "whisper_transcribe", new=AsyncMock(
             return_value=types.SimpleNamespace(text="")
         )):
        result = await practice_service.tutor_turn(
            db, station, question, [], audio_bytes=b"fake-audio", image_bytes=None,
            settings=_fake_settings(),
        )

    assert result["transcript"] == ""
    assert "didn't catch that" in result["reply"].lower()
