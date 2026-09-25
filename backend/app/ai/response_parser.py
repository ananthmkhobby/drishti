"""
Response parsers and validators for every AI output type.

Each public parse_* function:
  1. Strips markdown code fences
  2. JSON-parses where required
  3. Validates the schema with clear field checks
  4. Returns a normalised dict ready to be stored in ai_outputs.content_json
  5. Raises ParseError on schema failure or RefusalError on AI refusal
"""
from __future__ import annotations

import json
import re
from typing import Any

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ParseError(ValueError):
    """Raised when the raw AI response cannot be turned into a valid structure."""

class RefusalError(ParseError):
    """Raised when the model returned a refusal / 'I cannot …' response."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```\w*\s*|\s*```$", re.MULTILINE)

_REFUSAL_MARKERS = (
    "i cannot",
    "i don't have enough",
    "i'm unable",
    "i am unable",
    "not enough information",
    "cannot generate",
    "i apologize, but i",
    "as an ai,",
    "as an ai language",
)

BLOOM_LEVELS_VALID = frozenset(
    {"remember", "understand", "apply", "analyze", "evaluate", "create"}
)

QUESTION_TYPES_VALID = frozenset({"mcq", "true_false"})

EXPERIMENT_DIFFICULTIES = frozenset({"easy", "medium", "hard"})

HOMEWORK_TYPES = frozenset({"practice", "explore", "research", "creative"})


def _strip_fences(raw: str) -> str:
    """Remove ``` / ```json code fences from an LLM response."""
    return _FENCE_RE.sub("", raw).strip()


def _detect_refusal(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in _REFUSAL_MARKERS)


def _load_json(raw: str) -> Any:
    """Strip fences then JSON-parse; raises ParseError on decode failure."""
    clean = _strip_fences(raw)
    if not clean:
        raise ParseError("Empty response from model")
    try:
        return json.loads(clean)
    except json.JSONDecodeError as exc:
        # Try to salvage: sometimes there's text after the closing bracket
        # Look for the first complete JSON array or object
        for start_char, end_char in [("[", "]"), ("{", "}")]:
            start = clean.find(start_char)
            end = clean.rfind(end_char)
            if start != -1 and end > start:
                try:
                    return json.loads(clean[start : end + 1])
                except json.JSONDecodeError:
                    pass
        raise ParseError(f"JSON decode failed: {exc}") from exc


def _require_keys(obj: dict, *keys: str, context: str = "") -> None:
    missing = [k for k in keys if k not in obj]
    if missing:
        prefix = f"[{context}] " if context else ""
        raise ParseError(f"{prefix}Missing required keys: {missing}")


# ---------------------------------------------------------------------------
# Notes  (new: Curriculum Intelligence JSON; falls back to plain markdown)
# ---------------------------------------------------------------------------

def parse_notes(raw: str) -> dict:
    """
    New format: JSON object with markdown + mind_map + curriculum analysis.
    Legacy format: plain markdown string — still accepted for old sessions.

    Returns dict always containing at least: {"markdown": str}
    Rich new format also contains: mind_map, session_summary, topic_detected,
    covered_concepts, partially_covered_concepts, missing_concepts,
    missing_prerequisites, curriculum_coverage, bloom_distribution,
    teaching_completeness_score, recommended_next_topics, suggested_exercises.
    """
    if _detect_refusal(raw):
        raise RefusalError("Model refused to generate notes")

    # ── Try JSON first (new curriculum intelligence format) ──────────────────
    try:
        data = _load_json(raw)
        if isinstance(data, dict):
            markdown = data.get("markdown", "")
            if not isinstance(markdown, str) or len(markdown.strip()) < 30:
                topic = data.get("topic_detected", "Notes")
                summary = data.get("session_summary", "")
                markdown = f"# {topic}\n\n{summary}\n"
            if "#" not in markdown:
                markdown = "# Notes\n\n" + markdown
            data["markdown"] = markdown
            # Ensure all optional curriculum fields have safe defaults
            data.setdefault("mind_map", "")
            data.setdefault("session_summary", "")
            data.setdefault("topic_detected", "")
            data.setdefault("covered_concepts", [])
            data.setdefault("partially_covered_concepts", [])
            data.setdefault("missing_concepts", [])
            data.setdefault("missing_prerequisites", [])
            data.setdefault("curriculum_coverage", {})
            data.setdefault("bloom_distribution", {})
            data.setdefault("teaching_completeness_score", None)
            data.setdefault("recommended_next_topics", [])
            data.setdefault("suggested_exercises", [])
            return data
    except ParseError:
        pass  # Not JSON — fall through to markdown handling

    # ── Legacy: plain markdown ───────────────────────────────────────────────
    text = raw.strip()
    if len(text) < 30:
        raise ParseError(f"Notes too short ({len(text)} chars) — likely incomplete")
    if "#" not in text:
        raise ParseError("Notes missing a markdown heading")
    return {
        "markdown": text,
        # Provide empty defaults so UI code can safely check these fields
        "mind_map": "",
        "session_summary": "",
        "topic_detected": "",
        "covered_concepts": [],
        "partially_covered_concepts": [],
        "missing_concepts": [],
        "missing_prerequisites": [],
        "curriculum_coverage": {},
        "bloom_distribution": {},
        "teaching_completeness_score": None,
        "recommended_next_topics": [],
        "suggested_exercises": [],
    }


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def parse_summary(raw: str) -> dict:
    """
    Expect plain prose, 3–5 sentences.  Min 50 chars.
    Returns: {"text": str}
    """
    if _detect_refusal(raw):
        raise RefusalError("Model refused to generate summary")
    text = raw.strip()
    if len(text) < 50:
        raise ParseError(f"Summary too short ({len(text)} chars)")
    return {"text": text}


# ---------------------------------------------------------------------------
# Quiz
# ---------------------------------------------------------------------------

def _validate_question(q: dict, idx: int) -> dict:
    """Validate and normalise a single question dict."""
    ctx = f"question[{idx}]"
    if not isinstance(q, dict):
        raise ParseError(f"[{ctx}] Expected dict, got {type(q).__name__}")
    _require_keys(q, "type", "text", "bloom_level", context=ctx)

    q_type = q["type"]
    if q_type not in QUESTION_TYPES_VALID:
        raise ParseError(f"[{ctx}] Invalid type '{q_type}', expected mcq|true_false")

    bloom = str(q.get("bloom_level", "")).lower()
    if bloom not in BLOOM_LEVELS_VALID:
        # Normalise: accept "Understand" etc.
        bloom = bloom.strip()
        if bloom not in BLOOM_LEVELS_VALID:
            q["bloom_level"] = "remember"  # coerce to safe default

    if q_type == "mcq":
        opts = q.get("options")
        if not isinstance(opts, list) or len(opts) != 4:
            raise ParseError(f"[{ctx}] MCQ must have exactly 4 options, got {opts!r}")
        correct = q.get("correct")
        if not isinstance(correct, int) or correct not in range(4):
            raise ParseError(f"[{ctx}] MCQ correct must be int 0–3, got {correct!r}")
    else:  # true_false
        correct = q.get("correct")
        if not isinstance(correct, bool):
            # Coerce string "true"/"false"
            if isinstance(correct, str):
                q["correct"] = correct.lower() == "true"
            else:
                raise ParseError(f"[{ctx}] T/F correct must be bool, got {correct!r}")

    return q


def parse_quiz(raw: str) -> list[dict]:
    """
    Expect a JSON array of question objects.
    Returns: list of validated question dicts.
    Raises ParseError if schema is invalid; raises RefusalError if model refused.
    """
    if _detect_refusal(raw):
        raise RefusalError("Model refused to generate quiz")
    data = _load_json(raw)
    if not isinstance(data, list):
        raise ParseError(f"Quiz must be a JSON array, got {type(data).__name__}")
    if len(data) == 0:
        raise ParseError("Quiz array is empty")

    questions = [_validate_question(q, i) for i, q in enumerate(data)]

    if not any(q["type"] == "mcq" for q in questions):
        raise ParseError("Quiz must include at least one MCQ question")
    if not any(q["type"] == "true_false" for q in questions):
        raise ParseError("Quiz must include at least one True/False question")

    return questions


# ---------------------------------------------------------------------------
# Bloom analysis
# ---------------------------------------------------------------------------

_BLOOM_KEYS = ("remember", "understand", "apply", "analyze", "evaluate", "create")


def parse_bloom(raw: str) -> dict:
    """
    Returns: {"counts": {…}, "lower_order_dominant": bool, "suggestions": [str, …]}
    """
    if _detect_refusal(raw):
        raise RefusalError("Model refused to generate bloom analysis")
    data = _load_json(raw)
    if not isinstance(data, dict):
        raise ParseError(f"Bloom must be a JSON object, got {type(data).__name__}")
    _require_keys(data, "counts", "lower_order_dominant", "suggestions", context="bloom")

    counts = data["counts"]
    if not isinstance(counts, dict):
        raise ParseError("bloom.counts must be an object")
    # Fill any missing bloom keys with 0
    for key in _BLOOM_KEYS:
        counts.setdefault(key, 0)

    if not isinstance(data.get("suggestions"), list):
        data["suggestions"] = []

    return {
        "counts": counts,
        "lower_order_dominant": bool(data["lower_order_dominant"]),
        "suggestions": [str(s) for s in data["suggestions"]],
    }


# ---------------------------------------------------------------------------
# Missing concepts  (new: deep Pedagogical Gap Analysis; backward-compat)
# ---------------------------------------------------------------------------

def parse_missing_concepts(raw: str) -> dict:
    """
    New format: rich pedagogical gap analysis JSON with 8-step framework output.
    Legacy format: simple {"prerequisite_gaps", "incomplete_topics", "suggested_next"}.

    Always returns at least the three legacy keys so downstream code keeps working.
    New keys: session_summary, topics_detected, concepts_covered, pedagogical_gaps,
    bloom_analysis, classroom_metrics, student_risk_areas, missing_prerequisites,
    instructional_weaknesses, recommended_interventions, suggested_next_steps,
    remediation_plan, teaching_effectiveness_score.
    """
    if _detect_refusal(raw):
        raise RefusalError("Model refused to generate missing concepts")
    data = _load_json(raw)
    if not isinstance(data, dict):
        raise ParseError(f"missing_concepts must be a JSON object, got {type(data).__name__}")
    _require_keys(data, "prerequisite_gaps", "incomplete_topics", "suggested_next", context="missing_concepts")

    # ── Ensure backward-compat keys always present ───────────────────────────
    prereq_gaps = [str(x) for x in (data.get("prerequisite_gaps") or data.get("missing_prerequisites") or [])]
    incomplete   = [str(x) for x in (data.get("incomplete_topics") or [])]
    suggested    = str(data.get("suggested_next") or "")

    # ── Rich pedagogical fields (new format) ─────────────────────────────────
    pg = data.get("pedagogical_gaps") or {}
    bloom_analysis = data.get("bloom_analysis") or {}
    bloom_dist = bloom_analysis.get("distribution") or {}
    for key in ("remember", "understand", "apply", "analyze", "evaluate", "create"):
        bloom_dist.setdefault(key, 0)

    classroom_metrics = data.get("classroom_metrics") or {}

    risk_areas = []
    for r in (data.get("student_risk_areas") or []):
        if isinstance(r, dict):
            risk_areas.append({
                "concept":    str(r.get("concept", "")),
                "risk_level": str(r.get("risk_level", "medium")),
                "reason":     str(r.get("reason", "")),
            })

    eff_score = data.get("teaching_effectiveness_score")
    try:
        eff_score = float(eff_score) if eff_score is not None else None
    except (TypeError, ValueError):
        eff_score = None

    return {
        # Backward compat
        "prerequisite_gaps": prereq_gaps,
        "incomplete_topics": incomplete,
        "suggested_next":    suggested,
        # New rich fields
        "session_summary":   str(data.get("session_summary") or ""),
        "topics_detected":   [str(x) for x in (data.get("topics_detected") or [])],
        "concepts_covered":  [str(x) for x in (data.get("concepts_covered") or [])],
        "pedagogical_gaps": {
            "conceptual_gaps":    [str(x) for x in (pg.get("conceptual_gaps") or [])],
            "sequencing_gaps":    [str(x) for x in (pg.get("sequencing_gaps") or [])],
            "reinforcement_gaps": [str(x) for x in (pg.get("reinforcement_gaps") or [])],
            "assessment_gaps":    [str(x) for x in (pg.get("assessment_gaps") or [])],
            "cognitive_depth_gaps":  [str(x) for x in (pg.get("cognitive_depth_gaps") or [])],
            "accessibility_gaps": [str(x) for x in (pg.get("accessibility_gaps") or [])],
        },
        "bloom_analysis": {
            "distribution":      bloom_dist,
            "dominant_level":    str(bloom_analysis.get("dominant_level") or "remember"),
            "higher_order_missing": bool(bloom_analysis.get("higher_order_missing", True)),
        },
        "classroom_metrics": {
            "concept_density":           str(classroom_metrics.get("concept_density") or ""),
            "explanation_depth":         str(classroom_metrics.get("explanation_depth") or ""),
            "example_density":           str(classroom_metrics.get("example_density") or ""),
            "assessment_density":        str(classroom_metrics.get("assessment_density") or ""),
            "curriculum_alignment_score":    _safe_int(classroom_metrics.get("curriculum_alignment_score")),
            "instructional_balance_score":   _safe_int(classroom_metrics.get("instructional_balance_score")),
            "progression_coherence_score":   _safe_int(classroom_metrics.get("progression_coherence_score")),
            "learner_readiness_score":       _safe_int(classroom_metrics.get("learner_readiness_score")),
        },
        "student_risk_areas":         risk_areas,
        "missing_prerequisites":      [str(x) for x in (data.get("missing_prerequisites") or prereq_gaps)],
        "instructional_weaknesses":   [str(x) for x in (data.get("instructional_weaknesses") or [])],
        "recommended_interventions":  [str(x) for x in (data.get("recommended_interventions") or [])],
        "suggested_next_steps":       [str(x) for x in (data.get("suggested_next_steps") or [])],
        "remediation_plan":           str(data.get("remediation_plan") or ""),
        "teaching_effectiveness_score": eff_score,
    }


def _safe_int(val: Any) -> int | None:
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------

def _validate_experiment(exp: dict, idx: int) -> dict:
    ctx = f"experiments[{idx}]"
    if not isinstance(exp, dict):
        raise ParseError(f"[{ctx}] Expected dict, got {type(exp).__name__}")
    _require_keys(exp, "title", "description", context=ctx)
    # Coerce missing fields to safe defaults
    exp.setdefault("materials", [])
    exp.setdefault("steps", [])
    exp.setdefault("topic", "")
    exp.setdefault("xperimentor_kit", None)
    exp.setdefault("expected_outcome", "")
    exp.setdefault("safety_note", "")
    diff = exp.get("difficulty", "medium")
    if diff not in EXPERIMENT_DIFFICULTIES:
        exp["difficulty"] = "medium"
    return exp


def parse_experiments(raw: str) -> list[dict]:
    if _detect_refusal(raw):
        raise RefusalError("Model refused to generate experiments")
    data = _load_json(raw)
    if not isinstance(data, list):
        raise ParseError(f"experiments must be a JSON array, got {type(data).__name__}")
    if len(data) == 0:
        raise ParseError("experiments array is empty")
    return [_validate_experiment(exp, i) for i, exp in enumerate(data)]


# ---------------------------------------------------------------------------
# Visual cards
# ---------------------------------------------------------------------------

def parse_visual_cards(raw: str) -> list[dict]:
    if _detect_refusal(raw):
        raise RefusalError("Model refused to generate visual cards")
    data = _load_json(raw)
    if not isinstance(data, list):
        raise ParseError(f"visual_cards must be a JSON array, got {type(data).__name__}")
    cards = []
    for i, card in enumerate(data):
        ctx = f"visual_cards[{i}]"
        if not isinstance(card, dict):
            raise ParseError(f"[{ctx}] Expected dict")
        _require_keys(card, "title", "content", context=ctx)
        card.setdefault("formula", None)
        card.setdefault("bloom_level", "remember")
        cards.append(card)
    return cards


# ---------------------------------------------------------------------------
# Homework suggestions
# ---------------------------------------------------------------------------

def _validate_homework(hw: dict, idx: int) -> dict:
    ctx = f"homework[{idx}]"
    if not isinstance(hw, dict):
        raise ParseError(f"[{ctx}] Expected dict")
    _require_keys(hw, "task", context=ctx)
    hw.setdefault("type", "practice")
    hw.setdefault("bloom_level", "remember")
    hw.setdefault("estimated_minutes", 15)
    hw.setdefault("topic", "")
    hw.setdefault("answer", "")
    hw.setdefault("explanation", "")
    hw_type = hw.get("type", "practice")
    if hw_type not in HOMEWORK_TYPES:
        hw["type"] = "practice"
    return hw


def parse_homework(raw: str) -> list[dict]:
    """
    Returns a list of homework task dicts.
    Each task: {"task", "type", "bloom_level", "estimated_minutes", "topic",
    "answer", "explanation"} — the last two default to "" for older cached
    outputs generated before they existed.
    """
    if _detect_refusal(raw):
        raise RefusalError("Model refused to generate homework")
    data = _load_json(raw)
    if not isinstance(data, list):
        raise ParseError(f"homework must be a JSON array, got {type(data).__name__}")
    if len(data) == 0:
        raise ParseError("homework array is empty")
    return [_validate_homework(hw, i) for i, hw in enumerate(data)]


# ---------------------------------------------------------------------------
# Analogy suggestions
# ---------------------------------------------------------------------------

def _validate_analogy(an: dict, idx: int) -> dict:
    ctx = f"analogies[{idx}]"
    if not isinstance(an, dict):
        raise ParseError(f"[{ctx}] Expected dict")
    _require_keys(an, "concept", "analogy", context=ctx)
    an.setdefault("explanation", "")
    return an


def parse_analogies(raw: str) -> list[dict]:
    """
    Returns: [{"concept": str, "analogy": str, "explanation": str}, …]
    """
    if _detect_refusal(raw):
        raise RefusalError("Model refused to generate analogies")
    data = _load_json(raw)
    if not isinstance(data, list):
        raise ParseError(f"analogies must be a JSON array, got {type(data).__name__}")
    if len(data) == 0:
        raise ParseError("analogies array is empty")
    return [_validate_analogy(an, i) for i, an in enumerate(data)]


# ---------------------------------------------------------------------------
# Lesson plan topic extraction
# ---------------------------------------------------------------------------

def parse_topic_list(raw: str) -> list[str]:
    """Returns a list of topic strings extracted from a lesson plan."""
    if _detect_refusal(raw):
        raise RefusalError("Model refused to extract topics")
    data = _load_json(raw)
    if not isinstance(data, list):
        raise ParseError(f"topic list must be a JSON array, got {type(data).__name__}")
    return [str(t).strip() for t in data if str(t).strip()]


# ---------------------------------------------------------------------------
# Lesson plan coverage analysis
# ---------------------------------------------------------------------------

def parse_combined_analysis(raw: str) -> dict:
    """
    Parses the source-split combined analysis.

    New format has five top-level keys: from_board, from_audio, from_audience,
    from_video, complete_analysis.  Old flat format is also accepted (backward
    compat for existing stored records) and promoted to the new structure.
    """
    if _detect_refusal(raw):
        raise RefusalError("Model refused to generate combined analysis")
    data = _load_json(raw)
    if not isinstance(data, dict):
        raise ParseError(f"combined_analysis must be a JSON object, got {type(data).__name__}")

    def _clamp(val, lo=0, hi=10) -> int:
        try:
            return max(lo, min(hi, int(val)))
        except (TypeError, ValueError):
            return 0

    def _parse_topics_spoken(items) -> list[dict]:
        out = []
        for item in (items or []):
            if isinstance(item, dict):
                out.append({
                    "topic": str(item.get("topic", "")),
                    "evidence": str(item.get("evidence", "")),
                    "approximate_time": str(item.get("approximate_time", "")),
                })
        return out

    def _parse_questions(items) -> list[dict]:
        out = []
        for item in (items or []):
            if isinstance(item, dict):
                out.append({
                    "question": str(item.get("question", "")),
                    "approximate_time": str(item.get("approximate_time", "")),
                    "answered": bool(item.get("answered", False)),
                })
        return out

    def _parse_pacing(raw_val) -> dict:
        if isinstance(raw_val, dict):
            return {
                "rating": str(raw_val.get("rating", "good")),
                "explanation": str(raw_val.get("explanation", "")),
            }
        return {"rating": "good", "explanation": str(raw_val or "")}

    def _parse_highlights(items) -> list[dict]:
        out = []
        for item in (items or []):
            if isinstance(item, dict):
                out.append({
                    "minute": int(item.get("minute", 0)),
                    "observation": str(item.get("observation", "")),
                    "type": str(item.get("type", "notable")),
                })
        return out

    def _parse_moments(items) -> list[dict]:
        out = []
        for item in (items or []):
            if isinstance(item, dict):
                out.append({
                    "description": str(item.get("description", "")),
                    "approximate_time": str(item.get("approximate_time", "")),
                })
        return out

    # ── Detect new source-split format ──────────────────────────────────────
    is_new_format = "complete_analysis" in data or "from_board" in data

    if is_new_format:
        fb  = data.get("from_board") or {}
        fa  = data.get("from_audio") or {}
        fau = data.get("from_audience") or {}
        fv  = data.get("from_video") or {}
        ca  = data.get("complete_analysis") or {}

        return {
            # ── Source sections ──────────────────────────────────────────────
            "from_board": {
                "frames_analysed": int(fb.get("frames_analysed") or 0),
                "topics": [str(t) for t in (fb.get("topics") or [])],
                "board_summary": str(fb.get("board_summary") or ""),
            },
            "from_audio": {
                "available": bool(fa.get("available", False)),
                "topics_spoken": _parse_topics_spoken(fa.get("topics_spoken")),
                "questions_detected": _parse_questions(fa.get("questions_detected")),
                "student_responses_detected": bool(fa.get("student_responses_detected", False)),
                "pacing": _parse_pacing(fa.get("pacing")),
                "engagement_highlights": _parse_highlights(fa.get("engagement_highlights")),
                "audio_summary": str(fa.get("audio_summary") or ""),
            },
            "from_audience": {
                "available": bool(fau.get("available", False)),
                "avg_attention_pct": fau.get("avg_attention_pct"),
                "high_attention_minutes": list(fau.get("high_attention_minutes") or []),
                "low_attention_minutes": list(fau.get("low_attention_minutes") or []),
                "audience_summary": str(fau.get("audience_summary") or ""),
            },
            "from_video": {
                "available": bool(fv.get("available", False)),
                "recording_count": int(fv.get("recording_count") or 0),
                "frames_extracted": int(fv.get("frames_extracted") or 0),
                "audio_transcribed": bool(fv.get("audio_transcribed", False)),
                "video_summary": str(fv.get("video_summary") or ""),
            },
            # ── Complete synthesis ───────────────────────────────────────────
            "complete_analysis": {
                "summary": str(ca.get("summary") or ""),
                "interactivity_score": _clamp(ca.get("interactivity_score")),
                "liveness_score": _clamp(ca.get("liveness_score")),
                "overall_score": _clamp(ca.get("overall_score")),
                "topics_on_board_not_spoken": [str(t) for t in (ca.get("topics_on_board_not_spoken") or [])],
                "topics_spoken_not_on_board": [str(t) for t in (ca.get("topics_spoken_not_on_board") or [])],
                "key_moments": _parse_moments(ca.get("key_moments")),
                "suggestions": str(ca.get("suggestions") or ""),
            },
        }

    # ── Backward compat: promote old flat format to new structure ────────────
    topics_spoken = _parse_topics_spoken(data.get("topics_spoken"))
    return {
        "from_board": {
            "frames_analysed": 0,
            "topics": [t["topic"] for t in topics_spoken],
            "board_summary": "",
        },
        "from_audio": {
            "available": bool(data.get("topics_spoken")),
            "topics_spoken": topics_spoken,
            "questions_detected": _parse_questions(data.get("questions_detected")),
            "student_responses_detected": bool(data.get("student_responses_detected", False)),
            "pacing": _parse_pacing(data.get("pacing")),
            "engagement_highlights": _parse_highlights(data.get("engagement_highlights")),
            "audio_summary": str(data.get("summary") or ""),
        },
        "from_audience": {
            "available": False,
            "avg_attention_pct": None,
            "high_attention_minutes": [],
            "low_attention_minutes": [],
            "audience_summary": "Audience mode was not used in this session.",
        },
        "from_video": {
            "available": False,
            "recording_count": 0,
            "frames_extracted": 0,
            "audio_transcribed": False,
            "video_summary": "No video recording for this session.",
        },
        "complete_analysis": {
            "summary": str(data.get("summary") or ""),
            "interactivity_score": _clamp(data.get("interactivity_score")),
            "liveness_score": _clamp(data.get("liveness_score")),
            "overall_score": _clamp(data.get("overall_score")),
            "topics_on_board_not_spoken": [str(t) for t in (data.get("topics_on_board_not_spoken") or [])],
            "topics_spoken_not_on_board": [str(t) for t in (data.get("topics_spoken_not_on_board") or [])],
            "key_moments": _parse_moments(data.get("key_moments")),
            "suggestions": str(data.get("suggestions") or ""),
        },
    }


# ---------------------------------------------------------------------------
# Lesson plan coverage analysis
# ---------------------------------------------------------------------------

def parse_lesson_plan_coverage(raw: str) -> dict:
    """
    Returns coverage analysis dict with covered/partial/missing topic lists
    and a coverage_score (0-100).
    """
    if _detect_refusal(raw):
        raise RefusalError("Model refused to generate coverage analysis")
    data = _load_json(raw)
    if not isinstance(data, dict):
        raise ParseError(f"lesson_plan_coverage must be a JSON object, got {type(data).__name__}")

    covered = []
    for item in (data.get("covered") or []):
        if isinstance(item, dict):
            covered.append({
                "topic": str(item.get("topic", "")),
                "evidence": str(item.get("evidence", "")),
            })

    partial = []
    for item in (data.get("partial") or []):
        if isinstance(item, dict):
            partial.append({
                "topic": str(item.get("topic", "")),
                "covered_aspect": str(item.get("covered_aspect", "")),
                "missing_aspect": str(item.get("missing_aspect", "")),
            })

    missing = [str(t) for t in (data.get("missing") or [])]

    teaching_notes = []
    for item in (data.get("teaching_notes") or []):
        if isinstance(item, dict):
            teaching_notes.append({
                "topic": str(item.get("topic", "")),
                "note": str(item.get("note", "")),
            })

    score = data.get("coverage_score")
    try:
        score = int(score) if score is not None else 0
        score = max(0, min(100, score))
    except (TypeError, ValueError):
        score = 0

    return {
        "lesson_plan_topics": [str(t) for t in (data.get("lesson_plan_topics") or [])],
        "covered": covered,
        "partial": partial,
        "missing": missing,
        "teaching_notes": teaching_notes,
        "coverage_score": score,
        "summary": str(data.get("summary") or ""),
        "suggestions": str(data.get("suggestions") or ""),
    }



# ---------------------------------------------------------------------------
# Absorption map (board content × audience attention)
# ---------------------------------------------------------------------------

def parse_absorption_map(raw: str) -> dict:
    """
    Returns targeted revision pack with sections per absorption level.
    {revision_sections: [{level, heading, items: [{topic, summary, detail?}]}],
     insight, replan_suggestion}
    """
    if _detect_refusal(raw):
        raise RefusalError("Model refused to generate absorption map")
    data = _load_json(raw)
    if not isinstance(data, dict):
        raise ParseError(f"absorption_map must be a JSON object, got {type(data).__name__}")

    sections = data.get("revision_sections")
    if not isinstance(sections, list):
        raise ParseError("absorption_map: missing revision_sections list")

    valid_levels = {"high", "medium", "low", "unknown"}
    clean_sections = []
    for s in sections:
        if not isinstance(s, dict):
            continue
        items = s.get("items") or []
        clean_items = []
        for item in items:
            if isinstance(item, dict) and item.get("topic"):
                ci: dict = {
                    "topic": str(item.get("topic", "")),
                    "summary": str(item.get("summary", "")),
                }
                if item.get("detail"):
                    ci["detail"] = str(item["detail"])
                clean_items.append(ci)
        level = str(s.get("level", "unknown"))
        if level not in valid_levels:
            level = "unknown"
        clean_sections.append({
            "level": level,
            "heading": str(s.get("heading", "")),
            "items": clean_items,
        })

    return {
        "revision_sections": clean_sections,
        "insight": str(data.get("insight", "")),
        "replan_suggestion": str(data.get("replan_suggestion", "")),
    }


# ---------------------------------------------------------------------------
# Session report (simple combined report)
# ---------------------------------------------------------------------------

def parse_session_report(raw: str) -> dict:
    """Flat session report combining board, audio, and video data."""
    if _detect_refusal(raw):
        raise RefusalError("Model refused to generate session report")
    data = _load_json(raw)
    if not isinstance(data, dict):
        raise ParseError(f"session_report must be a JSON object, got {type(data).__name__}")

    sources_raw = data.get("sources") or {}
    sources = {
        "board_frames": int(sources_raw.get("board_frames", 0)),
        "audio": bool(sources_raw.get("audio", False)),
    }

    return {
        "headline":         str(data.get("headline") or ""),
        "what_was_covered": str(data.get("what_was_covered") or ""),
        "how_it_went":      str(data.get("how_it_went") or ""),
        "highlights":       [str(h) for h in (data.get("highlights") or [])],
        "gaps":             [str(g) for g in (data.get("gaps") or [])],
        "next_class":       str(data.get("next_class") or ""),
        "sources":          sources,
    }


# ---------------------------------------------------------------------------
# Textbook — chapter detection
# ---------------------------------------------------------------------------

_SUPPORTED_LANGUAGE_CODES = frozenset({"en", "hi", "kn", "te", "mr", "ta"})


def parse_textbook_analysis(raw: str) -> dict:
    """Returns {language_code, language_name, subject, chapters: [{title, start_page, end_page}, ...]}."""
    if _detect_refusal(raw):
        raise RefusalError("Model refused to analyze textbook")
    data = _load_json(raw)
    if not isinstance(data, dict):
        raise ParseError(f"textbook analysis must be a JSON object, got {type(data).__name__}")

    raw_chapters = data.get("chapters")
    if not isinstance(raw_chapters, list):
        raise ParseError("textbook analysis: 'chapters' must be a JSON array")

    chapters = []
    for i, item in enumerate(raw_chapters):
        if not isinstance(item, dict):
            continue
        _require_keys(item, "title", "start_page", "end_page", context=f"chapter[{i}]")
        title = str(item["title"]).strip()
        if not title:
            continue
        try:
            start_page = int(item["start_page"])
            end_page = int(item["end_page"])
        except (TypeError, ValueError):
            continue
        if end_page < start_page:
            end_page = start_page
        chapters.append({"title": title, "start_page": start_page, "end_page": end_page})
    chapters.sort(key=lambda c: c["start_page"])

    language_code = data.get("language_code")
    if language_code not in _SUPPORTED_LANGUAGE_CODES:
        language_code = None  # "other" or missing/malformed — no matching UI locale
    language_name = str(data.get("language_name") or "").strip() or "English"
    subject = str(data.get("subject") or "").strip() or None

    return {
        "language_code": language_code,
        "language_name": language_name,
        "subject": subject,
        "chapters": chapters,
    }


def parse_concept_notes_analysis(raw: str) -> dict:
    """Returns {topic_title, language_code, language_name, subject} for a single-topic document."""
    if _detect_refusal(raw):
        raise RefusalError("Model refused to analyze document")
    data = _load_json(raw)
    if not isinstance(data, dict):
        raise ParseError(f"concept notes analysis must be a JSON object, got {type(data).__name__}")

    topic_title = str(data.get("topic_title") or "").strip()
    if not topic_title:
        raise ParseError("concept notes analysis: topic_title is empty")

    language_code = data.get("language_code")
    if language_code not in _SUPPORTED_LANGUAGE_CODES:
        language_code = None
    language_name = str(data.get("language_name") or "").strip() or "English"
    subject = str(data.get("subject") or "").strip() or None

    return {
        "topic_title": topic_title,
        "language_code": language_code,
        "language_name": language_name,
        "subject": subject,
    }


# ---------------------------------------------------------------------------
# Textbook — teaching segment
# ---------------------------------------------------------------------------

_DIAGRAM_TYPES_VALID = frozenset({"cycle", "sequence"})


def _parse_diagram_spec(raw: object) -> dict | None:
    """
    Defensive validation of a model-authored diagram_spec — this renders
    directly as an on-screen diagram for a child with no further review, so
    a malformed or oversized spec is dropped (returns None) rather than
    passed through: wrong shape, too few/many nodes, or a node that isn't
    a short plain string all just mean "no diagram this segment," never a
    hard error that would fail the whole teaching-segment call.
    """
    if not isinstance(raw, dict):
        return None
    diagram_type = raw.get("diagram_type")
    if diagram_type not in _DIAGRAM_TYPES_VALID:
        return None
    nodes_raw = raw.get("nodes")
    if not isinstance(nodes_raw, list):
        return None
    nodes = [str(n).strip() for n in nodes_raw if str(n).strip()]
    nodes = [n[:60] for n in nodes]  # a label is a few words, not a paragraph
    if not (2 <= len(nodes) <= 6):
        return None
    return {"diagram_type": diagram_type, "nodes": nodes}


_QUEST_PHASES_VALID = frozenset({"guess", "investigate", "observe", "infer"})


def parse_teaching_segment(raw: str) -> dict:
    """Returns {segment_text, taught_summary, is_last_segment, figure_id, diagram_spec, quest_phase}."""
    if _detect_refusal(raw):
        raise RefusalError("Model refused to generate teaching segment")
    data = _load_json(raw)
    if not isinstance(data, dict):
        raise ParseError(f"teaching segment must be a JSON object, got {type(data).__name__}")
    _require_keys(data, "segment_text", context="teaching_segment")

    segment_text = str(data.get("segment_text") or "").strip()
    if not segment_text:
        raise ParseError("teaching_segment: segment_text is empty")

    figure_id = data.get("figure_id")
    figure_id = str(figure_id).strip() if figure_id else None
    diagram_spec = _parse_diagram_spec(data.get("diagram_spec")) if not figure_id else None

    quest_phase = data.get("quest_phase")
    quest_phase = quest_phase if quest_phase in _QUEST_PHASES_VALID else None

    return {
        "segment_text": segment_text,
        "taught_summary": str(data.get("taught_summary") or "").strip(),
        "is_last_segment": bool(data.get("is_last_segment", False)),
        "figure_id": figure_id,
        "diagram_spec": diagram_spec,
        "quest_phase": quest_phase,
    }


def parse_figure_classification(raw: str) -> dict:
    """
    Returns {approve, caption, reason} for one candidate textbook figure.
    Fails CLOSED on any doubt — a refusal, an unparseable response, or a
    missing caption all reject the image, never approve it. This is the
    content-safety gate every extracted image passes through before it can
    be stored or shown to a student; see build_figure_classification_prompt.
    """
    if _detect_refusal(raw):
        return {"approve": False, "caption": None, "reason": "model refused to classify"}
    try:
        data = _load_json(raw)
    except ParseError:
        return {"approve": False, "caption": None, "reason": "unparseable response"}
    if not isinstance(data, dict):
        return {"approve": False, "caption": None, "reason": "unparseable response"}

    approve = bool(data.get("approve", False))
    caption = str(data.get("caption") or "").strip() or None
    if approve and not caption:
        approve = False
    return {"approve": approve, "caption": caption, "reason": data.get("reason")}


def parse_check_understanding(raw: str) -> dict:
    """Returns {question, options: list[str] (len 4), correct_index, explanation}."""
    if _detect_refusal(raw):
        raise RefusalError("Model refused to generate check-understanding question")
    data = _load_json(raw)
    if not isinstance(data, dict):
        raise ParseError(f"check-understanding must be a JSON object, got {type(data).__name__}")
    _require_keys(data, "question", "options", "correct_index", context="check_understanding")

    question = str(data.get("question") or "").strip()
    if not question:
        raise ParseError("check_understanding: question is empty")

    options_raw = data.get("options")
    if not isinstance(options_raw, list):
        raise ParseError("check_understanding: options must be a JSON array")
    options = [str(o).strip() for o in options_raw if str(o).strip()]
    if len(options) != 4:
        raise ParseError(f"check_understanding: expected exactly 4 options, got {len(options)}")

    try:
        correct_index = int(data["correct_index"])
    except (TypeError, ValueError):
        raise ParseError("check_understanding: correct_index must be an integer")
    if not (0 <= correct_index < len(options)):
        raise ParseError(f"check_understanding: correct_index {correct_index} out of range")

    return {
        "question": question,
        "options": options,
        "correct_index": correct_index,
        "explanation": str(data.get("explanation") or "").strip(),
    }


def parse_revision_recap(raw: str) -> dict:
    """Returns {points: list[str]}."""
    if _detect_refusal(raw):
        raise RefusalError("Model refused to generate revision recap")
    data = _load_json(raw)
    if not isinstance(data, dict):
        raise ParseError(f"revision recap must be a JSON object, got {type(data).__name__}")

    points_raw = data.get("points")
    if not isinstance(points_raw, list):
        raise ParseError("revision_recap: points must be a JSON array")
    points = [str(p).strip() for p in points_raw if str(p).strip()]
    if not points:
        raise ParseError("revision_recap: points is empty")

    return {"points": points}


def parse_batch_student_detection(raw: str) -> list[dict]:
    """
    Returns [{"name": str, "bbox": [x1,y1,x2,y2] (0-1000 normalized)}, ...].
    An empty list is a legitimate result (no confident detections), not an
    error — the caller decides how to surface that to the teacher.
    """
    if _detect_refusal(raw):
        raise RefusalError("Model refused to analyze the photo")
    data = _load_json(raw)
    if not isinstance(data, dict):
        raise ParseError(f"batch student detection must be a JSON object, got {type(data).__name__}")

    students_raw = data.get("students")
    if not isinstance(students_raw, list):
        raise ParseError("batch_student_detection: students must be a JSON array")

    out: list[dict] = []
    for i, item in enumerate(students_raw):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        bbox_raw = item.get("bbox")
        if not isinstance(bbox_raw, list) or len(bbox_raw) != 4:
            continue
        try:
            bbox = [float(v) for v in bbox_raw]
        except (TypeError, ValueError):
            continue
        x1, y1, x2, y2 = bbox
        if x2 <= x1 or y2 <= y1:
            continue
        # Clamp into the normalized 0-1000 space — a model can overshoot
        # slightly at a photo's edge; clamping is safer than dropping an
        # otherwise-good detection over a minor out-of-range coordinate.
        x1, y1, x2, y2 = (max(0.0, min(1000.0, v)) for v in (x1, y1, x2, y2))
        out.append({"name": name, "bbox": [x1, y1, x2, y2]})
    return out
