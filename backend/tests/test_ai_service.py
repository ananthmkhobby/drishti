"""
Tests for the AI generation pipeline.

Coverage:
  Parser unit tests (response_parser.py)
    - Each output type: happy path, code-fence stripping, refusal, invalid schema
  Prompt builder smoke tests
    - All 9 builders return PromptPair with non-empty system + user
  Orchestration tests (ai_service.py)
    - Placeholder path (no API key)
    - Real path mocked at call_openai level
    - Inter-step dependencies (bloom uses quiz, visual_cards uses notes)
    - Per-output DB persistence (quiz_questions, missing_concepts, experiment_suggestions)
    - Classroom memory update
    - Partial / failed outputs stored correctly
  HTTP integration tests (POST /sessions/{id}/generate, GET /sessions/{id}/outputs)
"""

from __future__ import annotations

import io
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from tests.conftest import TEACHER_ID, CLASSROOM_ID
from app.models.ai_output import AIOutput
from app.models.classroom_memory import ClassroomMemory
from app.models.experiment_suggestion import ExperimentSuggestion
from app.models.missing_concept import MissingConcept
from app.models.quiz_question import QuizQuestion


# ---------------------------------------------------------------------------
# Parser unit tests
# ---------------------------------------------------------------------------

class TestParseNotes:
    def test_valid_markdown(self):
        from app.ai.response_parser import parse_notes
        md = (
            "# Newton's Laws of Motion\n\n"
            "## First Law\nAn object at rest stays at rest unless acted upon by a net force.\n\n"
            "## Second Law\nForce equals mass times acceleration: F = ma.\n\n"
            "## Third Law\nEvery action has an equal and opposite reaction."
        )
        result = parse_notes(md)
        assert result["markdown"] == md

    def test_strips_leading_trailing_whitespace(self):
        from app.ai.response_parser import parse_notes
        md = (
            "\n\n# Title of Lesson\n\n"
            "## Section One\nContent here that is long enough to satisfy the minimum length check.\n\n"
        )
        result = parse_notes(md)
        assert result["markdown"].startswith("# Title")

    def test_too_short_raises(self):
        from app.ai.response_parser import parse_notes, ParseError
        with pytest.raises(ParseError, match="too short"):
            parse_notes("# Hi\n\nShort")

    def test_no_heading_raises(self):
        from app.ai.response_parser import parse_notes, ParseError
        with pytest.raises(ParseError, match="heading"):
            parse_notes("A" * 150)  # long but no #

    def test_refusal_raises(self):
        from app.ai.response_parser import parse_notes, RefusalError
        with pytest.raises(RefusalError):
            parse_notes("I cannot generate notes for this content as it is unclear.")


class TestParseSummary:
    def test_valid(self):
        from app.ai.response_parser import parse_summary
        text = "Today we learned about Newton's Laws of Motion. " \
               "The first law states that objects at rest stay at rest. " \
               "The second law relates force, mass, and acceleration."
        result = parse_summary(text)
        assert result["text"] == text

    def test_too_short_raises(self):
        from app.ai.response_parser import parse_summary, ParseError
        with pytest.raises(ParseError, match="too short"):
            parse_summary("Short.")

    def test_refusal_raises(self):
        from app.ai.response_parser import parse_summary, RefusalError
        with pytest.raises(RefusalError):
            parse_summary("I'm unable to generate a summary from this content.")


