"""
Unit tests for the TiQer export service.

Tests cover:
  - payload structure and field mapping
  - MCQ correct-answer index → A/B/C/D conversion
  - T/F correct-answer bool → "true"/"false" conversion
  - bloom_level → difficulty derivation
  - skill_tag fallback chain (stored → topic → "general")
  - degenerate inputs (missing options, unknown bloom, null skill_tag)
  - serialisation round-trip
  - metadata counts (mcq_count, bloom_distribution)
"""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.services.tiqer_service import (
    build_tiqer_payload,
    serialise_payload,
    payload_to_dict,
    _correct_answer_for,
    _bloom_level_for,
    _skill_tag_for,
    _BLOOM_DIFFICULTY,
)
from app.schemas.tiqer import TiQerExportPayload, TiQerQuestion


# ── Helpers ────────────────────────────────────────────────────────────────────

def _session(subject="Physics", grade="Grade 9") -> MagicMock:
    s = MagicMock()
    s.id = uuid.uuid4()
    s.subject = subject
    s.grade = grade
    return s


def _mcq(
    bloom="understand",
    topic="Newton's Laws",
    skill_tag=None,
    correct_idx=0,
    options=None,
) -> MagicMock:
    q = MagicMock()
    q.id = uuid.uuid4()
    q.question_type = "mcq"
    q.text = "What is Newton's Second Law?"
    q.options = options or ["F=ma", "F=mv", "F=mg", "F=ma²"]
    q.correct_answer = {"value": correct_idx}
    q.bloom_level = bloom
    q.topic = topic
    q.skill_tag = skill_tag
    return q


def _tf(bloom="remember", topic="Forces", skill_tag=None, correct=True) -> MagicMock:
    q = MagicMock()
    q.id = uuid.uuid4()
    q.question_type = "true_false"
    q.text = "Acceleration is proportional to force."
    q.options = None
    q.correct_answer = {"value": correct}
    q.bloom_level = bloom
    q.topic = topic
    q.skill_tag = skill_tag
    return q


TEACHER_ID = uuid.uuid4()


# ── _correct_answer_for ────────────────────────────────────────────────────────

class TestCorrectAnswerFor:
    def test_mcq_idx_0_is_A(self):
        assert _correct_answer_for(_mcq(correct_idx=0)) == "A"

    def test_mcq_idx_1_is_B(self):
        assert _correct_answer_for(_mcq(correct_idx=1)) == "B"

    def test_mcq_idx_2_is_C(self):
        assert _correct_answer_for(_mcq(correct_idx=2)) == "C"

    def test_mcq_idx_3_is_D(self):
        assert _correct_answer_for(_mcq(correct_idx=3)) == "D"

    def test_mcq_out_of_range_defaults_to_A(self):
        q = _mcq(correct_idx=5)
        assert _correct_answer_for(q) == "A"

    def test_mcq_none_answer_defaults_to_A(self):
        q = _mcq(correct_idx=0)
        q.correct_answer = None
        assert _correct_answer_for(q) == "A"

    def test_tf_true(self):
        assert _correct_answer_for(_tf(correct=True)) == "true"

    def test_tf_false(self):
        assert _correct_answer_for(_tf(correct=False)) == "false"

    def test_tf_string_true(self):
        q = _tf()
        q.correct_answer = {"value": "true"}
        assert _correct_answer_for(q) == "true"

    def test_tf_string_false(self):
        q = _tf()
        q.correct_answer = {"value": "false"}
        assert _correct_answer_for(q) == "false"


# ── _bloom_level_for ────────────────────────────────────────────────────────────

class TestBloomLevelFor:
    @pytest.mark.parametrize("level", ["remember", "understand", "apply", "analyze", "evaluate", "create"])
    def test_known_levels_pass_through(self, level):
        q = _mcq(bloom=level)
        assert _bloom_level_for(q) == level

    def test_unknown_bloom_falls_back_to_remember(self):
        q = _mcq(bloom="memorise")  # typo
        assert _bloom_level_for(q) == "remember"

    def test_none_bloom_falls_back_to_remember(self):
        q = _mcq(bloom=None)
        assert _bloom_level_for(q) == "remember"

    def test_uppercase_bloom_is_lowercased(self):
        q = _mcq(bloom="Understand")
        assert _bloom_level_for(q) == "understand"


# ── Bloom → difficulty ─────────────────────────────────────────────────────────

