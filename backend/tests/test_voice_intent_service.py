"""
Tests for the deterministic voice-intent classification layer.

Coverage:
  - Canonical-example regression: every "text" -> {json} example line in
    _SYSTEM_PROMPT is parsed and asserted against _classify_deterministic()
  - Deterministic-covered intents: exact {intent, params} match expected
  - Out-of-scope intents (create_session/open_session/delete_session/
    ask_question/named-chapter start_teaching): _classify_deterministic
    must return None, proving the fallback boundary is exactly where
    intended (no false-positive over-triggering)
  - Integration wiring: classify_intent() short-circuits before any network
    client is constructed for a covered phrase
  - Hand-written edge cases per intent not otherwise pinned down by the
    prompt's own examples (ordinal normalization, seconds rounding, tab
    synonyms, the prose-only assign_question_to_station third pattern)
"""
from __future__ import annotations

import json
import re

import pytest

from app.services.voice_intent_service import (
    _SYSTEM_PROMPT,
    _classify_deterministic,
    classify_intent,
)

_EXAMPLE_RE = re.compile(r'^"(.+)"\s*->\s*(\{.*\})\s*$')

_DETERMINISTIC_INTENTS = {
    "capture_frame", "start_camera", "stop_camera", "start_recording",
    "stop_recording", "reprocess_ocr", "check_understanding", "mute_audio",
    "unmute_audio", "end_session", "download_pdf", "view_tab",
    "generate_notes", "generate_quiz", "generate_summary", "generate_experiments",
    "generate_practice_questions", "generate_homework", "generate_lesson_plan",
    "generate_class_analysis", "generate_session_report", "generate_absorption_map",
    "set_auto_capture", "approve_question", "reject_question", "create_station",
    "start_station_capture", "stop_station_capture", "assign_question_to_station",
    "welcome_begin", "welcome_take_attendance", "welcome_see_summary", "welcome_go_to_dashboard",
    "station_toggle_capture", "station_record_answer",
}

_OUT_OF_SCOPE_INTENTS = {"create_session", "open_session", "delete_session", "ask_question"}


def _extract_examples():
    cases = []
    for line in _SYSTEM_PROMPT.splitlines():
        m = _EXAMPLE_RE.match(line.strip())
        if not m:
            continue
        cases.append((m.group(1), json.loads(m.group(2))))
    return cases


_ALL_EXAMPLES = _extract_examples()
_COVERED_CASES = [(t, e) for t, e in _ALL_EXAMPLES if e["intent"] in _DETERMINISTIC_INTENTS]
_OUT_OF_SCOPE_CASES = [
    (t, e) for t, e in _ALL_EXAMPLES
    if e["intent"] in _OUT_OF_SCOPE_INTENTS
    or (e["intent"] == "start_teaching" and "chapter" in e["params"])
]


def test_examples_found():
    assert len(_ALL_EXAMPLES) > 100
    assert len(_COVERED_CASES) > 40
    assert len(_OUT_OF_SCOPE_CASES) > 10


@pytest.mark.parametrize("text,expected", _COVERED_CASES, ids=[c[0] for c in _COVERED_CASES])
def test_deterministic_matches_canonical_examples(text, expected):
    result = _classify_deterministic(text)
    assert result is not None, f"expected a deterministic hit for {text!r}, got None"
    assert result["intent"] == expected["intent"]
    assert result["params"] == expected["params"]


@pytest.mark.parametrize("text,expected", _OUT_OF_SCOPE_CASES, ids=[c[0] for c in _OUT_OF_SCOPE_CASES])
def test_deterministic_returns_none_for_out_of_scope(text, expected):
    assert _classify_deterministic(text) is None, (
        f"deterministic layer should NOT handle {text!r} (intent={expected['intent']}) "
        f"— must fall through to the LLM pipeline"
    )


@pytest.mark.asyncio
async def test_full_classify_intent_short_circuits_for_covered_phrase():
    # Unreachable Ollama URL + empty OpenAI key: if this returns fast and
    # correctly, the network path was never attempted for a covered phrase.
    result = await classify_intent(
        "Stop the camera",
        ollama_base_url="http://unreachable.invalid:1",
        ollama_model="unused",
        openai_api_key="",
        timeout_sec=1,
    )
    assert result == {"intent": "stop_camera", "params": {}, "source": "deterministic"}


