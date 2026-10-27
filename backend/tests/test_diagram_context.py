"""
Tests for diagram_context — a short factual description of the QUESTION's
own labeled figure (circuit, geometric diagram, graph, ...), extracted
alongside recognized_steps and threaded through to validate_step.

Why this exists: validate_step only ever sees transcribed text, never the
photo itself, so a diagram's own labeled values (a circuit's resistor
values, a triangle's angle) were invisible to grading whenever the
question's own text/final_answer/known_misconceptions didn't happen to
restate every value. Confirmed live (2026-09-30): with sparse question
metadata, grading correctly caught a wrong final answer but couldn't
diagnose WHY once nothing else in its context mentioned the value that was
actually being ignored.

Coverage:
  - extract_steps parses a real diagram_context out of the vision response
  - a null/absent diagram_context stays None, not an error
  - _build_validate_prompt includes it (labeled clearly as the QUESTION's
    figure, not the student's work) only when present
  - validate_step actually forwards it through to the real LLM call
"""
from __future__ import annotations

import json
import types
from unittest.mock import patch

import numpy as np
import pytest

from app.ocr import practice_engine
from app.models.practice_question import PracticeQuestion
from app.services.practice_service import _build_validate_prompt, validate_step


def _tiny_image():
    return np.zeros((200, 200, 3), dtype=np.uint8)


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
async def test_extract_steps_parses_diagram_context():
    fake_client, _ = _mock_openai_client({
        "steps": [{"text": "I = V/R1 = 12/4 = 3", "bbox": [10, 10, 90, 30], "confidence": 95}],
        "overall_confidence": 95, "empty_reason": "none",
        "diagram_context": "Series circuit: 12V battery, R1=4Ω, R2=2Ω",
    })
    with patch("openai.AsyncOpenAI", return_value=fake_client):
        result = await practice_engine.extract_steps(_tiny_image(), "Find I.", "test-key", subject="Physics")
    assert result["diagram_context"] == "Series circuit: 12V battery, R1=4Ω, R2=2Ω"


@pytest.mark.asyncio
async def test_extract_steps_diagram_context_defaults_to_none():
    fake_client, _ = _mock_openai_client({
        "steps": [{"text": "some step", "bbox": None, "confidence": 90}],
        "overall_confidence": 90, "empty_reason": "none",
        # no diagram_context key at all — the common case, no figure present
    })
    with patch("openai.AsyncOpenAI", return_value=fake_client):
        result = await practice_engine.extract_steps(_tiny_image(), "Some question.", "test-key")
    assert result["diagram_context"] is None


def test_build_validate_prompt_includes_diagram_context_when_present():
    question = PracticeQuestion(session_id=None, text="Find I.", subject="Physics", answer_domain="numeric")
    prompt = _build_validate_prompt(
        question, [{"text": "I = 3"}], None,
        diagram_context="Series circuit: 12V battery, R1=4Ω, R2=2Ω",
    )
    assert "Series circuit: 12V battery, R1=4Ω, R2=2Ω" in prompt
    assert "QUESTION's own figure" in prompt


def test_build_validate_prompt_omits_diagram_context_when_absent():
    question = PracticeQuestion(session_id=None, text="Find I.", subject="Physics", answer_domain="numeric")
    prompt = _build_validate_prompt(question, [{"text": "I = 3"}], None)
    assert "QUESTION's own figure" not in prompt


@pytest.mark.asyncio
async def test_validate_step_forwards_diagram_context_to_llm_call():
    question = PracticeQuestion(
        session_id=None, text="Find the current I in the circuit shown.",
        subject="Physics", answer_domain="numeric", final_answer={"text": "2 A"},
    )
    fake_client, calls = _mock_openai_client({
        "validation_status": "conceptual_misconception", "error_step_index": 0,
        "misconception_code": None, "reason_code": "ignored_series_resistor", "confidence": 90,
    })
    with patch("openai.AsyncOpenAI", return_value=fake_client):
        await validate_step(
            question, [{"text": "I = V/R1 = 12/4 = 3"}], None,
            ollama_base_url="http://unreachable.invalid:1", ollama_model="unused",
            openai_api_key="test-key", local_enabled=False,
            diagram_context="Series circuit: 12V battery, R1=4Ω, R2=2Ω",
        )
    user_prompt_sent = calls[0]["messages"][1]["content"]
    assert "R1=4Ω, R2=2Ω" in user_prompt_sent
