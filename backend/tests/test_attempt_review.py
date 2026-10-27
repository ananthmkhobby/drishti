"""
Tests for practice_service.generate_attempt_review() — the on-demand
"conceptual error / perfect answer / tip" correction panel shown alongside
a finished attempt (frontend/src/app/practice-station/[stationId]/page.tsx's
AttemptResultCard). Deliberately separate from generate_hint (Gates G/H):
hints must never reveal the final answer while a student is still working;
this is the opposite — a post-hoc review that SHOULD reveal it.

Coverage:
  - a normal call returns the three expected fields, built from the
    question + student's actual recognized text + matched misconception
  - a known_misconceptions match is included in the prompt sent to the LLM
  - never empty-and-silent on an LLM failure — falls back to a plain,
    honest message rather than a blank/crashing review
"""
from __future__ import annotations

import json
import types
from unittest.mock import patch

import pytest

from app.models.practice_question import PracticeQuestion
from app.services import practice_service


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
    base = dict(
        text="Name and describe the two types of natural resources based on their distribution.",
        subject="Geography", topic="Natural resources",
        final_answer={"summary": "Universal resources (found everywhere) and localised resources (found only in specific places)."},
        known_misconceptions=[
            {"code": "MC_UNIVERSAL_VS_ACTUAL", "description": "Confuses universal/localised distribution with actual/potential availability."},
        ],
    )
    base.update(overrides)
    return PracticeQuestion(session_id=None, **base)


@pytest.mark.asyncio
async def test_generate_attempt_review_returns_structured_fields():
    question = _make_question()
    fake_client, calls = _mock_openai_client({
        "conceptual_error": "You explained actual resources instead of universal resources.",
        "perfect_answer": [
            "Universal resources: found everywhere (e.g., sunlight).",
            "Localised resources: found only in specific places (e.g., iron ore).",
        ],
        "tip": "Review distribution of resources.",
    })

    with patch("openai.AsyncOpenAI", return_value=fake_client):
        result = await practice_service.generate_attempt_review(
            question,
            "actual resource: Actual resource are resource that are currently being used and have known quantities.",
            "MC_UNIVERSAL_VS_ACTUAL",
            ollama_base_url="http://unreachable.invalid:1", ollama_model="unused",
            openai_api_key="test-key", local_enabled=False,
        )

    assert result["conceptual_error"] == "You explained actual resources instead of universal resources."
    assert len(result["perfect_answer"]) == 2
    assert "Review distribution" in result["tip"]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_generate_attempt_review_includes_matched_misconception_in_prompt():
    question = _make_question()
    fake_client, calls = _mock_openai_client({
        "conceptual_error": "x", "perfect_answer": ["a", "b"], "tip": "y",
    })

    with patch("openai.AsyncOpenAI", return_value=fake_client):
        await practice_service.generate_attempt_review(
            question, "the student's written answer", "MC_UNIVERSAL_VS_ACTUAL",
            ollama_base_url="http://unreachable.invalid:1", ollama_model="unused",
            openai_api_key="test-key", local_enabled=False,
        )

    sent_prompt = calls[0]["messages"][1]["content"]
    assert "the student's written answer" in sent_prompt
    assert "Confuses universal/localised distribution" in sent_prompt
    # Never asked to hold back the answer here — the opposite of generate_hint.
    system_prompt = calls[0]["messages"][0]["content"]
    assert "reveal the correct answer" in system_prompt


@pytest.mark.asyncio
async def test_generate_attempt_review_falls_back_when_llm_unavailable():
    question = _make_question()

    async def create(**kwargs):
        raise RuntimeError("network down")

    fake_client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create))
    )
    with patch("openai.AsyncOpenAI", return_value=fake_client):
        result = await practice_service.generate_attempt_review(
            question, "some answer", None,
            ollama_base_url="http://unreachable.invalid:1", ollama_model="unused",
            openai_api_key="test-key", local_enabled=False,
        )

    assert result["conceptual_error"]
    assert result["perfect_answer"] == []


@pytest.mark.asyncio
async def test_generate_attempt_review_no_misconception_match_still_works():
    # misconception_code doesn't match anything in known_misconceptions (or
    # the question has none at all) — should still build a usable prompt,
    # not crash on a None lookup.
    question = _make_question(known_misconceptions=None)
    fake_client, calls = _mock_openai_client({
        "conceptual_error": "x", "perfect_answer": ["a"], "tip": "y",
    })

    with patch("openai.AsyncOpenAI", return_value=fake_client):
        result = await practice_service.generate_attempt_review(
            question, "some answer", "MC_SOMETHING_NOT_LISTED",
            ollama_base_url="http://unreachable.invalid:1", ollama_model="unused",
            openai_api_key="test-key", local_enabled=False,
        )

    assert result["perfect_answer"] == ["a"]