class TestParseQuiz:
    def _valid_questions(self):
        return [
            {
                "type": "mcq",
                "text": "What is Newton's Second Law?",
                "options": ["F=ma", "F=mv", "F=mg", "F=ma²"],
                "correct": 0,
                "bloom_level": "understand",
                "topic": "Newton's Laws",
                "skill_tag": "recall",
            },
            {
                "type": "mcq",
                "text": "Which unit measures force?",
                "options": ["Newton", "Joule", "Watt", "Pascal"],
                "correct": 0,
                "bloom_level": "remember",
                "topic": "Units",
                "skill_tag": "identification",
            },
            {
                "type": "mcq",
                "text": "If mass doubles and force is constant, acceleration...",
                "options": ["doubles", "halves", "stays same", "triples"],
                "correct": 1,
                "bloom_level": "apply",
                "topic": "Newton's Laws",
                "skill_tag": "calculation",
            },
            {
                "type": "mcq",
                "text": "What is inertia?",
                "options": [
                    "Resistance to change in motion",
                    "Rate of change of velocity",
                    "Product of mass and velocity",
                    "Force per unit area",
                ],
                "correct": 0,
                "bloom_level": "remember",
                "topic": "Newton's First Law",
                "skill_tag": "definition",
            },
            {
                "type": "mcq",
                "text": "A 5 kg object accelerates at 3 m/s². The net force is?",
                "options": ["15 N", "1.67 N", "8 N", "2 N"],
                "correct": 0,
                "bloom_level": "apply",
                "topic": "F=ma",
                "skill_tag": "calculation",
            },
            {
                "type": "true_false",
                "text": "Acceleration is directly proportional to force.",
                "correct": True,
                "bloom_level": "remember",
                "topic": "Newton's Second Law",
                "skill_tag": "recall",
            },
            {
                "type": "true_false",
                "text": "Mass and weight are the same quantity.",
                "correct": False,
                "bloom_level": "understand",
                "topic": "Mass vs Weight",
                "skill_tag": "distinction",
            },
            {
                "type": "true_false",
                "text": "Newton's Third Law states that every action has an equal reaction.",
                "correct": True,
                "bloom_level": "remember",
                "topic": "Newton's Third Law",
                "skill_tag": "recall",
            },
        ]

    def test_valid_json(self):
        from app.ai.response_parser import parse_quiz
        raw = json.dumps(self._valid_questions())
        result = parse_quiz(raw)
        assert len(result) == 8
        assert result[0]["type"] == "mcq"
        assert result[5]["type"] == "true_false"

    def test_strips_code_fence(self):
        from app.ai.response_parser import parse_quiz
        raw = "```json\n" + json.dumps(self._valid_questions()) + "\n```"
        result = parse_quiz(raw)
        assert len(result) == 8

    def test_strips_plain_fence(self):
        from app.ai.response_parser import parse_quiz
        raw = "```\n" + json.dumps(self._valid_questions()) + "\n```"
        result = parse_quiz(raw)
        assert len(result) == 8

    def test_coerces_string_true_false(self):
        from app.ai.response_parser import parse_quiz
        questions = self._valid_questions()
        questions[5]["correct"] = "true"   # string instead of bool
        questions[6]["correct"] = "false"
        result = parse_quiz(json.dumps(questions))
        assert result[5]["correct"] is True
        assert result[6]["correct"] is False

    def test_invalid_json_raises(self):
        from app.ai.response_parser import parse_quiz, ParseError
        with pytest.raises(ParseError, match="JSON decode"):
            parse_quiz("not json at all")

    def test_empty_array_raises(self):
        from app.ai.response_parser import parse_quiz, ParseError
        with pytest.raises(ParseError, match="empty"):
            parse_quiz("[]")

    def test_not_array_raises(self):
        from app.ai.response_parser import parse_quiz, ParseError
        with pytest.raises(ParseError, match="array"):
            parse_quiz('{"questions": []}')

    def test_missing_type_raises(self):
        from app.ai.response_parser import parse_quiz, ParseError
        questions = self._valid_questions()
        del questions[0]["type"]
        with pytest.raises(ParseError):
            parse_quiz(json.dumps(questions))

    def test_invalid_type_raises(self):
        from app.ai.response_parser import parse_quiz, ParseError
        questions = self._valid_questions()
        questions[0]["type"] = "short_answer"
        with pytest.raises(ParseError, match="Invalid type"):
            parse_quiz(json.dumps(questions))

    def test_mcq_wrong_options_count_raises(self):
        from app.ai.response_parser import parse_quiz, ParseError
        questions = self._valid_questions()
        questions[0]["options"] = ["A", "B"]  # only 2
        with pytest.raises(ParseError, match="exactly 4 options"):
            parse_quiz(json.dumps(questions))

    def test_mcq_out_of_range_correct_raises(self):
        from app.ai.response_parser import parse_quiz, ParseError
        questions = self._valid_questions()
        questions[0]["correct"] = 5
        with pytest.raises(ParseError, match="int 0–3"):
            parse_quiz(json.dumps(questions))

    def test_no_mcq_raises(self):
        from app.ai.response_parser import parse_quiz, ParseError
        # Only T/F questions
        tf_only = [
            {
                "type": "true_false",
                "text": "Q?",
                "correct": True,
                "bloom_level": "remember",
                "topic": "T",
                "skill_tag": "recall",
            }
        ] * 3
        with pytest.raises(ParseError, match="MCQ"):
            parse_quiz(json.dumps(tf_only))

    def test_no_true_false_raises(self):
        from app.ai.response_parser import parse_quiz, ParseError
        # Only MCQ
        mcq_only = [
            {
                "type": "mcq",
                "text": "Q?",
                "options": ["A", "B", "C", "D"],
                "correct": 0,
                "bloom_level": "remember",
                "topic": "T",
                "skill_tag": "recall",
            }
        ] * 5
        with pytest.raises(ParseError, match="True/False"):
            parse_quiz(json.dumps(mcq_only))

    def test_refusal_raises(self):
        from app.ai.response_parser import parse_quiz, RefusalError
        with pytest.raises(RefusalError):
            parse_quiz("I cannot generate quiz questions for this topic.")

    def test_coerces_invalid_bloom_level(self):
        from app.ai.response_parser import parse_quiz
        questions = self._valid_questions()
        questions[0]["bloom_level"] = "memorise"  # invalid — coerced to "remember"
        result = parse_quiz(json.dumps(questions))
        assert result[0]["bloom_level"] == "remember"

    def test_salvages_json_with_trailing_text(self):
        """Parser should extract the JSON array even if there's text after it."""
        from app.ai.response_parser import parse_quiz
        raw = json.dumps(self._valid_questions()) + "\n\nHope this helps!"
        result = parse_quiz(raw)
        assert len(result) == 8


class TestParseBloom:
    def _valid_bloom(self):
        return {
            "counts": {
                "remember": 3, "understand": 2, "apply": 1,
                "analyze": 1, "evaluate": 0, "create": 0,
            },
            "lower_order_dominant": True,
            "suggestions": [
                "Design an experiment to test Newton's Second Law.",
                "Evaluate how friction affects the motion of an object.",
            ],
        }

    def test_valid(self):
        from app.ai.response_parser import parse_bloom
        result = parse_bloom(json.dumps(self._valid_bloom()))
        assert result["counts"]["remember"] == 3
        assert result["lower_order_dominant"] is True
        assert len(result["suggestions"]) == 2

    def test_strips_fence(self):
        from app.ai.response_parser import parse_bloom
        raw = "```json\n" + json.dumps(self._valid_bloom()) + "\n```"
        result = parse_bloom(raw)
        assert "counts" in result

    def test_fills_missing_bloom_keys(self):
        """Counts missing some bloom keys → filled with 0."""
        from app.ai.response_parser import parse_bloom
        data = {"counts": {"remember": 2}, "lower_order_dominant": False, "suggestions": []}
        result = parse_bloom(json.dumps(data))
        assert result["counts"]["analyze"] == 0
        assert result["counts"]["create"] == 0

    def test_missing_required_key_raises(self):
        from app.ai.response_parser import parse_bloom, ParseError
        data = self._valid_bloom()
        del data["counts"]
        with pytest.raises(ParseError, match="Missing required keys"):
            parse_bloom(json.dumps(data))

    def test_not_object_raises(self):
        from app.ai.response_parser import parse_bloom, ParseError
        with pytest.raises(ParseError, match="object"):
            parse_bloom("[1, 2, 3]")

    def test_refusal_raises(self):
        from app.ai.response_parser import parse_bloom, RefusalError
        with pytest.raises(RefusalError):
            parse_bloom("As an AI, I cannot analyse bloom taxonomy from this content.")


