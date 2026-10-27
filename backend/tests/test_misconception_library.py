"""Library integrity, grade handling, code allow-list and early-grade guard."""
from __future__ import annotations

import json
import pathlib
import types
from unittest.mock import patch

import pytest

from app.data.misconception_seed import MISCONCEPTION_SEED
from app.models.practice_question import PracticeQuestion
from app.services import misconception_library as lib
from app.services.practice_service import _build_validate_system_prompt, validate_step

VALID_KEYS = {"math", "physics", "chemistry", "science", "history", "language"}
GOLDEN = json.loads((pathlib.Path(__file__).parents[1] / "evals" / "golden_cases.json").read_text())["cases"]


def test_seed_codes_unique_and_fields_sane():
    codes = [r["code"] for r in MISCONCEPTION_SEED]
    assert len(codes) == len(set(codes))
    for r in MISCONCEPTION_SEED:
        assert r["subject_key"] in VALID_KEYS
        assert 1 <= r["grade_min"] <= r["grade_max"] <= 10
        assert r["source_type"] in ("research", "convention")
        for f in ("title", "description", "typical_work", "source_citation"):
            assert r[f].strip(), f"{r['code']} missing {f}"


def test_every_subject_and_grade_band_is_covered():
    subjects = {r["subject_key"] for r in MISCONCEPTION_SEED}
    assert subjects == VALID_KEYS
    for g in range(1, 11):
        assert any(r["grade_min"] <= g <= r["grade_max"] for r in MISCONCEPTION_SEED), f"no entry covers grade {g}"


def test_golden_cases_reference_real_library_codes():
    codes = {r["code"] for r in MISCONCEPTION_SEED}
    for c in GOLDEN:
        if c.get("expected_misconception"):
            assert c["expected_misconception"] in codes, c["id"]
        assert 1 <= c["grade"] <= 10


@pytest.mark.parametrize("raw,expected", [("Grade 8", 8), ("8th", 8), ("Class 10", 10), ("3", 3), ("", None), (None, None), ("KG", None), ("Grade 15", None)])
def test_parse_grade(raw, expected):
    assert lib.parse_grade(raw) == expected


def test_grade_band():
    assert [lib.grade_band(g) for g in (1, 3, 4, 7, 8, 10)] == ["early", "early", "middle", "middle", "senior", "senior"]
    assert lib.grade_band(None) is None


def test_rank_candidates_filters_by_subject_grade_and_topic():
    out = lib.rank_candidates(MISCONCEPTION_SEED, ["math"], 5, "comparing decimal numbers 0.35 and 0.4", limit=3)
    assert out and out[0]["code"] == "M-DEC-01"
    assert all(r["code"].startswith("M-") for r in out)
    # a Grade 1 child never gets a Grade 9 trig entry
    assert "M-TRIG-01" not in {r["code"] for r in lib.rank_candidates(MISCONCEPTION_SEED, ["math"], 1, "trigonometry", limit=50)}


def test_physics_also_sees_general_science_entries():
    assert lib.library_subject_keys("physics") == ["physics", "science"]
    assert lib.library_subject_keys("other", "Biology") == ["science"]
    assert lib.library_subject_keys("other", "Art") == []


def test_grade_addendum_scales_down_rigor_for_young_students():
    early = _build_validate_system_prompt("Mathematics", "early")
    assert "does NOT apply to this student" in early
    assert "b/d" in early
    assert "does NOT apply" not in _build_validate_system_prompt("Mathematics", "senior")


def _fake(payload):
    async def create(**kw):
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=json.dumps(payload)))])
    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))


async def _run(payload, grade_band=None, library=None, known=None):
    q = PracticeQuestion(session_id=None, text="q", subject="Mathematics", answer_domain="conceptual", known_misconceptions=known)
    with patch("openai.AsyncOpenAI", return_value=_fake(payload)):
        return await validate_step(
            q, [{"text": "s"}], None, ollama_base_url="x", ollama_model="x",
            openai_api_key="k", local_enabled=False, grade_band=grade_band, library_misconceptions=library,
        )


BASE = {"validation_status": "conceptual_misconception", "error_step_index": 0, "reason_code": "r", "confidence": 90}


@pytest.mark.asyncio
async def test_off_list_misconception_code_is_dropped():
    r = await _run({**BASE, "misconception_code": "MADE_UP"}, library=[{"code": "M-DEC-01"}])
    assert r["validation_status"] == "conceptual_misconception" and r["misconception_code"] is None


@pytest.mark.asyncio
async def test_library_code_is_kept():
    r = await _run({**BASE, "misconception_code": "M-DEC-01"}, library=[{"code": "M-DEC-01"}])
    assert r["misconception_code"] == "M-DEC-01"


@pytest.mark.asyncio
async def test_question_known_code_is_kept():
    r = await _run({**BASE, "misconception_code": "MC1"}, known=[{"code": "MC1"}])
    assert r["misconception_code"] == "MC1"


@pytest.mark.asyncio
async def test_early_grade_spelling_is_never_a_misconception():
    payload = {**BASE, "misconception_code": "L-SPELL-01", "reason_code": "phonetic_spelling"}
    early = await _run(payload, grade_band="early", library=[{"code": "L-SPELL-01"}])
    assert early["validation_status"] == "valid_progress" and early["error_step_index"] is None
    senior = await _run(payload, grade_band="senior", library=[{"code": "L-SPELL-01"}])
    assert senior["validation_status"] == "conceptual_misconception"
