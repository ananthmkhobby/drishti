"""
Tests for subject-specialized grading rubrics (practice_service._normalize_
subject_key / _build_validate_system_prompt / validate_step's routing) —
"correction logic" (Gates E/F) previously applied the exact same rubric to
every subject, with question.subject never even mentioned in the prompt.
Each subject now gets an addendum with the judgment criteria a specialist
in that subject would apply, layered on top of (never replacing) the
shared validation_status taxonomy every other gate/hint/review feature
depends on.

Coverage:
  - subject-string normalization handles real free-text variations across
    all five specialized subjects (math, physics, chemistry, history,
    language) plus non-English languages under the same "language" key
  - each specialized addendum is actually reachable and contains the
    subject-specific criteria it's supposed to
  - a subject with no written specialization ("Biology", None) falls back
    to the base prompt only — a real, intended outcome, not a bug
  - validate_step actually SENDS the subject-appropriate system prompt to
    the LLM call, not just that the builder function returns the right text
"""
from __future__ import annotations

import json
import types
from unittest.mock import patch

import pytest

from app.models.practice_question import PracticeQuestion
from app.services.practice_service import (
    _normalize_subject_key,
    _build_validate_system_prompt,
    _VALIDATE_SYSTEM_PROMPT,
    validate_step,
)


@pytest.mark.parametrize("raw,expected", [
    ("Math", "math"),
    ("Maths", "math"),
    ("mathematics", "math"),
    ("Grade 8 Mathematics", "math"),
    ("Physics", "physics"),
    ("physics ", "physics"),
    ("Chemistry", "chemistry"),
    ("Grade 10 Chemistry", "chemistry"),
    ("History", "history"),
    ("Social Science", "history"),
    ("Social Studies", "history"),
    ("English", "language"),
    ("English Language Arts", "language"),
    ("Hindi", "language"),
    ("Tamil", "language"),
    ("French", "language"),
    ("Grammar", "language"),
    ("Literature", "language"),
    ("Biology", "other"),
    ("Civics", "other"),
    ("Geography", "other"),
    ("", "other"),
    (None, "other"),
])
def test_normalize_subject_key(raw, expected):
    assert _normalize_subject_key(raw) == expected


def test_math_addendum_covers_the_specific_topics_requested():
    prompt = _build_validate_system_prompt("Mathematics")
    assert prompt.startswith(_VALIDATE_SYSTEM_PROMPT)
    for kw in ("ratio", "percentage", "angle", "polygon", "integral", "derivative", "lim", "matri"):
        assert kw.lower() in prompt.lower(), f"expected {kw!r} in math addendum"


def test_physics_addendum_covers_units_laws_and_sign_conventions():
    prompt = _build_validate_system_prompt("Physics")
    for kw in ("unit", "law", "sign convention", "physically"):
        assert kw.lower() in prompt.lower(), f"expected {kw!r} in physics addendum"


def test_chemistry_addendum_covers_equations_formulas_reactions():
    prompt = _build_validate_system_prompt("Chemistry")
    for kw in ("balanced", "valency", "state symbol", "reaction", "reversible", "stoichiometric"):
        assert kw.lower() in prompt.lower(), f"expected {kw!r} in chemistry addendum"


def test_history_addendum_covers_facts_causation_anachronism():
    prompt = _build_validate_system_prompt("History")
    for kw in ("factual", "cause", "anachronism", "historiographical"):
        assert kw.lower() in prompt.lower(), f"expected {kw!r} in history addendum"


def test_language_addendum_covers_grammar_punctuation_tone_and_isnt_english_only():
    prompt = _build_validate_system_prompt("Hindi")
    for kw in ("grammar", "punctuation", "spelling", "tone", "register"):
        assert kw.lower() in prompt.lower(), f"expected {kw!r} in language addendum"
    assert "none of the criteria below are English-specific" in prompt


def test_unspecialized_subject_gets_base_prompt_only():
    for subject in ("Biology", "Civics", "Geography", None, ""):
        prompt = _build_validate_system_prompt(subject)
        assert prompt == _VALIDATE_SYSTEM_PROMPT


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
async def test_validate_step_sends_subject_specific_system_prompt():
    question = PracticeQuestion(
        session_id=None, text="Name the two types of natural resources.",
        subject="Physics", answer_domain="conceptual",
    )
    fake_client, calls = _mock_openai_client({
        "validation_status": "valid_progress", "error_step_index": None,
        "misconception_code": None, "reason_code": "ok", "confidence": 80,
    })

    with patch("openai.AsyncOpenAI", return_value=fake_client):
        await validate_step(
            question, [{"text": "F = ma"}], None,
            ollama_base_url="http://unreachable.invalid:1", ollama_model="unused",
            openai_api_key="test-key", local_enabled=False,
        )

    system_prompt_sent = calls[0]["messages"][0]["content"]
    assert "SUBJECT SPECIALIZATION: Physics" in system_prompt_sent
    assert "SUBJECT SPECIALIZATION: Mathematics" not in system_prompt_sent
    assert "SUBJECT SPECIALIZATION: Chemistry" not in system_prompt_sent
    assert "SUBJECT SPECIALIZATION: History" not in system_prompt_sent
    assert "SUBJECT SPECIALIZATION: Language" not in system_prompt_sent
    # Subject is also now named in the user-content prompt, not just the
    # system prompt — previously question.subject was never mentioned at all.
    user_prompt_sent = calls[0]["messages"][1]["content"]
    assert "Subject: Physics" in user_prompt_sent


@pytest.mark.asyncio
async def test_validate_step_unspecialized_subject_sends_base_prompt_only():
    question = PracticeQuestion(
        session_id=None, text="Describe the process of photosynthesis.",
        subject="Biology", answer_domain="conceptual",
    )
    fake_client, calls = _mock_openai_client({
        "validation_status": "valid_progress", "error_step_index": None,
        "misconception_code": None, "reason_code": "ok", "confidence": 80,
    })

    with patch("openai.AsyncOpenAI", return_value=fake_client):
        await validate_step(
            question, [{"text": "Plants convert sunlight into energy"}], None,
            ollama_base_url="http://unreachable.invalid:1", ollama_model="unused",
            openai_api_key="test-key", local_enabled=False,
        )

    system_prompt_sent = calls[0]["messages"][0]["content"]
    assert system_prompt_sent == _VALIDATE_SYSTEM_PROMPT