class TestBloomDifficulty:
    def test_remember_is_easy(self):
        assert _BLOOM_DIFFICULTY["remember"] == "easy"

    def test_understand_is_easy(self):
        assert _BLOOM_DIFFICULTY["understand"] == "easy"

    def test_apply_is_medium(self):
        assert _BLOOM_DIFFICULTY["apply"] == "medium"

    def test_analyze_is_medium(self):
        assert _BLOOM_DIFFICULTY["analyze"] == "medium"

    def test_evaluate_is_hard(self):
        assert _BLOOM_DIFFICULTY["evaluate"] == "hard"

    def test_create_is_hard(self):
        assert _BLOOM_DIFFICULTY["create"] == "hard"


# ── _skill_tag_for ─────────────────────────────────────────────────────────────

class TestSkillTagFor:
    def test_stored_skill_tag_used(self):
        q = _mcq(skill_tag="newton-second-law")
        assert _skill_tag_for(q) == "newton-second-law"

    def test_skill_tag_slugified(self):
        q = _mcq(skill_tag="Newton's Second Law")
        assert _skill_tag_for(q) == "newtons-second-law"

    def test_fallback_to_topic(self):
        q = _mcq(skill_tag=None, topic="Friction Forces")
        assert _skill_tag_for(q) == "friction-forces"

    def test_fallback_to_general_when_no_topic(self):
        q = _mcq(skill_tag=None, topic=None)
        assert _skill_tag_for(q) == "general"

    def test_skill_tag_truncated_at_80_chars(self):
        q = _mcq(skill_tag="a" * 100)
        assert len(_skill_tag_for(q)) <= 80

    def test_special_chars_removed(self):
        q = _mcq(skill_tag="Forces & Motion: Part 1")
        tag = _skill_tag_for(q)
        assert "&" not in tag
        assert ":" not in tag
        assert " " not in tag


# ── build_tiqer_payload ────────────────────────────────────────────────────────

class TestBuildTiQerPayload:
    def _make_payload(self, questions=None, tiqer_class_id="CLS-001"):
        session = _session()
        qs = questions or [_mcq(), _tf()]
        return build_tiqer_payload(
            session=session,
            teacher_id=TEACHER_ID,
            questions=qs,
            tiqer_class_id=tiqer_class_id,
        )

    # ── Envelope fields ──────────────────────────────────────────────────────

    def test_schema_version_is_1_0(self):
        p = self._make_payload()
        assert p.schema_version == "1.0"

    def test_class_id_preserved(self):
        p = self._make_payload(tiqer_class_id="CLS-2026-G9-PHY")
        assert p.tiqer_class_id == "CLS-2026-G9-PHY"

    def test_question_count_matches(self):
        qs = [_mcq(), _mcq(), _tf()]
        p = self._make_payload(questions=qs)
        assert p.question_count == 3

    def test_subject_and_grade_from_session(self):
        s = _session(subject="Chemistry", grade="Grade 11")
        p = build_tiqer_payload(s, TEACHER_ID, [_mcq()], "CLS")
        assert p.subject == "Chemistry"
        assert p.grade == "Grade 11"

    def test_exported_at_is_timezone_aware(self):
        p = self._make_payload()
        assert p.exported_at.tzinfo is not None

    def test_export_id_is_uuid_string(self):
        p = self._make_payload()
        uuid.UUID(p.export_id)  # raises if invalid

    def test_custom_export_id_preserved(self):
        eid = "my-custom-id"
        session = _session()
        p = build_tiqer_payload(session, TEACHER_ID, [_mcq()], "C", export_id=eid)
        assert p.export_id == eid

    # ── Questions ────────────────────────────────────────────────────────────

    def test_question_sequence_starts_at_1(self):
        p = self._make_payload()
        assert p.questions[0].sequence == 1

    def test_question_sequence_increments(self):
        p = self._make_payload(questions=[_mcq(), _tf(), _mcq()])
        seqs = [q.sequence for q in p.questions]
        assert seqs == [1, 2, 3]

    def test_mcq_has_4_options(self):
        p = self._make_payload(questions=[_mcq()])
        q = p.questions[0]
        assert q.options is not None
        assert len(q.options) == 4

    def test_mcq_option_keys_are_A_B_C_D(self):
        p = self._make_payload(questions=[_mcq()])
        keys = [o.key for o in p.questions[0].options]
        assert keys == ["A", "B", "C", "D"]

    def test_tf_options_are_none(self):
        p = self._make_payload(questions=[_tf()])
        assert p.questions[0].options is None

    def test_mcq_correct_answer_is_letter(self):
        p = self._make_payload(questions=[_mcq(correct_idx=2)])
        assert p.questions[0].correct_answer == "C"

    def test_tf_correct_answer_true(self):
        p = self._make_payload(questions=[_tf(correct=True)])
        assert p.questions[0].correct_answer == "true"

    def test_tf_correct_answer_false(self):
        p = self._make_payload(questions=[_tf(correct=False)])
        assert p.questions[0].correct_answer == "false"

    def test_difficulty_derived_from_bloom(self):
        p = self._make_payload(questions=[
            _mcq(bloom="remember"),
            _mcq(bloom="apply"),
            _mcq(bloom="create"),
        ])
        diffs = [q.difficulty for q in p.questions]
        assert diffs == ["easy", "medium", "hard"]

    def test_grade_on_each_question(self):
        s = _session(grade="Grade 10")
        p = build_tiqer_payload(s, TEACHER_ID, [_mcq()], "C")
        assert p.questions[0].grade == "Grade 10"

    def test_subject_on_each_question(self):
        s = _session(subject="Biology")
        p = build_tiqer_payload(s, TEACHER_ID, [_mcq()], "C")
        assert p.questions[0].subject == "Biology"

    # ── Metadata ─────────────────────────────────────────────────────────────

    def test_mcq_count_in_metadata(self):
        p = self._make_payload(questions=[_mcq(), _mcq(), _tf()])
        assert p.metadata.mcq_count == 2

    def test_tf_count_in_metadata(self):
        p = self._make_payload(questions=[_mcq(), _tf(), _tf()])
        assert p.metadata.true_false_count == 2

    def test_bloom_distribution_counts(self):
        p = self._make_payload(questions=[
            _mcq(bloom="remember"),
            _mcq(bloom="remember"),
            _mcq(bloom="apply"),
            _tf(bloom="evaluate"),
        ])
        dist = p.metadata.bloom_distribution
        assert dist["remember"] == 2
        assert dist["apply"] == 1
        assert dist["evaluate"] == 1
        assert dist["understand"] == 0

    def test_bloom_distribution_has_all_six_levels(self):
        p = self._make_payload()
        keys = set(p.metadata.bloom_distribution.keys())
        assert keys == {"remember", "understand", "apply", "analyze", "evaluate", "create"}

    def test_generated_by_string(self):
        p = self._make_payload()
        assert "ACI" in p.metadata.generated_by

    # ── Null session fields ───────────────────────────────────────────────────

    def test_null_subject_becomes_general(self):
        s = _session(subject=None)
        p = build_tiqer_payload(s, TEACHER_ID, [_mcq()], "C")
        assert p.subject == "General"

    def test_null_grade_becomes_unknown(self):
        s = _session(grade=None)
        p = build_tiqer_payload(s, TEACHER_ID, [_mcq()], "C")
        assert "unknown" in p.grade.lower()

    def test_null_options_mcq_handled_gracefully(self):
        q = _mcq()
        q.options = None
        s = _session()
        p = build_tiqer_payload(s, TEACHER_ID, [q], "C")
        # Should produce None or empty options, not raise
        assert p.questions[0].options is None or p.questions[0].options == []