class TestParseMissingConcepts:
    def _valid(self):
        return {
            "prerequisite_gaps": ["Velocity and speed", "Newton's First Law basics"],
            "incomplete_topics": ["Friction types"],
            "suggested_next": "Friction — types and applications",
        }

    def test_valid(self):
        from app.ai.response_parser import parse_missing_concepts
        result = parse_missing_concepts(json.dumps(self._valid()))
        assert "Friction types" in result["incomplete_topics"]
        assert result["suggested_next"] == "Friction — types and applications"

    def test_strips_fence(self):
        from app.ai.response_parser import parse_missing_concepts
        raw = "```json\n" + json.dumps(self._valid()) + "\n```"
        result = parse_missing_concepts(raw)
        assert "prerequisite_gaps" in result

    def test_missing_key_raises(self):
        from app.ai.response_parser import parse_missing_concepts, ParseError
        data = self._valid()
        del data["suggested_next"]
        with pytest.raises(ParseError, match="Missing required keys"):
            parse_missing_concepts(json.dumps(data))

    def test_empty_lists_ok(self):
        from app.ai.response_parser import parse_missing_concepts
        data = {"prerequisite_gaps": [], "incomplete_topics": [], "suggested_next": "Optics"}
        result = parse_missing_concepts(json.dumps(data))
        assert result["prerequisite_gaps"] == []


class TestParseExperiments:
    def _valid(self):
        return [
            {
                "title": "Paper Bridge",
                "topic": "Structural strength",
                "difficulty": "easy",
                "description": "Build a bridge using paper and see how much weight it can hold.",
                "materials": ["A4 paper", "Coins", "Ruler"],
                "steps": ["Fold paper into an arch", "Place between two books", "Add coins"],
                "expected_outcome": "Students observe compression and tension forces.",
                "safety_note": "No sharp objects required.",
                "xperimentor_kit": None,
            }
        ]

    def test_valid(self):
        from app.ai.response_parser import parse_experiments
        result = parse_experiments(json.dumps(self._valid()))
        assert result[0]["title"] == "Paper Bridge"
        assert result[0]["difficulty"] == "easy"

    def test_strips_fence(self):
        from app.ai.response_parser import parse_experiments
        raw = "```json\n" + json.dumps(self._valid()) + "\n```"
        result = parse_experiments(raw)
        assert len(result) == 1

    def test_coerces_invalid_difficulty(self):
        from app.ai.response_parser import parse_experiments
        data = self._valid()
        data[0]["difficulty"] = "very_easy"  # invalid
        result = parse_experiments(json.dumps(data))
        assert result[0]["difficulty"] == "medium"

    def test_empty_array_raises(self):
        from app.ai.response_parser import parse_experiments, ParseError
        with pytest.raises(ParseError, match="empty"):
            parse_experiments("[]")

    def test_missing_title_raises(self):
        from app.ai.response_parser import parse_experiments, ParseError
        data = [{"description": "no title here"}]
        with pytest.raises(ParseError, match="title"):
            parse_experiments(json.dumps(data))

    def test_defaults_populated(self):
        """Minimal experiment — missing optional fields get defaults."""
        from app.ai.response_parser import parse_experiments
        data = [{"title": "Simple Experiment", "description": "Do something."}]
        result = parse_experiments(json.dumps(data))
        assert result[0]["materials"] == []
        assert result[0]["steps"] == []
        assert result[0]["xperimentor_kit"] is None


class TestParseHomework:
    def _valid(self):
        return [
            {
                "task": "Write 5 examples of Newton's Second Law from daily life.",
                "type": "explore",
                "bloom_level": "apply",
                "estimated_minutes": 20,
                "topic": "Newton's Laws",
            },
            {
                "task": "Memorise the three laws and write them from memory.",
                "type": "practice",
                "bloom_level": "remember",
                "estimated_minutes": 10,
                "topic": "Newton's Laws",
            },
        ]

    def test_valid(self):
        from app.ai.response_parser import parse_homework
        result = parse_homework(json.dumps(self._valid()))
        assert len(result) == 2
        assert result[0]["type"] == "explore"

    def test_strips_fence(self):
        from app.ai.response_parser import parse_homework
        raw = "```json\n" + json.dumps(self._valid()) + "\n```"
        result = parse_homework(raw)
        assert len(result) == 2

    def test_coerces_invalid_type(self):
        from app.ai.response_parser import parse_homework
        data = self._valid()
        data[0]["type"] = "worksheet"  # not in enum
        result = parse_homework(json.dumps(data))
        assert result[0]["type"] == "practice"

    def test_empty_raises(self):
        from app.ai.response_parser import parse_homework, ParseError
        with pytest.raises(ParseError, match="empty"):
            parse_homework("[]")

    def test_missing_task_raises(self):
        from app.ai.response_parser import parse_homework, ParseError
        with pytest.raises(ParseError, match="task"):
            parse_homework(json.dumps([{"type": "practice"}]))

    def test_refusal_raises(self):
        from app.ai.response_parser import parse_homework, RefusalError
        with pytest.raises(RefusalError):
            parse_homework("I cannot provide homework suggestions for this topic.")