@pytest.mark.asyncio
async def test_full_classify_intent_falls_through_for_out_of_scope_phrase():
    # An out-of-scope phrase must NOT be answered by the deterministic layer
    # — with no reachable model, it should end up as "unknown"/"none", not a
    # wrong deterministic guess.
    result = await classify_intent(
        "Open Newton's Laws of Motion",
        ollama_base_url="http://unreachable.invalid:1",
        ollama_model="unused",
        openai_api_key="",
        timeout_sec=1,
    )
    assert result["source"] == "none"
    assert result["intent"] == "unknown"


# --- Hand-written edge cases beyond the prompt's own examples ---

def test_ordinal_word_fourth():
    result = _classify_deterministic("Approve the fourth question")
    assert result == {"intent": "approve_question", "params": {"which": "4th"}}


def test_ordinal_word_out_of_vocabulary_falls_through():
    assert _classify_deterministic("Approve the sixth question") is None


def test_seconds_rounds_to_nearest():
    result = _classify_deterministic("auto capture every 7 seconds")
    assert result == {"intent": "set_auto_capture", "params": {"seconds": 5}}


def test_seconds_tie_break_prefers_lower():
    # |25-20| == |25-30| == 5; tie resolves to 20 (first in _VALID_SECONDS).
    result = _classify_deterministic("auto capture every 25 seconds")
    assert result == {"intent": "set_auto_capture", "params": {"seconds": 20}}


def test_view_tab_synonym_missing_concepts():
    result = _classify_deterministic("Take me to missing concepts")
    assert result == {"intent": "view_tab", "params": {"output": "missing-concepts"}}


def test_view_tab_synonym_opportunities():
    result = _classify_deterministic("Go to opportunities")
    assert result == {"intent": "view_tab", "params": {"output": "missing-concepts"}}


def test_view_tab_take_me_from_x_to_y():
    # "Take me from quiz to experiments" -> view_tab(experiments), a real
    # canonical example whose leading phrase doesn't match the plain
    # _LEADS_WITH_VIEW_VERB alternation ("take me to"), needing the
    # dedicated "take me from X to Y" pattern.
    result = _classify_deterministic("Take me from quiz to experiments")
    assert result == {"intent": "view_tab", "params": {"output": "experiments"}}


def test_view_tab_defers_to_open_session_on_grade_signal():
    # "Show me the lesson plan for my grade 5 class" is a canonical
    # open_session example (line 290) — the deterministic view_tab check
    # must NOT fire just because "lesson plan" is present.
    assert _classify_deterministic("Show me the lesson plan for my grade 5 class") is None


def test_view_tab_defers_to_open_session_on_recency_signal():
    # "Show me last week's grade 5 notes" -> open_session (line 279).
    assert _classify_deterministic("Show me last week's grade 5 notes") is None


def test_assign_question_to_station_prose_only_pattern():
    # "set station 2 to the third question" appears only in the prompt's
    # prose (not as a parseable "text" -> {json} example line).
    result = _classify_deterministic("set station 2 to the third question")
    assert result == {
        "intent": "assign_question_to_station",
        "params": {"station": "2", "which": "3rd"},
    }


def test_station_ref_allows_filler_words_before_station():
    # "Priya's PRACTICE station" — 2026-09-25 fix: the possessive-then-
    # "station" pattern used to require "station" immediately after "'s",
    # so any adjective/noun in between ("work station", "practice station")
    # made name extraction silently fail and fall through to None.
    result = _classify_deterministic("Start Priya's practice station")
    assert result == {"intent": "start_station_capture", "params": {"station": "Priya"}}


def test_open_station_and_start_not_anchored_to_start_of_phrase():
    # "Let's OPEN Arjun's work station and START" doesn't lead with
    # start/begin, so only the "open ... station ... start" search pattern
    # (not the leading-verb regex) can catch it.
    result = _classify_deterministic("Let's open Arjun's work station and start")
    assert result == {"intent": "start_station_capture", "params": {"station": "Arjun"}}


def test_open_station_without_start_still_falls_through():
    # No start/begin/go cue anywhere — should NOT be misclassified as
    # start_station_capture; must fall through to the LLM tier.
    assert _classify_deterministic("open Arjun's work station") is None