# ── Serialisation ──────────────────────────────────────────────────────────────

class TestSerialisation:
    def test_serialise_produces_valid_json(self):
        session = _session()
        payload = build_tiqer_payload(session, TEACHER_ID, [_mcq(), _tf()], "CLS-X")
        raw = serialise_payload(payload)
        parsed = json.loads(raw)
        assert parsed["schema_version"] == "1.0"
        assert len(parsed["questions"]) == 2

    def test_payload_to_dict_is_dict(self):
        session = _session()
        payload = build_tiqer_payload(session, TEACHER_ID, [_mcq()], "CLS")
        d = payload_to_dict(payload)
        assert isinstance(d, dict)
        assert "questions" in d

    def test_round_trip_preserves_question_count(self):
        session = _session()
        questions = [_mcq(), _mcq(), _tf(), _tf(), _mcq()]
        payload = build_tiqer_payload(session, TEACHER_ID, questions, "CLS")
        d = payload_to_dict(payload)
        assert d["question_count"] == 5
        assert len(d["questions"]) == 5

    def test_options_serialised_as_list_of_dicts(self):
        session = _session()
        payload = build_tiqer_payload(session, TEACHER_ID, [_mcq()], "CLS")
        d = payload_to_dict(payload)
        opts = d["questions"][0]["options"]
        assert isinstance(opts, list)
        assert opts[0]["key"] == "A"

    def test_tf_options_serialised_as_null(self):
        session = _session()
        payload = build_tiqer_payload(session, TEACHER_ID, [_tf()], "CLS")
        d = payload_to_dict(payload)
        assert d["questions"][0]["options"] is None

    def test_exported_at_is_iso_string(self):
        session = _session()
        payload = build_tiqer_payload(session, TEACHER_ID, [_mcq()], "CLS")
        d = payload_to_dict(payload)
        # Should not raise
        datetime.fromisoformat(d["exported_at"].replace("Z", "+00:00"))