class TestParseAnalogies:
    def _valid(self):
        return [
            {
                "concept": "Inertia",
                "analogy": "Like a cricket ball that keeps rolling on a flat pitch.",
                "explanation": "Once the ball is moving, it continues unless something stops it.",
            },
        ]

    def test_valid(self):
        from app.ai.response_parser import parse_analogies
        result = parse_analogies(json.dumps(self._valid()))
        assert result[0]["concept"] == "Inertia"
        assert result[0]["explanation"] != ""

    def test_strips_fence(self):
        from app.ai.response_parser import parse_analogies
        raw = "```json\n" + json.dumps(self._valid()) + "\n```"
        result = parse_analogies(raw)
        assert len(result) == 1

    def test_missing_analogy_raises(self):
        from app.ai.response_parser import parse_analogies, ParseError
        with pytest.raises(ParseError, match="analogy"):
            parse_analogies(json.dumps([{"concept": "Inertia"}]))

    def test_empty_raises(self):
        from app.ai.response_parser import parse_analogies, ParseError
        with pytest.raises(ParseError, match="empty"):
            parse_analogies("[]")

    def test_refusal_raises(self):
        from app.ai.response_parser import parse_analogies, RefusalError
        with pytest.raises(RefusalError):
            parse_analogies("As an AI language model, I cannot create analogies.")


# ---------------------------------------------------------------------------
# Prompt builder smoke tests
# ---------------------------------------------------------------------------

class TestPromptBuilders:
    """All builders must return PromptPair with non-empty system and user strings."""

    OCR = "Force equals mass times acceleration. F = ma. Newton's Second Law of Motion."

    def test_notes(self):
        from app.ai.prompt_builder import build_notes_prompt
        p = build_notes_prompt(self.OCR, "Physics", "Grade 9", "chalkboard")
        assert p.system and "Physics" in p.system
        assert "# heading" in p.user
        assert self.OCR in p.user

    def test_notes_with_topic_hint(self):
        from app.ai.prompt_builder import build_notes_prompt
        p = build_notes_prompt(self.OCR, "Physics", "Grade 9", "chalkboard", topic="Newton's Laws")
        assert "Newton's Laws" in p.user

    def test_summary(self):
        from app.ai.prompt_builder import build_summary_prompt
        p = build_summary_prompt(self.OCR, "Physics", "Grade 9", "chalkboard")
        assert "3–5 sentence" in p.user

    def test_quiz(self):
        from app.ai.prompt_builder import build_quiz_prompt
        p = build_quiz_prompt(self.OCR, "Physics", "Grade 9", "chalkboard")
        assert "5 MCQ" in p.user
        assert "3 True/False" in p.user
        assert "skill_tag" in p.user

    def test_quiz_strict_prefix(self):
        from app.ai.prompt_builder import build_quiz_prompt
        p = build_quiz_prompt(self.OCR, "Physics", "Grade 9", "chalkboard", strict=True)
        assert "CRITICAL" in p.user

    def test_bloom(self):
        from app.ai.prompt_builder import build_bloom_prompt
        quiz_json = '[{"type":"mcq","bloom_level":"remember"}]'
        p = build_bloom_prompt(quiz_json, "Physics", "Grade 9", "chalkboard")
        assert "Bloom" in p.user
        assert "lower_order_dominant" in p.user

    def test_missing_concepts(self):
        from app.ai.prompt_builder import build_missing_concepts_prompt
        p = build_missing_concepts_prompt(
            "Newton's Laws", "Velocity", "Physics", "Grade 9", "chalkboard"
        )
        assert "prerequisite" in p.user.lower()
        assert "suggested_next" in p.user

    def test_experiments(self):
        from app.ai.prompt_builder import build_experiments_prompt
        p = build_experiments_prompt(
            "Newton's Laws", "Physics", "Grade 9", "chalkboard"
        )
        assert "Xperimentor" in p.user
        assert "electricity" in p.user

    def test_visual_cards(self):
        from app.ai.prompt_builder import build_visual_cards_prompt
        p = build_visual_cards_prompt(
            "# Title\n## Section\nContent", "Physics", "Grade 9", "chalkboard"
        )
        assert "flash card" in p.user.lower() or "concept card" in p.user.lower()

    def test_homework(self):
        from app.ai.prompt_builder import build_homework_prompt
        p = build_homework_prompt(self.OCR, "Physics", "Grade 9", "chalkboard")
        assert "homework" in p.user.lower() or "task" in p.user.lower()
        assert "bloom" in p.user.lower()

    def test_analogies(self):
        from app.ai.prompt_builder import build_analogies_prompt
        p = build_analogies_prompt(self.OCR, "Physics", "Grade 9", "chalkboard")
        assert "India" in p.user
        assert "analogy" in p.user.lower() or "analogi" in p.user.lower()

    def test_all_builders_have_grade_in_system(self):
        """Grade must appear in the system message for every builder."""
        import app.ai.prompt_builder as pb
        builders = [
            pb.build_notes_prompt(self.OCR, "Physics", "Grade 9", "chalkboard"),
            pb.build_summary_prompt(self.OCR, "Physics", "Grade 9", "chalkboard"),
            pb.build_quiz_prompt(self.OCR, "Physics", "Grade 9", "chalkboard"),
            pb.build_bloom_prompt("[]", "Physics", "Grade 9", "chalkboard"),
            pb.build_missing_concepts_prompt("T", "M", "Physics", "Grade 9", "chalkboard"),
            pb.build_experiments_prompt("T", "Physics", "Grade 9", "chalkboard"),
            pb.build_visual_cards_prompt("# H\nContent here.", "Physics", "Grade 9", "chalkboard"),
            pb.build_homework_prompt(self.OCR, "Physics", "Grade 9", "chalkboard"),
            pb.build_analogies_prompt(self.OCR, "Physics", "Grade 9", "chalkboard"),
        ]
        for p in builders:
            assert "Grade 9" in p.system, f"Grade missing in system: {p.system[:80]}"


# ---------------------------------------------------------------------------
# ai_service helpers
# ---------------------------------------------------------------------------

class TestTruncateToTokens:
    def test_short_text_not_truncated(self):
        from app.services.ai_service import _truncate_to_tokens
        text = "Hello world"
        result, was = _truncate_to_tokens(text, 1000)
        assert result == text
        assert was is False

    def test_long_text_truncated(self):
        from app.services.ai_service import _truncate_to_tokens
        text = "A" * 20000
        result, was = _truncate_to_tokens(text, 1000)  # max 4000 chars
        assert was is True
        assert "[OCR text truncated" in result
        assert len(result) <= 4050  # 4000 chars + short suffix

    def test_snaps_to_sentence_boundary(self):
        from app.services.ai_service import _truncate_to_tokens
        # Build text with a sentence boundary inside the truncation zone
        before = "Newton said F equals ma. " * 200  # ~5000 chars
        result, was = _truncate_to_tokens(before, 1000)
        assert was is True
        # Should end before the truncation note at a '.'
        without_note = result.replace("\n[OCR text truncated for token budget]", "")
        assert without_note.endswith(".")


