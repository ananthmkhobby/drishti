"""
Tests for subject-aware step extraction (practice_engine.extract_steps) —
the OCR/vision layer that transcribes a photographed notebook page.
Previously used one generic prompt for every subject; a misread symbol
here (a chemistry subscript vs superscript, a matrix's layout, a name in a
history answer) defeats even a perfect validation rubric downstream, so
extraction now gets the same subject-specialization treatment Gates E/F
already have (see test_subject_rubric.py) — a different addendum, about
what to pay attention to while TRANSCRIBING, not while judging correctness.

Coverage:
  - extract_steps actually sends the subject-appropriate extraction
    addendum to the vision call, not just that a builder returns the
    right text
  - an unrecognized/absent subject sends the base extraction prompt only
  - _normalize_subject_key is now shared between practice_engine (here)
    and practice_service (test_subject_rubric.py) — imported, not
    duplicated, so the two can't drift apart
"""
from __future__ import annotations

import json
import types
from unittest.mock import patch

import numpy as np
import pytest

from app.ocr import practice_engine
from app.services.practice_service import _normalize_subject_key as _normalize_subject_key_reexported


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


def _sent_prompt_text(calls) -> str:
    # extract_steps sends multi-part content (text + image_url), unlike the
    # plain-string prompts elsewhere in this app.
    return calls[0]["messages"][0]["content"][0]["text"]


@pytest.mark.asyncio
async def test_extract_steps_sends_chemistry_addendum():
    fake_client, calls = _mock_openai_client({
        "steps": [], "overall_confidence": 0, "empty_reason": "blank",
    })
    with patch("openai.AsyncOpenAI", return_value=fake_client):
        await practice_engine.extract_steps(
            _tiny_image(), "Balance: H2 + O2 -> H2O", "test-key", subject="Chemistry",
        )
    prompt = _sent_prompt_text(calls)
    assert "Chemistry-specific" in prompt
    assert "subscript atom count" in prompt.lower() or "SUBSCRIPT atom count" in prompt
    assert "Physics-specific" not in prompt
    assert "Math-specific" not in prompt


@pytest.mark.asyncio
async def test_extract_steps_sends_language_addendum():
    fake_client, calls = _mock_openai_client({
        "steps": [], "overall_confidence": 0, "empty_reason": "blank",
    })
    with patch("openai.AsyncOpenAI", return_value=fake_client):
        await practice_engine.extract_steps(
            _tiny_image(), "Write a short paragraph about your weekend.", "test-key", subject="Hindi",
        )
    prompt = _sent_prompt_text(calls)
    assert "Language-specific" in prompt
    assert "do NOT auto-correct" in prompt or "do not auto-correct" in prompt.lower()


@pytest.mark.asyncio
async def test_extract_steps_unspecialized_subject_sends_base_prompt():
    fake_client, calls = _mock_openai_client({
        "steps": [], "overall_confidence": 0, "empty_reason": "blank",
    })
    with patch("openai.AsyncOpenAI", return_value=fake_client):
        await practice_engine.extract_steps(
            _tiny_image(), "Describe the water cycle.", "test-key", subject="Biology",
        )
    prompt = _sent_prompt_text(calls)
    for marker in ("Math-specific", "Physics-specific", "Chemistry-specific", "History-specific", "Language-specific"):
        assert marker not in prompt


@pytest.mark.asyncio
async def test_extract_steps_no_subject_sends_base_prompt():
    fake_client, calls = _mock_openai_client({
        "steps": [], "overall_confidence": 0, "empty_reason": "blank",
    })
    with patch("openai.AsyncOpenAI", return_value=fake_client):
        await practice_engine.extract_steps(_tiny_image(), "Some question.", "test-key")
    prompt = _sent_prompt_text(calls)
    for marker in ("Math-specific", "Physics-specific", "Chemistry-specific", "History-specific", "Language-specific"):
        assert marker not in prompt


def test_normalize_subject_key_shared_not_duplicated():
    # Same function object, imported (not copy-pasted) into
    # practice_service — proves the two can't silently drift apart.
    assert practice_engine._normalize_subject_key is _normalize_subject_key_reexported