class TestExtractTopics:
    def test_extracts_headings(self):
        from app.services.ai_service import _extract_topics
        md = "# Newton's Laws\n\n## First Law\nContent\n\n## Second Law\nContent"
        result = _extract_topics(md)
        assert "Newton's Laws" in result
        assert "First Law" in result

    def test_fallback_to_first_chars(self):
        from app.services.ai_service import _extract_topics
        plain = "No headings here. Just plain text about physics."
        result = _extract_topics(plain)
        assert "physics" in result.lower()


# ---------------------------------------------------------------------------
# Orchestration: placeholder path (no API key)
# ---------------------------------------------------------------------------

@pytest.fixture
async def session_id(client, db):
    """Create a completed session and return its UUID."""
    resp = await client.post(
        "/v1/sessions",
        json={
            "teacher_id": TEACHER_ID,
            "classroom_id": str(CLASSROOM_ID),
            "subject": "Physics",
            "grade": "Grade 9",
            "board_type": "chalkboard",
            "capture_mode": "time_based",
            "capture_interval_sec": 30,
        },
    )
    assert resp.status_code == 201
    sid = resp.json()["session_id"]
    # Mark session completed
    await client.patch(f"/v1/sessions/{sid}", json={"status": "completed"})
    return sid


@pytest.mark.asyncio
async def test_placeholder_generation_no_api_key(client, db, session_id):
    """When OPENAI_API_KEY is empty, POST /generate returns 202 and outputs are ready."""
    resp = await client.post(
        f"/v1/sessions/{session_id}/generate",
        json={"outputs": ["notes", "summary", "quiz"]},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "queued"
    assert "job_id" in data

    # Allow background task to complete (httpx ASGI runs it synchronously in tests)
    import asyncio; await asyncio.sleep(0.1)

    outputs_resp = await client.get(f"/v1/sessions/{session_id}/outputs")
    assert outputs_resp.status_code == 200
    outputs = outputs_resp.json()["outputs"]
    assert outputs["notes"]["status"] == "ready"
    assert outputs["summary"]["status"] == "ready"
    assert outputs["quiz"]["status"] == "ready"


@pytest.mark.asyncio
async def test_placeholder_quiz_questions_persisted(client, db, session_id):
    """Placeholder quiz must insert rows into quiz_questions table."""
    resp = await client.post(
        f"/v1/sessions/{session_id}/generate",
        json={"outputs": ["quiz"]},
    )
    assert resp.status_code == 202
    import asyncio; await asyncio.sleep(0.1)

    quiz_resp = await client.get(f"/v1/sessions/{session_id}/outputs/quiz")
    assert quiz_resp.status_code == 200
    questions = quiz_resp.json()["questions"]
    assert len(questions) > 0
    # All questions must have bloom_level
    for q in questions:
        assert q["bloom_level"] in {
            "remember", "understand", "apply", "analyze", "evaluate", "create"
        }


@pytest.mark.asyncio
async def test_generate_session_not_found(client, db):
    fake_id = uuid.uuid4()
    resp = await client.post(
        f"/v1/sessions/{fake_id}/generate",
        json={"outputs": ["notes"]},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_generate_invalid_output_type(client, db, session_id):
    resp = await client.post(
        f"/v1/sessions/{session_id}/generate",
        json={"outputs": ["invalid_type"]},
    )
    assert resp.status_code == 422  # Pydantic validation rejects unknown type


@pytest.mark.asyncio
async def test_all_default_output_types(client, db, session_id):
    """Trigger with default output list — all types should end up in the DB."""
    resp = await client.post(
        f"/v1/sessions/{session_id}/generate",
        json={},  # uses default output list
    )
    assert resp.status_code == 202
    import asyncio; await asyncio.sleep(0.1)

    outputs_resp = await client.get(f"/v1/sessions/{session_id}/outputs")
    assert outputs_resp.status_code == 200
    outputs = outputs_resp.json()["outputs"]
    # Default list = notes, summary, quiz, bloom, missing_concepts, experiments, homework, analogies
    for otype in ("notes", "summary", "quiz", "bloom", "missing_concepts",
                  "experiments", "homework", "analogies"):
        assert otype in outputs, f"Missing output type: {otype}"
        assert outputs[otype]["status"] == "ready"


@pytest.mark.asyncio
async def test_idempotent_generation(client, db, session_id):
    """Calling generate twice must not duplicate rows (upsert behaviour)."""
    for _ in range(2):
        resp = await client.post(
            f"/v1/sessions/{session_id}/generate",
            json={"outputs": ["summary"]},
        )
        assert resp.status_code == 202
        import asyncio; await asyncio.sleep(0.1)

    from sqlalchemy import select, func
    count = (
        await db.execute(
            select(func.count()).where(
                AIOutput.session_id == uuid.UUID(session_id),
                AIOutput.output_type == "summary",
            )
        )
    ).scalar()
    assert count == 1


# ---------------------------------------------------------------------------
# Orchestration: real generation path (OpenAI mocked)
# ---------------------------------------------------------------------------

def _make_valid_quiz_json() -> str:
    questions = [
        {
            "type": "mcq",
            "text": f"MCQ question {i}?",
            "options": ["A", "B", "C", "D"],
            "correct": 0,
            "bloom_level": "remember",
            "topic": "Newton",
            "skill_tag": "recall",
        }
        for i in range(5)
    ] + [
        {
            "type": "true_false",
            "text": f"T/F question {i}?",
            "correct": True,
            "bloom_level": "understand",
            "topic": "Newton",
            "skill_tag": "recall",
        }
        for i in range(3)
    ]
    return json.dumps(questions)


def _make_bloom_json() -> str:
    return json.dumps({
        "counts": {
            "remember": 5, "understand": 3, "apply": 0,
            "analyze": 0, "evaluate": 0, "create": 0,
        },
        "lower_order_dominant": True,
        "suggestions": [
            "Design an experiment to test Newton's Second Law.",
            "Evaluate how friction affects motion.",
        ],
    })


def _make_missing_concepts_json() -> str:
    return json.dumps({
        "prerequisite_gaps": ["Velocity", "Acceleration"],
        "incomplete_topics": ["Friction"],
        "suggested_next": "Friction — types and applications",
    })


def _make_experiments_json() -> str:
    return json.dumps([
        {
            "title": "Coin Drop",
            "topic": "Inertia",
            "difficulty": "easy",
            "description": "Drop a coin from a card to show inertia.",
            "materials": ["Card", "Coin"],
            "steps": ["Place card on cup", "Place coin on card", "Flick card"],
            "expected_outcome": "Coin falls into cup.",
            "safety_note": "No hazards.",
            "xperimentor_kit": None,
        }
    ])


def _make_homework_json() -> str:
    return json.dumps([
        {
            "task": "Write 3 examples of Newton's Second Law from daily life.",
            "type": "explore",
            "bloom_level": "apply",
            "estimated_minutes": 20,
            "topic": "Newton's Laws",
        }
    ])


def _make_analogies_json() -> str:
    return json.dumps([
        {
            "concept": "Inertia",
            "analogy": "A cricket ball rolling on a flat pitch.",
            "explanation": "Once moving, it keeps moving unless something stops it.",
        }
    ])


def _make_mock_response(output_type: str) -> tuple[str, int]:
    """Return (raw_content, token_count) for a given output type."""
    responses = {
        "notes": (
            "# Newton's Laws of Motion\n\n"
            "## First Law\nAn object at rest stays at rest unless acted upon by a force.\n\n"
            "## Second Law\nF = ma — force equals mass times acceleration.\n\n"
            "## Third Law\nEvery action has an equal and opposite reaction.",
            200,
        ),
        "summary": (
            "Today we studied Newton's Three Laws of Motion. "
            "The first law describes inertia. "
            "The second law gives the relationship F = ma. "
            "The third law explains action-reaction pairs.",
            80,
        ),
        "quiz": (_make_valid_quiz_json(), 500),
        "bloom": (_make_bloom_json(), 200),
        "missing_concepts": (_make_missing_concepts_json(), 300),
        "experiments": (_make_experiments_json(), 400),
        "visual_cards": (
            json.dumps([
                {"title": "Inertia", "content": "Tendency of objects to resist change.", "formula": None, "bloom_level": "remember"},
                {"title": "F = ma", "content": "Force equals mass times acceleration.", "formula": "F = ma", "bloom_level": "remember"},
            ]),
            200,
        ),
        "homework": (_make_homework_json(), 200),
        "analogies": (_make_analogies_json(), 150),
    }
    return responses.get(output_type, ('{"placeholder": true}', 50))


@pytest.mark.asyncio
async def test_real_generation_with_mock_openai(client, db, session_id):
    """
    With OPENAI_API_KEY set + call_openai mocked, run_generation should:
    - persist AIOutput rows for every requested type
    - persist quiz_questions rows
    - persist missing_concepts rows
    - persist experiment_suggestions rows
    """
    # Create a frame with OCR text so the service has something to work with
    sid_uuid = uuid.UUID(session_id)
    from app.models.frame import Frame
    from app.models.ocr_result import OCRResult
    frame = Frame(
        id=uuid.uuid4(),
        local_frame_id="local-ai-test-frame",
        session_id=sid_uuid,
        sequence_no=1,
        image_path="/tmp/test.jpg",
        image_size_kb=10,
        captured_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        ocr_status="done",
    )
    db.add(frame)
    await db.flush()
    ocr = OCRResult(
        id=uuid.uuid4(),
        frame_id=frame.id,
        raw_text=(
            "Newton's Laws of Motion\n"
            "First Law: An object at rest stays at rest.\n"
            "Second Law: F = ma\n"
            "Third Law: Every action has an equal and opposite reaction.\n"
            "Key formula: Force = Mass × Acceleration"
        ),
        confidence=0.9,
        engine_used="paddleocr",
    )
    db.add(ocr)
    await db.commit()

    output_types = ["notes", "summary", "quiz", "bloom",
                    "missing_concepts", "experiments", "homework", "analogies"]

    call_count = {"n": 0}
    output_iter = iter(output_types)

    # Distinctive substrings present in exactly one prompt template.
    # More specific strings listed first to avoid cross-matching.
    _KEYWORD_MAP = [
        ("bloom",            "lower_order_dominant"),  # bloom JSON schema hint
        ("missing_concepts", "prerequisite_gaps"),     # missing_concepts JSON schema
        ("experiments",      "xperimentor_kit"),       # experiments JSON schema
        ("visual_cards",     "flash card"),            # visual_cards wording
        ("homework",         "estimated_minutes"),     # homework JSON schema
        ("analogies",        "real-life analogies"),   # analogies intro phrase
        ("notes",            "structured study notes"),
        ("summary",          "3–5 sentence"),     # en-dash "3–5 sentence"
        ("quiz",             "EXACTLY"),               # quiz strict wording
    ]

    async def mock_call_openai(**kwargs):
        user = kwargs.get("user", "")
        for otype, keyword in _KEYWORD_MAP:
            if keyword.lower() in user.lower():
                call_count["n"] += 1
                return _make_mock_response(otype)
        call_count["n"] += 1
        return ('{"placeholder": true}', 50)

    settings_obj = type("S", (), {
        "openai_api_key": "sk-test-fake-key",
        "openai_model_default": "gpt-4o",
        "openai_model_mini": "gpt-4o-mini",
        "ai_max_retries": 1,
        "ai_request_timeout_sec": 10,
        "ai_max_ocr_tokens": 4000,
    })()

    with patch("app.ai.call_openai", new=mock_call_openai):
        from app.services import ai_service
        from app.models.job import Job

        job = Job(
            id=uuid.uuid4(),
            job_type="ai_generation",
            session_id=sid_uuid,
            status="queued",
            progress=0,
        )
        db.add(job)
        await db.commit()

        await ai_service._run_real_generation(
            sid_uuid, output_types, job.id, db, settings_obj
        )

    # Verify AIOutput rows
    rows = (
        await db.execute(
            select(AIOutput).where(AIOutput.session_id == sid_uuid)
        )
    ).scalars().all()
    row_types = {r.output_type for r in rows}
    for otype in output_types:
        assert otype in row_types, f"AIOutput row missing for {otype}"
        row = next(r for r in rows if r.output_type == otype)
        assert row.status == "ready", f"{otype} status={row.status}"

    # Verify quiz_questions rows
    quiz_rows = (
        await db.execute(
            select(QuizQuestion).where(QuizQuestion.session_id == sid_uuid)
        )
    ).scalars().all()
    assert len(quiz_rows) == 8, f"Expected 8 quiz questions, got {len(quiz_rows)}"
    mcq_count = sum(1 for q in quiz_rows if q.question_type == "mcq")
    tf_count = sum(1 for q in quiz_rows if q.question_type == "true_false")
    assert mcq_count == 5
    assert tf_count == 3

    # Verify missing_concepts rows
    mc_rows = (
        await db.execute(
            select(MissingConcept).where(MissingConcept.session_id == sid_uuid)
        )
    ).scalars().all()
    assert len(mc_rows) >= 1, "Expected at least one MissingConcept row"
    gap_rows = [r for r in mc_rows if r.concept_type == "prerequisite_gap"]
    assert len(gap_rows) >= 1

    # Verify experiment_suggestions rows
    exp_rows = (
        await db.execute(
            select(ExperimentSuggestion).where(ExperimentSuggestion.session_id == sid_uuid)
        )
    ).scalars().all()
    assert len(exp_rows) >= 1, "Expected at least one ExperimentSuggestion row"
    assert exp_rows[0].title == "Coin Drop"

    # Verify session status updated
    from app.models.session import Session as SessionModel
    session_obj = (
        await db.execute(
            select(SessionModel).where(SessionModel.id == sid_uuid)
        )
    ).scalar_one()
    assert session_obj.status == "ai_complete"


@pytest.mark.asyncio
async def test_real_generation_classroom_memory_updated(client, db, session_id):
    """After generation, ClassroomMemory row must be created/updated."""
    sid_uuid = uuid.UUID(session_id)
    from app.models.frame import Frame
    from app.models.ocr_result import OCRResult

    frame = Frame(
        id=uuid.uuid4(),
        local_frame_id="local-memory-test",
        session_id=sid_uuid,
        sequence_no=1,
        image_path="/tmp/test.jpg",
        image_size_kb=5,
        captured_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        ocr_status="done",
    )
    db.add(frame)
    await db.flush()
    db.add(OCRResult(
        id=uuid.uuid4(),
        frame_id=frame.id,
        raw_text="# Newton's Laws\n\n## First Law\nObjects at rest stay at rest.\n\n"
                 "## Second Law\nF = ma.\n\n## Third Law\nAction equals reaction.",
        confidence=0.85,
        engine_used="paddleocr",
    ))
    await db.commit()

    async def mock_call(**kwargs):
        user = kwargs.get("user", "")
        if "prerequisite" in user:
            return (_make_missing_concepts_json(), 300)
        if "structured study notes" in user:
            return (
                "# Newton's Laws of Motion\n\n"
                "## First Law\nObjects at rest stay at rest.\n\n"
                "## Second Law\nF = ma\n\n"
                "## Third Law\nEvery action has an equal and opposite reaction.\n",
                200,
            )
        return ('{"placeholder": true}', 50)

    with patch("app.ai.call_openai", new=mock_call):
        settings_obj = type("S", (), {
            "openai_api_key": "sk-test",
            "openai_model_default": "gpt-4o",
            "openai_model_mini": "gpt-4o-mini",
            "ai_max_retries": 1,
            "ai_request_timeout_sec": 10,
            "ai_max_ocr_tokens": 4000,
        })()

        from app.models.job import Job
        job = Job(
            id=uuid.uuid4(),
            job_type="ai_generation",
            session_id=sid_uuid,
            status="queued",
            progress=0,
        )
        db.add(job)
        await db.commit()

        from app.services import ai_service
        await ai_service._run_real_generation(
            sid_uuid, ["notes", "missing_concepts"], job.id, db, settings_obj
        )

    memory = (
        await db.execute(
            select(ClassroomMemory).where(
                ClassroomMemory.teacher_id == uuid.UUID(TEACHER_ID)
            )
        )
    ).scalar_one_or_none()
    assert memory is not None
    assert memory.last_session_id == sid_uuid
    assert memory.topics_covered is not None
    # "Newton's Laws of Motion" heading should be in topics
    assert any("Newton" in str(t) for t in memory.topics_covered)
    assert memory.suggested_next == "Friction — types and applications"


@pytest.mark.asyncio
async def test_parse_failure_retries_then_marks_partial(client, db, session_id):
    """If both parse attempts fail, output must be stored with status='partial'."""
    sid_uuid = uuid.UUID(session_id)
    from app.models.frame import Frame
    from app.models.ocr_result import OCRResult

    frame = Frame(
        id=uuid.uuid4(),
        local_frame_id="local-partial-test",
        session_id=sid_uuid,
        sequence_no=1,
        image_path="/tmp/x.jpg",
        image_size_kb=5,
        captured_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        ocr_status="done",
    )
    db.add(frame)
    await db.flush()
    db.add(OCRResult(
        id=uuid.uuid4(),
        frame_id=frame.id,
        raw_text="Some board content about science topics.",
        confidence=0.7,
        engine_used="paddleocr",
    ))
    await db.commit()

    # Always return garbage JSON
    async def bad_openai(**kwargs):
        return ("This is not valid JSON at all!!!", 50)

    with patch("app.ai.call_openai", new=bad_openai):
        settings_obj = type("S", (), {
            "openai_api_key": "sk-test",
            "openai_model_default": "gpt-4o",
            "openai_model_mini": "gpt-4o-mini",
            "ai_max_retries": 1,
            "ai_request_timeout_sec": 5,
            "ai_max_ocr_tokens": 4000,
        })()

        from app.models.job import Job
        job = Job(
            id=uuid.uuid4(),
            job_type="ai_generation",
            session_id=sid_uuid,
            status="queued",
            progress=0,
        )
        db.add(job)
        await db.commit()

        from app.services import ai_service
        # Should NOT raise — partial failure is swallowed
        await ai_service._run_real_generation(
            sid_uuid, ["quiz"], job.id, db, settings_obj
        )

    row = (
        await db.execute(
            select(AIOutput).where(
                AIOutput.session_id == sid_uuid,
                AIOutput.output_type == "quiz",
            )
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.status == "partial"
    assert "error" in row.content_json


@pytest.mark.asyncio
async def test_refusal_marks_failed(client, db, session_id):
    """A refusal response must store status='failed' without retry."""
    sid_uuid = uuid.UUID(session_id)
    from app.models.frame import Frame
    from app.models.ocr_result import OCRResult

    frame = Frame(
        id=uuid.uuid4(),
        local_frame_id="local-refusal-test",
        session_id=sid_uuid,
        sequence_no=1,
        image_path="/tmp/x.jpg",
        image_size_kb=5,
        captured_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        ocr_status="done",
    )
    db.add(frame)
    await db.flush()
    db.add(OCRResult(
        id=uuid.uuid4(),
        frame_id=frame.id,
        raw_text=(
            "Newton's Laws of Motion. First Law: objects at rest stay at rest. "
            "Second Law: F equals ma. Third Law: action equals reaction."
        ),
        confidence=0.7,
        engine_used="paddleocr",
    ))
    await db.commit()

    async def refusal_openai(**kwargs):
        return ("I cannot generate quiz questions for this content as it is inappropriate.", 30)

    with patch("app.ai.call_openai", new=refusal_openai):
        settings_obj = type("S", (), {
            "openai_api_key": "sk-test",
            "openai_model_default": "gpt-4o",
            "openai_model_mini": "gpt-4o-mini",
            "ai_max_retries": 1,
            "ai_request_timeout_sec": 5,
            "ai_max_ocr_tokens": 4000,
        })()

        from app.models.job import Job
        job = Job(
            id=uuid.uuid4(),
            job_type="ai_generation",
            session_id=sid_uuid,
            status="queued",
            progress=0,
        )
        db.add(job)
        await db.commit()

        from app.services import ai_service
        await ai_service._run_real_generation(
            sid_uuid, ["quiz"], job.id, db, settings_obj
        )

    row = (
        await db.execute(
            select(AIOutput).where(
                AIOutput.session_id == sid_uuid,
                AIOutput.output_type == "quiz",
            )
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.status == "failed"


@pytest.mark.asyncio
async def test_insufficient_ocr_falls_back_to_placeholder(client, db, session_id):
    """Session with no OCR text must fall back to placeholder, not error."""
    # No frames/OCR added — ocr_text will be ""
    settings_obj = type("S", (), {
        "openai_api_key": "sk-test",
        "openai_model_default": "gpt-4o",
        "openai_model_mini": "gpt-4o-mini",
        "ai_max_retries": 1,
        "ai_request_timeout_sec": 5,
        "ai_max_ocr_tokens": 4000,
    })()

    sid_uuid = uuid.UUID(session_id)

    from app.models.job import Job
    job = Job(
        id=uuid.uuid4(),
        job_type="ai_generation",
        session_id=sid_uuid,
        status="queued",
        progress=0,
    )
    db.add(job)
    await db.commit()

    from app.services import ai_service
    # Should not raise; falls back to placeholder silently
    await ai_service._run_real_generation(
        sid_uuid, ["notes"], job.id, db, settings_obj
    )

    row = (
        await db.execute(
            select(AIOutput).where(
                AIOutput.session_id == sid_uuid,
                AIOutput.output_type == "notes",
            )
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.status == "ready"
    assert row.content_json.get("metadata", {}).get("placeholder") is True


# ---------------------------------------------------------------------------
# GET /sessions/{id}/outputs quiz endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_quiz_not_ready_before_generation(client, db):
    """GET /outputs/quiz before any generation returns 404."""
    resp = await client.post(
        "/v1/sessions",
        json={
            "teacher_id": TEACHER_ID,
            "classroom_id": str(CLASSROOM_ID),
            "subject": "Biology",
            "grade": "Grade 6",
            "board_type": "whiteboard",
            "capture_mode": "time_based",
            "capture_interval_sec": 30,
        },
    )
    sid = resp.json()["session_id"]
    quiz_resp = await client.get(f"/v1/sessions/{sid}/outputs/quiz")
    assert quiz_resp.status_code == 404
    assert quiz_resp.json()["error"] == "QUIZ_NOT_READY"


@pytest.mark.asyncio
async def test_get_quiz_after_generation(client, db, session_id):
    await client.post(
        f"/v1/sessions/{session_id}/generate",
        json={"outputs": ["quiz"]},
    )
    import asyncio; await asyncio.sleep(0.1)

    resp = await client.get(f"/v1/sessions/{session_id}/outputs/quiz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == session_id
    questions = data["questions"]
    assert len(questions) > 0
    for q in questions:
        assert "type" in q
        assert "text" in q
        assert "bloom_level" in q
        assert q["type"] in ("mcq", "true_false")
