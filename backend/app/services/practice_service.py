"""
ThinkStep guided-practice orchestration.

  generate_practice_questions() -> question bank from a lecture session's
                                    board OCR (any subject/topic)
  process_attempt()             -> runs Gates A-H on one notebook capture

Gates D-H follow the same local-Ollama-first / OpenAI-fallback pattern as
classroom_brain_service.py and voice_intent_service.py, with the same
request-level "keep_alive": -1 fix. Gate D (deterministic) always runs
before any LLM call, per the PRD's explicit ordering — see
app/ocr/practice_engine.py.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.practice_attempt import PracticeAttempt
from app.models.practice_attempt_summary import PracticeAttemptSummary
from app.models.practice_question import PracticeQuestion
from app.models.practice_station import PracticeStation
from app.models.practice_tutor_message import PracticeTutorMessage
from app.models.session import Session
from app.ocr import practice_engine
from app.services import storage_service
from app.services.whisper_service import transcribe as whisper_transcribe

logger = logging.getLogger(__name__)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(content: str) -> dict | None:
    match = _JSON_BLOCK.search(content)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None


# =============================================================================
# Question generation — subject/topic-agnostic, from board OCR content
# =============================================================================

_GENERATE_SYSTEM_PROMPT = """You are writing guided-practice questions for a \
classroom, based on text transcribed from today's board. The subject could be \
anything — math, science, language, social studies — infer it from the content, \
don't assume math.

For EACH question, you must provide a full accepted-solution graph, because a \
separate system will validate a student's handwritten work against it — a \
question without a usable solution graph is useless downstream, so do not \
generate a question you can't also solve yourself.

Output ONLY a JSON object of this shape:
{
  "questions": [
    {
      "text": "<the question, as a student would read it>",
      "subject": "<short subject name>",
      "topic": "<short topic>",
      "difficulty": "easy" | "medium" | "hard",
      "answer_domain": "numeric" | "algebraic" | "conceptual" | "diagram" | "other",
      "expected_solution_graph": [
        {"label": "<short name for this approach, e.g. 'standard method'>",
         "steps": [{"step": "<ordered step, as a student would write it>", "description": "<why this step, for a teacher reviewing it>"}]}
      ],
      "final_answer": {"text": "<canonical final answer, plain text>"},
      "known_misconceptions": [
        {"code": "<short id, e.g. MC1>", "description": "<the misconception>", "trigger_pattern": "<what a student who has it typically writes>"}
      ]
    }
  ]
}

RULES:
- answer_domain "numeric"/"algebraic" ONLY for questions with a closed-form \
checkable expression (a specific number or algebraic equation as the answer). \
Use "conceptual" for explanation questions, "diagram" for anything requiring \
a drawn diagram, "other" otherwise. Getting this right matters — it decides \
whether a deterministic checker or only an LLM can validate the answer later.
- expected_solution_graph should include AT LEAST one alternative approach \
when a genuinely different valid method exists (e.g. two ways to solve the \
same equation) — do not force students into one canonical method. For a \
"prove/show that LHS = RHS" or identity-style question specifically, \
include separate approaches for transforming LHS toward RHS AND RHS toward \
LHS (a validator sees this graph later and must not penalize a student for \
starting from whichever side they find natural).
- A student's work gets checked against this graph with genuine exam-grade \
rigor (units, sign conventions, domain/boundary conditions, not just \
surface algebra) — so the graph itself needs that same rigor to be a fair \
standard: include units on every numeric step where units apply, note the \
sign convention in use for anything directional (force/current/displacement, \
which root of a quadratic is physical), and call out any domain restriction \
or edge case a rigorous grader would actually check (e.g. an extraneous \
root introduced by squaring, a function's valid input range). A solution \
graph that's just the bare algebra, with rigor a real exam would require \
left unstated, produces unfair grading later — the validator has nothing \
but this graph to check against.
- Ground every question in the board content actually given — do not invent \
questions about topics that weren't taught.
- Never include the final numeric/symbolic answer inside a "step" description \
in a way a student capture could accidentally leak — keep final_answer \
separate from the solution steps.
- Output ONLY the JSON object, no markdown fences, no other text."""


def _build_generate_user_prompt(ocr_text: str, subject: str | None, topic: str | None, count: int) -> str:
    header = f"Generate {count} guided-practice question(s)."
    if subject or topic:
        header += f" Context: subject={subject or 'unknown'}, topic={topic or 'unknown'}."
    return f"{header}\n\nBoard content:\n{ocr_text[:4000]}"


def _build_generate_user_prompt_from_topic(subject: str, topic: str, count: int) -> str:
    return (
        f"Generate {count} guided-practice question(s) for subject \"{subject}\", "
        f"chapter/topic \"{topic}\". No board content is available — write questions "
        f"a teacher would expect for this exact chapter/topic at a typical level for "
        f"that subject, covering a reasonable spread of sub-concepts within it rather "
        f"than {count} variations on the same narrow point."
    )


def _coerce_generated_questions(raw_questions: list, fallback_subject: str | None, fallback_topic: str | None) -> list[dict]:
    out = []
    valid_domains = {"numeric", "algebraic", "conceptual", "diagram", "other"}
    for q in raw_questions:
        if not isinstance(q, dict) or not q.get("text"):
            continue
        domain = q.get("answer_domain") if q.get("answer_domain") in valid_domains else "other"
        out.append({
            "text": str(q["text"]).strip(),
            "subject": (str(q.get("subject", "")).strip() or fallback_subject or None),
            "topic": (str(q.get("topic", "")).strip() or fallback_topic or None),
            "difficulty": q.get("difficulty") if q.get("difficulty") in ("easy", "medium", "hard") else None,
            "answer_domain": domain,
            "expected_solution_graph": q.get("expected_solution_graph") or None,
            "final_answer": q.get("final_answer") or None,
            "known_misconceptions": q.get("known_misconceptions") or None,
        })
    return out


async def _call_generate_llm(system_prompt: str, user_prompt: str, api_key: str, timeout_sec: int) -> list:
    """Shared OpenAI call + parse for both generation entry points. Returns raw 'questions' list, or []."""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        logger.warning("Practice question generation: openai client not installed")
        return []
    if not api_key:
        logger.warning("Practice question generation: no OpenAI API key configured")
        return []

    client = AsyncOpenAI(api_key=api_key)
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o",
            temperature=0.4,
            timeout=timeout_sec,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = resp.choices[0].message.content or ""
    except Exception as exc:
        logger.warning("Practice question generation: LLM call failed: %s", exc)
        return []

    data = _extract_json(content)
    if data is None:
        logger.warning("Practice question generation: unparseable output: %.200s", content)
        return []
    return data.get("questions") or []


async def generate_practice_questions(
    session: Session,
    ocr_text: str,
    count: int,
    api_key: str,
    timeout_sec: int = 60,
) -> list[dict]:
    """
    From a lecture session's already-captured board OCR content. Returns a
    list of question dicts (already validated/coerced). Empty list on any
    failure — caller treats that as "nothing generated", never raises.
    """
    if not ocr_text.strip():
        return []
    user_prompt = _build_generate_user_prompt(ocr_text, session.subject, session.title, count)
    raw_questions = await _call_generate_llm(_GENERATE_SYSTEM_PROMPT, user_prompt, api_key, timeout_sec)
    return _coerce_generated_questions(raw_questions, session.subject, session.title)


async def generate_practice_questions_from_topic(
    subject: str,
    topic: str,
    count: int,
    api_key: str,
    timeout_sec: int = 60,
) -> list[dict]:
    """
    From a teacher-typed subject + chapter/topic — no board capture needed
    first. Same output shape and validation as generate_practice_questions.
    """
    if not subject.strip() or not topic.strip():
        return []
    user_prompt = _build_generate_user_prompt_from_topic(subject.strip(), topic.strip(), count)
    raw_questions = await _call_generate_llm(_GENERATE_SYSTEM_PROMPT, user_prompt, api_key, timeout_sec)
    return _coerce_generated_questions(raw_questions, subject.strip(), topic.strip())


# =============================================================================
# Gate D router — decides whether the deterministic checker applies
# =============================================================================

def run_gate_d(step_texts: list[str], prev_step_text: str | None) -> dict | None:
    """
    Deterministic arithmetic/algebra check, in priority order. Every dict
    returned carries a "step_index" (0-based, into step_texts) pinpointing
    WHICH recognized step the result is about — the step that introduced an
    arithmetic_error, or the latest step for an arithmetically_valid result.

      1. Every consecutive pair WITHIN this capture's own recognized steps
         (most direct evidence — one photo, one derivation, already ordered
         top-to-bottom by the vision model). Covers both an equation-to-
         equation transformation and a bare result line with no repeated
         "=" (e.g. "2/3 + 1/3" then, on the next line, just "21/3") — a
         single capture's OWN steps were never checked against each other
         before, only the last step against a DIFFERENT capture's last
         step, which is exactly why a wrong bare-result line on the same
         page as its setup fell through to the LLM entirely undetected
         (confirmed root cause, reported 2026-09-16). Scans oldest to
         newest and returns the first arithmetic_error found, else the
         last arithmetically_valid result.
      2. This capture's latest step vs. the PREVIOUS capture's latest step
         — continuity across separate photos of the same ongoing attempt.
      3. The latest step alone, as a closed equation.

    Returns None when nothing above applies — Gate E/F's LLM path handles
    it instead. Never guesses.
    """
    best_valid = None
    for i in range(1, len(step_texts)):
        result = (
            practice_engine.check_step_transformation(step_texts[i - 1], step_texts[i])
            or practice_engine.check_bare_expression_equality(step_texts[i - 1], step_texts[i])
        )
        if result is None:
            continue
        result["step_index"] = i
        if result["verdict"] == "arithmetic_error":
            return result
        best_valid = result
    if best_valid is not None:
        return best_valid

    if prev_step_text and step_texts:
        result = practice_engine.check_step_transformation(prev_step_text, step_texts[-1])
        if result is not None:
            result["step_index"] = len(step_texts) - 1
            return result

    if step_texts:
        result = practice_engine.check_arithmetic_step(step_texts[-1])
        if result is not None:
            result["step_index"] = len(step_texts) - 1
        return result
    return None


# =============================================================================
# Gates E/F — solution-path validation + misconception classification
# =============================================================================

_VALIDATE_SYSTEM_PROMPT = """You are validating a student's handwritten step \
against a known accepted-solution graph, for a Socratic guided-practice tool. \
You are NOT tutoring the student directly — you are classifying their work so \
a separate hint system can decide what to say.

Classify the student's work into EXACTLY one of these categories, considering
ALL their recognized steps together (not just the last one):
- "solved": the steps actually REACH the final answer given to you below —
  not just a correct step along the way, the work is done. Check this
  explicitly; don't default to "valid_progress" just because every step so
  far is correct — if the last step states/matches the final answer (or an
  equivalent form of it), that's "solved", not "valid_progress".
  For a "conceptual"/explanation-style answer domain specifically, apply the
  SAME rigor you would to a numeric answer, not a looser standard just
  because it's prose: "solved" requires the explanation to cover the actual
  required components of a correct answer (the key terms/steps/causal links
  the question is asking for), correctly and without a material error or
  omission — being generally on-topic, using the right vocabulary, or
  covering ONE of several required parts is "valid_progress" or
  "incomplete", not "solved". A confident-sounding but incomplete or
  partly-wrong explanation is a false "solved" (a real, reported failure
  mode) — resist grading on tone/fluency instead of actual content.
- "valid_progress": a correct step following the expected approach, but the
  final answer has NOT been reached yet
- "alternative_valid_method": correct, but following a different valid approach than the canonical one
- "incomplete": correct so far but doesn't yet resolve anything
- "arithmetic_slip": right approach, wrong calculation
- "conceptual_misconception": applies an incorrect concept (matches a known misconception if one fits)
- "ambiguous": you genuinely cannot tell from what's given (illegible, off-topic, insufficient work shown)
- "unsupported": the approach shown isn't in the accepted solution graph and isn't a recognizable valid alternative

For a "prove/show that LHS = RHS" or identity-style question: the student
may validly start from EITHER side and transform it toward the other, or
manipulate both sides at once — this is true regardless of which direction
the accepted solution graph happens to list first. Never classify a
correct step as "unsupported" or "conceptual_misconception" merely because
it starts from the opposite side of the identity than the solution graph's
first-listed approach does; judge whether the ALGEBRA/reasoning is valid,
not which side it started from.

Grade with the rigor of a competitive-exam evaluator (JEE/IIT-entrance
level), not a lenient pattern-match against the solution graph's exact
wording:
- Check dimensional/unit consistency explicitly where units are involved —
  a numerically-plausible answer with the wrong units, or an equation that
  doesn't balance dimensionally, is arithmetic_slip or conceptual_misconception,
  not valid_progress.
- Watch sign conventions (direction of forces/current/displacement,
  exothermic vs endothermic, which root of a quadratic is physical) — a
  flipped sign that changes the physical meaning of the answer is a real
  error, not a rounding-level nitpick to overlook.
- Check boundary/edge cases the accepted solution graph implies but may not
  spell out (domain restrictions on a function, extraneous roots introduced
  by squaring both sides, a physically impossible negative
  mass/time/probability) — a step that's algebraically consistent but
  produces a physically or mathematically invalid result downstream is
  still wrong, and the earliest step that let it through is the one to
  flag, not the final absurd answer.
- A method that's "close" to the accepted approach but skips a
  justification a rigorous grader would require (e.g. asserting a limit
  exists without showing continuity, or applying a formula outside its
  valid domain) is "incomplete", not "valid_progress" — silently assuming
  a step JEE-level grading would actually dock is generosity the student
  won't get in a real exam.
- This rigor cuts both ways: apply it to catch real errors, but don't
  manufacture pedantry — a step that's genuinely equivalent to the
  accepted one (different but valid simplification, an unstated-but-
  standard assumption like "g = 9.8 m/s²" for a mechanics problem) is
  still correct. When genuinely unsure whether something crosses the line
  into a real error, prefer "ambiguous" over guessing wrong in either
  direction, per the rule below.

If the status is arithmetic_slip, conceptual_misconception, or unsupported,
you must also PINPOINT which recognized step (its index, from the numbered
list given to you) is where the error FIRST appears — not every step
downstream of it, just the root cause. Everything from that step onward is a
consequence, not a separate error to also flag.

If the error is "arithmetic_slip" AND it's specifically a carry/borrow
mistake in column-aligned addition or subtraction (digits stacked by place
value — ones/tens/hundreds/...), also identify WHICH row and place-value
column the error is actually in, so the mistake can be pointed at precisely
instead of just circling the whole line. Reason about this the way a person
checking the work would — which column's carry or borrow doesn't match what
the digits actually require — not the nearest visible gap on the page.
Include this ONLY when you're actually confident which column it is; leave
it out entirely for anything else (a non-arithmetic error, an error not
about carrying/borrowing, or genuine uncertainty about the column) — a
wrong column pointed at confidently is worse than no column at all.

Output ONLY a JSON object:
{
  "validation_status": "<one of the categories above>",
  "error_step_index": <integer index of the step where the error first appears, or null if there is no error to point at>,
  "misconception_code": "<code from known_misconceptions if conceptual_misconception, else null>",
  "reason_code": "<short machine-friendly snake_case reason>",
  "confidence": <0-100 int, your certainty in this classification>,
  "column_hint": {"row": "operand_1"|"operand_2"|"answer"|"carry", "column": "ones"|"tens"|"hundreds"|"thousands"|"tenths"|"hundredths"} or null
}

RULES:
- Prefer "ambiguous" over guessing. A wrong "arithmetic_slip" or \
"conceptual_misconception" call is a FALSE ACCUSATION — much worse than \
saying ambiguous and asking for a clearer capture.
- error_step_index must be one of the indices actually given to you, or null \
— never a step number that wasn't in the list, never a guess when you're not \
confident which step is the real root cause (use null rather than guess).
- If a deterministic check result is provided, treat it as ground truth for \
whatever it covers (including its own step_index AND its own column_hint, \
if it has one) and do not contradict it.
- Output ONLY the JSON object, no markdown fences, no other text."""


def _build_validate_prompt(
    question: PracticeQuestion,
    recognized_steps: list[dict],
    gate_d_result: dict | None,
) -> str:
    lines = [f"Question: {question.text}", f"Answer domain: {question.answer_domain}"]
    if question.final_answer:
        lines.append(
            f"Final answer — check explicitly whether the student's steps actually "
            f"reach this (that's \"solved\", not just \"valid_progress\"): "
            f"{json.dumps(question.final_answer)[:500]}"
        )
    else:
        lines.append(
            "No canonical final answer was recorded for this question. Do NOT let "
            "that make \"solved\" easier to reach — if anything, be MORE conservative "
            "without one to check against: only classify as \"solved\" when the "
            "steps are unambiguously complete and directly answer what was asked, "
            "not merely on-topic or partially correct. When genuinely unsure, prefer "
            "\"valid_progress\" or \"incomplete\" over \"solved\"."
        )
    if question.expected_solution_graph:
        lines.append(f"Accepted solution graph: {json.dumps(question.expected_solution_graph)[:2000]}")
    if question.known_misconceptions:
        lines.append(f"Known misconceptions: {json.dumps(question.known_misconceptions)[:1000]}")
    numbered_steps = [f"{i}: {s.get('text')}" for i, s in enumerate(recognized_steps)]
    lines.append("Student's recognized steps, numbered in order:\n" + "\n".join(numbered_steps))
    if gate_d_result:
        lines.append(f"Deterministic check (ground truth for what it covers): {json.dumps(gate_d_result)}")
    return "\n".join(lines)


async def _validate_local(prompt: str, base_url: str, model: str, timeout: int) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{base_url}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": _VALIDATE_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "options": {"temperature": 0},
                    "keep_alive": -1,
                },
            )
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content", "")
    except Exception as exc:
        logger.warning("Practice validate: local Ollama call failed: %s", exc)
        return None
    return _extract_json(content)


async def _validate_cloud(prompt: str, api_key: str, timeout: int) -> dict | None:
    try:
        from openai import AsyncOpenAI
    except ImportError:
        return None
    client = AsyncOpenAI(api_key=api_key)
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o",
            temperature=0,
            timeout=timeout,
            messages=[
                {"role": "system", "content": _VALIDATE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        content = resp.choices[0].message.content or ""
    except Exception as exc:
        logger.warning("Practice validate: OpenAI fallback failed: %s", exc)
        return None
    return _extract_json(content)


_VALID_STATUSES = {
    "solved", "valid_progress", "alternative_valid_method", "incomplete",
    "arithmetic_slip", "conceptual_misconception", "ambiguous", "unsupported",
}

_VALID_COLUMN_HINT_ROWS = {"operand_1", "operand_2", "answer", "carry"}
# practice_engine._PLACE_VALUE_NAMES covers ones..ten_thousands for the CV
# pixel-targeting side (locate_arithmetic_column); tenths/hundredths are
# accepted here too since the LLM path's semantic reasoning can still name
# a decimal column correctly even though that CV lookup doesn't target it
# yet (see locate_arithmetic_column's own docstring).
_VALID_COLUMN_HINT_COLUMNS = {
    "ones", "tens", "hundreds", "thousands", "ten_thousands", "tenths", "hundredths",
}


def _parse_column_hint(raw: object) -> dict | None:
    """Validates an LLM-proposed column_hint against the known row/column
    vocabulary — a hallucinated row/column name (or malformed shape) is
    discarded rather than passed through, same "don't trust a free-form
    guess" spirit as error_step_index's own range check just below."""
    if not isinstance(raw, dict):
        return None
    row, column = raw.get("row"), raw.get("column")
    if row not in _VALID_COLUMN_HINT_ROWS or column not in _VALID_COLUMN_HINT_COLUMNS:
        return None
    return {"row": row, "column": column}


async def validate_step(
    question: PracticeQuestion,
    recognized_steps: list[dict],
    gate_d_result: dict | None,
    *,
    ollama_base_url: str,
    ollama_model: str,
    openai_api_key: str,
    local_enabled: bool,
    timeout_sec: int = 30,
) -> dict:
    """
    Gates E/F combined. Returns {"validation_status", "error_step_index",
    "misconception_code", "reason_code", "confidence" (0-1),
    "source": "deterministic"|"local"|"cloud"|"none", "column_hint"}.

    A Gate D verdict of "arithmetic_error" short-circuits straight to
    arithmetic_slip without an LLM call at all — the PRD requires Gate D
    results to be treated as ground truth, not re-litigated by the LLM.
    Gate D's own step_index carries straight through as error_step_index —
    it already knows exactly which step failed. Same for column_hint, when
    Gate D's own digit comparison found one (see check_arithmetic_step/
    check_bare_expression_equality) — pure math, more reliable than
    anything the LLM path below could independently determine.
    """
    if gate_d_result and gate_d_result.get("applicable"):
        if gate_d_result["verdict"] == "arithmetic_error":
            return {
                "validation_status": "arithmetic_slip",
                "error_step_index": gate_d_result.get("step_index"),
                "misconception_code": None,
                "reason_code": "deterministic_arithmetic_error",
                "confidence": 1.0,
                "source": "deterministic",
                "column_hint": gate_d_result.get("column_hint"),
            }
        # arithmetically_valid on its own doesn't prove the STRATEGY is
        # right (e.g. correctly simplifying a step that's still off the
        # accepted approaches) — still route through the LLM, but hand it
        # the Gate D result so it knows the arithmetic itself already checks out.

    prompt = _build_validate_prompt(question, recognized_steps, gate_d_result)

    result = await _validate_local(prompt, ollama_base_url, ollama_model, timeout_sec) if local_enabled else None
    source = "local"
    if result is None and openai_api_key:
        result = await _validate_cloud(prompt, openai_api_key, timeout_sec)
        source = "cloud"
    if result is None:
        return {
            "validation_status": "ambiguous",
            "error_step_index": None,
            "misconception_code": None,
            "reason_code": "validator_unavailable",
            "confidence": 0.0,
            "source": "none",
            "column_hint": None,
        }

    status = result.get("validation_status")
    if status not in _VALID_STATUSES:
        status = "ambiguous"
        reason = "unparseable_status"
    else:
        reason = str(result.get("reason_code", "")).strip() or None

    confidence = result.get("confidence", 0)
    try:
        confidence = max(0.0, min(1.0, float(confidence) / 100.0))
    except (TypeError, ValueError):
        confidence = 0.5

    misconception_code = result.get("misconception_code")
    if status != "conceptual_misconception":
        misconception_code = None

    # Only meaningful for statuses that ARE an error to point at — a step
    # index attached to "valid_progress"/"incomplete"/"ambiguous" would be
    # noise, not a pinpoint. Also validated against the actual step count so
    # a hallucinated out-of-range index never reaches the frontend.
    error_step_index = None
    if status in ("arithmetic_slip", "conceptual_misconception", "unsupported"):
        raw_index = result.get("error_step_index")
        try:
            idx = int(raw_index)
            if 0 <= idx < len(recognized_steps):
                error_step_index = idx
        except (TypeError, ValueError):
            error_step_index = None

    # Only meaningful alongside an actual arithmetic_slip pinpoint — a
    # column_hint on any other status (or with no error_step_index at all)
    # would have nothing to anchor to.
    column_hint = None
    if status == "arithmetic_slip" and error_step_index is not None:
        column_hint = _parse_column_hint(result.get("column_hint"))

    return {
        "validation_status": status,
        "error_step_index": error_step_index,
        "misconception_code": misconception_code,
        "column_hint": column_hint,
        "reason_code": reason,
        "confidence": round(confidence, 3),
        "source": source,
    }


# =============================================================================
# Student state model (§6) — deterministic, not an LLM judgment call
# =============================================================================

# validation_status -> ("intrinsic" state assuming this is a fresh attempt,
# i.e. before factoring in repeated-attempt streaks)
#
# "incomplete" maps to progressing, not a lesser state: it means "correct so
# far, doesn't resolve anything YET" per the Gate E/F prompt's own definition
# — with a station auto-capturing every 10-20s, a student mid-way through a
# normal multi-step solution produces several genuinely "incomplete" captures
# in a row purely because they're not done writing, not because they're
# stuck. Treating that as evidence of struggle was a real bug (caught
# 2026-09-11 from real Pi usage): it escalated a student who was correctly,
# steadily working through a problem straight to "your teacher will look
# into this" within under a minute, with no way back.
#
# "solved" is deliberately its OWN state, distinct from "progressing" — the
# original categories had no way to say "the final answer was actually
# reached," only "a correct step," so a fully-solved attempt kept reading as
# generic ongoing progress forever (reported 2026-09-17). Gate E/F is told
# the question's final_answer explicitly and must check for it, not infer
# "solved" from "every step so far was correct."
_STATE_FOR_STATUS = {
    "solved": "solved",
    "valid_progress": "progressing",
    "alternative_valid_method": "progressing",
    "incomplete": "progressing",
    "ambiguous": "ambiguous",
    "arithmetic_slip": "stuck",
    "conceptual_misconception": "misconception",
    "unsupported": "teacher_required",
}

# Only these represent the student actually having gotten something wrong —
# these are the only statuses that should count toward the escalating-help
# streak. "incomplete" (still working) and "ambiguous" (a capture/relevance
# problem, not evidence about the student's work) are neutral: they neither
# advance nor reset the streak, they're just skipped.
_MISTAKE_STATUSES = frozenset({"arithmetic_slip", "conceptual_misconception", "unsupported"})


def derive_student_state(validation_status: str, help_streak: int) -> str:
    """
    help_streak = consecutive prior attempts on this question that were
    genuine mistakes (see _MISTAKE_STATUSES) — NOT every non-progressing
    attempt, since "incomplete"/"ambiguous" aren't evidence of struggling.
    """
    if help_streak >= 4 and validation_status not in ("solved", "valid_progress", "alternative_valid_method", "incomplete", "ambiguous"):
        return "teacher_required"
    return _STATE_FOR_STATUS.get(validation_status, "ambiguous")


def select_hint_level(validation_status: str, help_streak: int) -> int:
    """
    L0 (silence) through L5 (teacher handoff). Deterministic per the PRD's
    "use the lowest level likely to restart reasoning" default rule — the
    LLM only phrases the content at whatever level this function picks, it
    never picks the level itself.
    """
    if validation_status in ("solved", "valid_progress", "alternative_valid_method"):
        return 0
    if validation_status == "unsupported":
        return 5
    if validation_status in ("incomplete", "ambiguous"):
        # Still working, or a capture problem — neither is a mistake to nudge
        # about. Stay silent rather than interrupting a student who's simply
        # not finished yet, or nagging about a photo that just needs a retake.
        return 0
    if help_streak >= 4:
        return 5
    # arithmetic_slip/conceptual_misconception ramp 1->4 on genuine mistakes
    return min(help_streak + 1, 4)


# =============================================================================
# Gate G — hint generation, then a SEPARATE leakage-guard pass
# =============================================================================

_HINT_LEVEL_NAMES = {
    1: "L1 metacognitive prompt — ask the student to check their own work, no new information",
    2: "L2 concept cue — name the concept they need without applying it for them",
    3: "L3 targeted procedural cue — point at the specific procedure/step without doing it",
    4: "L4 analogous micro-example — a DIFFERENT simpler example illustrating the same concept",
}

_HINT_SYSTEM_PROMPT = """You write a single short hint for a student stuck on a \
guided-practice question. You must generate a hint at EXACTLY the level given \
— do not escalate or de-escalate it yourself.

RULES:
- Never state the final answer or a numerically/symbolically equivalent form of it.
- Never write out the next correct step for them — nudge toward finding it themselves.
- One or two sentences. Plain, encouraging, age-appropriate language.
- If misconception info is given, target THAT misconception specifically.

Output ONLY a JSON object: {"hint_text": "<the hint>"}
Output ONLY the JSON object, no markdown fences, no other text."""

_LEAKAGE_SYSTEM_PROMPT = """You are a safety check. Given a question's final \
answer and a candidate hint that's about to be shown to a student, determine \
whether the hint reveals the final answer — directly, or in an equivalent \
form (a paraphrase, a numerically equal value, a fully-worked next step that \
trivially completes the problem).

Output ONLY a JSON object: {"leaks_answer": true|false, "reason": "<short reason>"}
Be strict — when genuinely unsure, say leaks_answer: true. A rejected safe \
hint costs nothing; a leaked answer defeats the entire point of this tool.
Output ONLY the JSON object, no markdown fences, no other text."""


async def _llm_call(system_prompt: str, user_prompt: str, *, ollama_base_url, ollama_model,
                     openai_api_key, local_enabled, timeout_sec) -> tuple[dict | None, str]:
    result = None
    source = "local"
    if local_enabled:
        try:
            async with httpx.AsyncClient(timeout=timeout_sec) as client:
                resp = await client.post(
                    f"{ollama_base_url}/api/chat",
                    json={
                        "model": ollama_model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "stream": False,
                        "options": {"temperature": 0.3},
                        "keep_alive": -1,
                    },
                )
                resp.raise_for_status()
                content = resp.json().get("message", {}).get("content", "")
                result = _extract_json(content)
        except Exception as exc:
            logger.warning("Practice LLM call: local failed: %s", exc)
            result = None
    if result is None and openai_api_key:
        source = "cloud"
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=openai_api_key)
            resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0.3,
                timeout=timeout_sec,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            result = _extract_json(resp.choices[0].message.content or "")
        except Exception as exc:
            logger.warning("Practice LLM call: cloud fallback failed: %s", exc)
            result = None
    if result is None:
        source = "none"
    return result, source


async def generate_hint(
    question: PracticeQuestion,
    hint_level: int,
    validation: dict,
    *,
    ollama_base_url: str,
    ollama_model: str,
    openai_api_key: str,
    local_enabled: bool,
    timeout_sec: int = 20,
) -> dict:
    """Returns {"hint_text": str, "source": str}. hint_level must be 1-4 (L0/L5 handled by the caller)."""
    if hint_level not in _HINT_LEVEL_NAMES:
        return {"hint_text": "", "source": "none"}

    misconception = None
    if validation.get("misconception_code") and question.known_misconceptions:
        misconception = next(
            (m for m in question.known_misconceptions if m.get("code") == validation["misconception_code"]),
            None,
        )
    user_prompt = (
        f"Question: {question.text}\n"
        f"Hint level to write: {_HINT_LEVEL_NAMES[hint_level]}\n"
        f"Student's situation: {validation.get('validation_status')}"
        + (f", misconception: {misconception}" if misconception else "")
    )

    result, source = await _llm_call(
        _HINT_SYSTEM_PROMPT, user_prompt,
        ollama_base_url=ollama_base_url, ollama_model=ollama_model,
        openai_api_key=openai_api_key, local_enabled=local_enabled, timeout_sec=timeout_sec,
    )
    hint_text = (result or {}).get("hint_text", "").strip() if result else ""
    return {"hint_text": hint_text, "source": source}


async def check_hint_leakage(
    question: PracticeQuestion,
    hint_text: str,
    *,
    ollama_base_url: str,
    ollama_model: str,
    openai_api_key: str,
    local_enabled: bool,
    timeout_sec: int = 20,
) -> bool:
    """
    Second, SEPARATE pass — the PRD requires this not be the same call that
    generated the hint. Returns True (leak detected — caller must not show
    this hint) on any failure/uncertainty, never False by default.
    """
    if not hint_text:
        return False
    user_prompt = (
        f"Question: {question.text}\n"
        f"Final answer: {json.dumps(question.final_answer) if question.final_answer else '(not specified)'}\n"
        f"Candidate hint: {hint_text}"
    )
    result, source = await _llm_call(
        _LEAKAGE_SYSTEM_PROMPT, user_prompt,
        ollama_base_url=ollama_base_url, ollama_model=ollama_model,
        openai_api_key=openai_api_key, local_enabled=local_enabled, timeout_sec=timeout_sec,
    )
    if result is None:
        logger.warning("Practice leakage check unavailable (source=%s) — failing closed", source)
        return True
    return bool(result.get("leaks_answer", True))


# =============================================================================
# Classroom Brain chat — a student asking about their active question
# =============================================================================

_CHAT_SYSTEM_PROMPT = """You are the Classroom Brain, a friendly study buddy \
helping ONE student with ONE specific guided-practice question. They may ask \
you about it at any time.

RULES:
- Help with THIS question, the concept it's testing, and any term or idea a \
  student would reasonably need to answer it (e.g. defining a term the \
  question itself relies on IS on-topic). Only decline when they ask \
  something with no real connection to this question — another subject, a \
  different question, personal questions, general chit-chat. Politely \
  decline those in one short sentence and point them back to this question, \
  without answering the off-topic part even partially.
- Never state the final answer to this question, or a numerically/symbolically \
  equivalent form of it.
- Never write out the next correct step for them — explain the concept and \
  nudge them toward finding the step themselves.
- Keep it short: 1-3 sentences, plain, encouraging, age-appropriate language.

You must also self-report whether you just declined. Set "declined" to true \
ONLY when their message had no real connection to this question and your \
reply is a redirect for that reason. A genuine clarifying question about a \
term/concept THIS question depends on is on-topic — "declined" must be false \
for that, even though you're not handing them the final answer.

Output ONLY a JSON object: {"reply": "<your reply>", "declined": true|false}
Output ONLY the JSON object, no markdown fences, no other text."""

_CHAT_FALLBACK_REPLY = "I couldn't think that through just now — try asking again in a moment."
_CHAT_LEAK_FALLBACK_REPLY = "I can't just hand you the answer to this one — try working through it, and ask me about a specific step instead."


async def answer_question(
    question: PracticeQuestion,
    student_message: str,
    *,
    ollama_base_url: str,
    ollama_model: str,
    openai_api_key: str,
    local_enabled: bool,
    timeout_sec: int = 20,
) -> dict:
    """
    Returns {"reply": str, "declined": bool}. `declined` is True when the
    model judged the student's message off-topic for this question — never
    an empty reply either way, since a silent failure here reads to the
    student as the Brain ignoring them.
    """
    user_prompt = (
        f"Question: {question.text}\n"
        f"Subject/topic: {question.subject or '(not set)'} / {question.topic or '(not set)'}\n"
        f"Student's message: {student_message}"
    )
    result, source = await _llm_call(
        _CHAT_SYSTEM_PROMPT, user_prompt,
        ollama_base_url=ollama_base_url, ollama_model=ollama_model,
        openai_api_key=openai_api_key, local_enabled=local_enabled, timeout_sec=timeout_sec,
    )
    if not result or not result.get("reply"):
        logger.warning("Practice chat: LLM unavailable (source=%s)", source)
        return {"reply": _CHAT_FALLBACK_REPLY, "declined": False}

    reply = str(result["reply"]).strip()
    declined = bool(result.get("declined", False))

    # Same leakage guard as hints (Gate G) — a SEPARATE pass, not the same
    # call that wrote the reply, matching the existing "never trust one
    # pass" rule for anything that could hand over the answer. Only runs
    # when there's an actual final_answer to check against: without one,
    # check_hint_leakage has nothing concrete to compare the reply to, and
    # its own "when unsure, say leaked" rule then fails closed on nearly
    # any substantive reply — exactly the common case for a conceptual
    # "explain in your own words" question, which has no single final_answer
    # by design. The main chat prompt's own "never state the final answer"
    # rule is what's actually carrying the guardrail for those questions.
    if not declined and question.final_answer:
        leaked = await check_hint_leakage(
            question, reply,
            ollama_base_url=ollama_base_url, ollama_model=ollama_model,
            openai_api_key=openai_api_key, local_enabled=local_enabled, timeout_sec=timeout_sec,
        )
        if leaked:
            reply = _CHAT_LEAK_FALLBACK_REPLY

    return {"reply": reply, "declined": declined}


# =============================================================================
# AI Tutor (Learning mode) — a live voice+vision conversation
# =============================================================================
# Genuinely different shape from everything else in this file: vision-capable
# (stays on OpenAI unconditionally, same rule as every other vision call in
# this app — the local model isn't vision-capable) and multi-turn (the ONE
# place in the whole app that is — see PracticeTutorMessage's docstring for
# why conversation state is still handled statelessly server-side).

_TUTOR_SYSTEM_PROMPT = """You are a friendly, patient AI tutor helping ONE student \
who has their notebook or textbook page open in front of a camera. You can see \
that page in the photo attached to their latest message, if one is attached.

HOW TO TUTOR:
- Look at what's actually on the page and ground your help in it — refer to what \
they've written or what the page shows, don't give a generic explanation that \
could apply to any page.
- Never just give the final answer on the student's first attempt or two — ask a \
guiding question first, or explain the underlying concept, and let the student take \
the next step themselves. HOWEVER: if the context below tells you they're several \
exchanges into this question AND their latest message is explicitly asking for the \
answer outright or signals they've given up ("just tell me", "I don't know", "give \
up", "what's the answer", etc.) — give it to them. Don't keep withholding it from a \
student who has genuinely tried and is now directly asking; that's not good \
tutoring, it's just being unhelpful. When you do this, always include THREE things \
in the same reply: (1) the correct final answer stated plainly, (2) a clear \
explanation of WHY it's correct — the actual reasoning/concept, not just the \
number or fact restated, and (3) a concrete worked example or real-life \
application that illustrates it. A bare answer with no explanation is still a bad \
reply even once you've decided to give it.
- After explaining something, check whether it landed — ask a short, genuine \
follow-up like "does that make sense?" or "want to try the next part?" rather \
than just moving on to more material unprompted.
- If the student's reply signals they're still confused (says they don't get it, \
asks you to repeat, or gives a reply that doesn't show understanding), do NOT repeat \
the same explanation in different words — switch strategy. Pick whichever of these \
fits best and hasn't already been tried in this conversation: (a) a simpler, more \
basic restatement, (b) a concrete worked example with different numbers/details, \
(c) a real-life analogy or application. Varying the approach matters — repeating an \
explanation that already didn't land is the single most common way a tutor loses a \
student.
- Keep it conversational and short — 1-4 sentences per turn, plain language, \
age-appropriate, like a real tutor talking, not a textbook.
- If the photo is blank, blurry, or clearly doesn't match what the student is asking \
about, say so plainly and ask them to show you the right page again — don't guess at \
content you can't actually read.

Output ONLY a JSON object: {"reply": "<your spoken reply>"}
Output ONLY the JSON object, no markdown fences, no other text."""

_TUTOR_FALLBACK_REPLY = "I couldn't quite think that through just now — try asking again in a moment."


async def _transcribe_tutor_audio(audio_bytes: bytes, filename: str, settings) -> str:
    """
    Cloud Whisper ONLY — deliberately NOT the local-whisper-first pattern
    _transcribe_command (routers/voice.py) uses, even though this function
    used to mirror it (reported 2026-09-24: "I didn't catch that" firing
    the majority of the time — this was the actual root cause, not just
    the min_duration_sec gap fixed alongside it earlier).

    local_whisper_enabled defaults to True (see config.py) and is
    explicitly scoped there to the VOICE COMMAND path only: "Deliberately
    NOT used for the long-form lecture-recording pipeline — that path
    leans on OpenAI's per-segment no_speech_prob/avg_logprob confidence
    scores for hallucination filtering, which whisper.cpp's basic
    /inference response doesn't provide. Short, deliberate command
    utterances don't need that same guard; long recordings still do." A
    free-form conversational reply to the AI Tutor is squarely on the
    "long recordings still do" side of that line, same as
    process_attempt's own spoken-answer path (which this now matches) —
    it's real, variable speech content that needs Whisper's actual
    confidence-based silence/hallucination filtering, not a fixed-
    vocabulary short command. Routing it through local whisper meant every
    turn got whatever whisper.cpp's weaker, GPU-less, filter-less
    transcription produced, with no cloud fallback when that was wrong —
    exactly the "majority of the time" failure reported.

    min_duration_sec=0.5: same override process_attempt's audio-answer
    path applies, and for the same reason — whisper_transcribe's module
    default (2.0s) silently blanks anything shorter, and a real
    VAD-stopped conversational reply ("yes", "no", "I don't get it")
    routinely lands under 2s.
    """
    result = await whisper_transcribe(
        audio_bytes, filename, settings.openai_api_key, settings.whisper_language or None,
        min_duration_sec=0.5, timeout_sec=25.0,
    )
    return result.text


async def tutor_turn(
    db: AsyncSession,
    station,
    question: PracticeQuestion | None,
    history: list[dict],
    audio_bytes: bytes,
    image_bytes: bytes | None,
    *,
    settings,
) -> dict:
    """
    One turn of the Learning-mode AI Tutor conversation: transcribe the
    student's audio, ask the vision model (grounded in the latest frame +
    running history), persist both turns, return the reply for the caller
    to speak back (via the existing /voice/speak endpoint — this function
    does not do TTS itself).

    `history` is the conversation so far, sent by the client each call —
    [{"role": "student"|"tutor", "text": str}, ...]. Returns
    {"transcript": str, "reply": str}. Never raises for "the model didn't
    answer" — falls back to a plain, honest reply instead of silently
    failing, matching answer_question's own fallback behavior.
    """
    transcript = await _transcribe_tutor_audio(audio_bytes, "tutor-turn.webm", settings)

    reply = _TUTOR_FALLBACK_REPLY
    if not transcript.strip():
        reply = "I didn't catch that — try again?"
    elif not settings.openai_api_key:
        reply = "I can't see or think right now — the AI connection isn't set up. Let your teacher know."
    else:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            reply = "I can't see or think right now — try again in a moment."
        else:
            image_bgr = None
            if image_bytes:
                import cv2
                import numpy as np
                arr = np.frombuffer(image_bytes, np.uint8)
                image_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if image_bgr is not None:
                    # Fixed mount correction first (only a no-op unless this
                    # station is desk-mounted), then the best-effort OSD
                    # rotation guess — OSD reads more reliably once the
                    # gross 90°+mirror from an overhead mount is already
                    # undone. Same cardinal-rotation correction as the
                    # graded-attempt path — a student holding a notebook or
                    # textbook at a tilt under the camera is exactly as
                    # common here as it is for a photographed attempt.
                    image_bgr = practice_engine.apply_mount_correction(image_bgr, station.camera_mount)
                    image_bgr = practice_engine.auto_orient(image_bgr)

            b64 = None
            if image_bgr is not None:
                try:
                    b64 = practice_engine.encode_for_vision(image_bgr)
                except Exception as exc:
                    logger.warning("Tutor turn: image encode failed: %s", exc)

            context_lines = []
            if question is not None:
                context_lines.append(f"The student's assigned question right now: {question.text}")
                context_lines.append(
                    f"Subject/topic: {question.subject or '(not set)'} / {question.topic or '(not set)'}"
                )
                # +1 accounts for the current turn, which isn't in `history`
                # yet (history is everything BEFORE this exchange).
                student_turn_number = sum(1 for h in history if h.get("role") == "student") + 1
                if student_turn_number >= 2:
                    # Several exchanges in — the reveal-if-asked rule above
                    # can apply. Only NOW hand the model the actual answer:
                    # for the first turn or two it's deliberately kept OUT
                    # of the prompt entirely (defense in depth, same reason
                    # answer_question() does this) so an eager model can't
                    # leak it before the student has genuinely tried.
                    context_lines.append(
                        f"This is the student's turn #{student_turn_number} on this question — "
                        f"they've already had a couple of exchanges. If their latest message is "
                        f"asking for the answer outright or signals they've given up, you're now "
                        f"authorized to give it per the rules above (answer + explanation + example)."
                    )
                    if question.final_answer:
                        context_lines.append(
                            f"Correct final answer — reference ONLY, don't state it unless the reveal "
                            f"conditions above are actually met: {json.dumps(question.final_answer)[:500]}"
                        )
                    if question.expected_solution_graph:
                        context_lines.append(
                            f"Accepted solution approach — same reveal-only caveat: "
                            f"{json.dumps(question.expected_solution_graph)[:2000]}"
                        )
                else:
                    context_lines.append(
                        f"This is the student's turn #{student_turn_number} on this question — "
                        f"keep guiding, it's too early to reveal the answer even if asked."
                    )
            else:
                context_lines.append(
                    "No specific question is assigned yet — the student is exploring/asking about whatever's on the page."
                )

            messages: list[dict] = [
                {"role": "system", "content": _TUTOR_SYSTEM_PROMPT + "\n\n" + "\n".join(context_lines)}
            ]
            for turn in history:
                role = "assistant" if turn.get("role") == "tutor" else "user"
                text = str(turn.get("text", "")).strip()
                if text:
                    messages.append({"role": role, "content": text})

            if b64:
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": transcript},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"}},
                    ],
                })
            else:
                messages.append({"role": "user", "content": transcript})

            client = AsyncOpenAI(api_key=settings.openai_api_key)
            try:
                resp = await client.chat.completions.create(
                    model="gpt-4o", temperature=0.5, timeout=30, messages=messages,
                )
                content = resp.choices[0].message.content or ""
                data = _extract_json(content)
                parsed_reply = str((data or {}).get("reply", "")).strip()
                if parsed_reply:
                    reply = parsed_reply
            except Exception as exc:
                logger.warning("Tutor turn: vision call failed: %s", exc)

    # Persist both sides — append-only log for a later report, not
    # conversation state (see PracticeTutorMessage's docstring).
    image_path = None
    if image_bytes:
        student_msg_id = uuid.uuid4()
        try:
            image_path = await storage_service.save_practice_tutor_image(
                station.session_id, str(student_msg_id), image_bytes,
            )
        except Exception:
            logger.exception("Tutor turn: failed to persist frame — continuing without it")
    else:
        student_msg_id = uuid.uuid4()

    db.add(PracticeTutorMessage(
        id=student_msg_id, station_id=station.id, question_id=question.id if question else None,
        role="student", text=transcript, image_path=image_path, had_image=image_path is not None,
    ))
    db.add(PracticeTutorMessage(
        id=uuid.uuid4(), station_id=station.id, question_id=question.id if question else None,
        role="tutor", text=reply, had_image=False,
    ))
    await db.commit()

    return {"transcript": transcript, "reply": reply}


# =============================================================================
# Attempt-history pruning — bound the raw history to the most recent N per
# question, consolidating anything older into a PracticeAttemptSummary
# first rather than just discarding it.
# =============================================================================

_KEEP_RECENT_ATTEMPTS = 10


async def prune_old_attempts_with_summary(
    db: AsyncSession, question_id: uuid.UUID, station_id: uuid.UUID | None,
) -> None:
    """
    Keeps only the most recent _KEEP_RECENT_ATTEMPTS completed attempts for
    a question as full rows/images; anything older is consolidated into ONE
    PracticeAttemptSummary row (see that model's own docstring for why) and
    then genuinely deleted — rows and stored image/audio blobs both. An
    unattended auto-capture station can generate a lot of these; on real
    usage this often includes a large share of redundant or off-topic
    re-reads (process_attempt's own "stop auto-capture once solved" fix
    was added after measuring 51% of one question's full history landing
    as exactly that) — summarizing rather than keeping every row bounds
    storage growth without silently losing the struggle/progress signal.

    Called after every attempt completes (see process_attempt) — a no-op
    whenever the count is still at or under the cap, so this only actually
    does anything once in a while, not on every single call.
    """
    rows = (
        await db.execute(
            select(PracticeAttempt)
            .where(PracticeAttempt.question_id == question_id, PracticeAttempt.status == "complete")
            .order_by(PracticeAttempt.created_at.desc())
        )
    ).scalars().all()
    if len(rows) <= _KEEP_RECENT_ATTEMPTS:
        return
    to_prune = rows[_KEEP_RECENT_ATTEMPTS:]  # everything past the most recent N

    misconception_counts: dict[str, int] = {}
    hint_level_counts: dict[str, int] = {}
    solved = False
    saw_teacher_required = False
    for a in to_prune:
        if a.misconception_code:
            misconception_counts[a.misconception_code] = misconception_counts.get(a.misconception_code, 0) + 1
        if a.hint_level is not None:
            key = str(a.hint_level)
            hint_level_counts[key] = hint_level_counts.get(key, 0) + 1
        if a.student_state == "solved":
            solved = True
        if a.student_state == "teacher_required":
            saw_teacher_required = True

    # "Needs another pass at this" — not solved in this batch, OR it hit
    # the teacher-escalation ceiling, OR enough DIFFERENT misconceptions
    # showed up that one hint clearly wasn't addressing the real gap.
    revision_required = (not solved) or saw_teacher_required or len(misconception_counts) >= 2

    db.add(PracticeAttemptSummary(
        question_id=question_id,
        station_id=station_id,
        attempts_summarized=len(to_prune),
        first_attempt_at=min(a.created_at for a in to_prune),
        last_attempt_at=max(a.created_at for a in to_prune),
        solved=solved,
        revision_required=revision_required,
        misconception_codes=misconception_counts or None,
        hint_levels_seen=hint_level_counts or None,
    ))

    for a in to_prune:
        if a.image_path:
            await storage_service.delete_blob(a.image_path)
        if a.audio_path:
            await storage_service.delete_blob(a.audio_path)
        await db.delete(a)
    await db.commit()


# =============================================================================
# Station-scoped notes/quiz — the voice-command analogs of a session's
# generate_notes/generate_quiz, scoped to ONE student's station history
# instead of a whole lecture. Reuses the same local-Ollama-first/cloud-
# fallback _llm_call already proven for hints/chat, and the same
# retained-rows + PracticeAttemptSummary sources prune_old_attempts_with_
# summary above already maintains — no new data collection, just a new
# way of reading it.
# =============================================================================

_STATION_NOTES_SYSTEM_PROMPT = """You write a short study-notes recap for a \
teacher or parent reviewing ONE student's recent work at a single Guided \
Practice station. You're given that station's attempt history (per-question \
outcomes, misconceptions seen, hint levels needed) — not the original \
lecture material, so never invent facts about the subject beyond what the \
data actually shows. Output ONLY a single JSON object, no other text: \
{"notes": "<3-6 short plain-text sentences, no markdown/bullets>"}. Cover: \
what was practiced, what's solid, what still needs work (name the \
misconception in plain language a parent would understand, not its \
internal code), and one concrete, actionable suggestion for what to try \
next. If the history is genuinely empty, say plainly that there's nothing \
to report yet instead of inventing content."""

_STATION_QUIZ_SYSTEM_PROMPT = """You write short follow-up practice \
questions for ONE student, targeting the specific misconceptions or \
mistakes visible in their recent Guided Practice attempt history at one \
station. Stay strictly within the same subject/topic and difficulty level \
already evidenced by their attempts — these are reinforcement of what they \
just struggled with, never new/harder material. Output ONLY a single JSON \
object, no other text: {"questions": ["<question text>", "<question \
text>", "<question text>"]} — exactly 3 items, text only (no images, \
diagrams, or answer keys — this station has no way to display those). If \
the history is genuinely empty, return {"questions": []} rather than \
inventing generic questions unrelated to anything the student has done."""


async def _collect_station_practice_digest(db: AsyncSession, station_id: uuid.UUID) -> str:
    """Compact, LLM-ready text summary of a station's practice history —
    the single source both generate_station_notes and generate_station_quiz
    read from, so a teacher never sees the notes and the quiz drawing on
    different evidence. Combines the still-retained recent rows (capped at
    _KEEP_RECENT_ATTEMPTS, same cap prune_old_attempts_with_summary
    enforces) with whatever's already been consolidated into
    PracticeAttemptSummary batches — a station open for a while may have
    most of its real history there rather than in live rows."""
    attempts = (
        await db.execute(
            select(PracticeAttempt)
            .where(PracticeAttempt.station_id == station_id, PracticeAttempt.status == "complete")
            .order_by(PracticeAttempt.created_at.desc())
            .limit(_KEEP_RECENT_ATTEMPTS)
        )
    ).scalars().all()
    summaries = (
        await db.execute(
            select(PracticeAttemptSummary)
            .where(PracticeAttemptSummary.station_id == station_id)
            .order_by(PracticeAttemptSummary.created_at.desc())
            .limit(10)
        )
    ).scalars().all()

    if not attempts and not summaries:
        return "(no attempt history for this station yet)"

    question_ids = {a.question_id for a in attempts} | {s.question_id for s in summaries}
    questions: dict[uuid.UUID, PracticeQuestion] = {}
    if question_ids:
        questions = {
            q.id: q for q in (
                await db.execute(select(PracticeQuestion).where(PracticeQuestion.id.in_(question_ids)))
            ).scalars().all()
        }

    lines: list[str] = []
    for a in attempts:
        q = questions.get(a.question_id)
        line = f"- Question: {q.text if q else '(question no longer exists)'} | outcome: {a.student_state or a.validation_status or 'unknown'}"
        if a.misconception_code:
            line += f" | misconception: {a.misconception_code}"
        if a.hint_level is not None:
            line += f" | hint level shown: {a.hint_level}"
        lines.append(line)
    for s in summaries:
        q = questions.get(s.question_id)
        codes = ", ".join(s.misconception_codes.keys()) if s.misconception_codes else "none"
        lines.append(
            f"- (earlier batch, {s.attempts_summarized} attempts) Question: {q.text if q else '(question no longer exists)'} "
            f"| solved: {s.solved} | revision required: {s.revision_required} | misconceptions seen: {codes}"
        )
    return "\n".join(lines)


async def generate_station_notes(
    db: AsyncSession, station_id: uuid.UUID, *,
    ollama_base_url: str, ollama_model: str, openai_api_key: str, local_enabled: bool, timeout_sec: int = 20,
) -> dict:
    """Returns {"notes": str, "source": str}. Never empty — falls back to a
    plain "nothing to report" message rather than a blank result, same
    never-silent-failure rule as answer_question's _CHAT_FALLBACK_REPLY."""
    digest = await _collect_station_practice_digest(db, station_id)
    result, source = await _llm_call(
        _STATION_NOTES_SYSTEM_PROMPT, digest,
        ollama_base_url=ollama_base_url, ollama_model=ollama_model,
        openai_api_key=openai_api_key, local_enabled=local_enabled, timeout_sec=timeout_sec,
    )
    notes = (result or {}).get("notes", "").strip() if result else ""
    if not notes:
        notes = "No practice history for this station yet — notes will show up once a question's been attempted."
    return {"notes": notes, "source": source}


async def generate_station_quiz(
    db: AsyncSession, station_id: uuid.UUID, *,
    ollama_base_url: str, ollama_model: str, openai_api_key: str, local_enabled: bool, timeout_sec: int = 20,
) -> dict:
    """Returns {"questions": list[str], "source": str} — an empty list (not
    an error) when there's no history yet or the LLM produced nothing usable."""
    digest = await _collect_station_practice_digest(db, station_id)
    result, source = await _llm_call(
        _STATION_QUIZ_SYSTEM_PROMPT, digest,
        ollama_base_url=ollama_base_url, ollama_model=ollama_model,
        openai_api_key=openai_api_key, local_enabled=local_enabled, timeout_sec=timeout_sec,
    )
    questions = [str(q).strip() for q in (result or {}).get("questions", []) if str(q).strip()] if result else []
    return {"questions": questions, "source": source}


# =============================================================================
# Main orchestrator — Gates A-H for one attempt
# =============================================================================

async def process_attempt(attempt_id: uuid.UUID, db: AsyncSession) -> PracticeAttempt:
    from app.config import get_settings
    import numpy as np
    import cv2

    settings = get_settings()

    attempt = await db.get(PracticeAttempt, attempt_id)
    if not attempt:
        raise ValueError(f"PracticeAttempt {attempt_id} not found")
    question = await db.get(PracticeQuestion, attempt.question_id)
    if not question:
        attempt.status = "failed"
        attempt.error_message = "question_not_found"
        await db.commit()
        return attempt

    # Not every attempt has a station (e.g. a directly-graded teacher
    # attempt with no capture device involved) — default to "front" (no
    # correction) exactly like a station itself would if camera_mount were
    # never set. `station` (possibly None) is reused further down to
    # auto-stop capturing once the question is solved — see there.
    station = None
    camera_mount = "front"
    if attempt.station_id:
        station = await db.get(PracticeStation, attempt.station_id)
        if station:
            camera_mount = station.camera_mount

    # Capture locals before the first commit expires the ORM objects.
    image_path = attempt.image_path
    audio_path = attempt.audio_path
    input_type = attempt.input_type
    question_text = question.text

    attempt.status = "processing"
    await db.commit()

    latency: dict[str, float] = {}
    transcript = ""  # only ever populated on the audio path; kept defined
    # unconditionally so the low-confidence branch below can safely check it
    # regardless of input_type, instead of a locals()-guarded lookup.
    import time as _time
    from app.services.storage_service import load_frame_bytes

    if input_type == "audio":
        if not audio_path:
            attempt.status = "failed"
            attempt.error_message = "no_audio_path"
            await db.commit()
            return attempt

        from app.services.whisper_service import transcribe as transcribe_cloud

        try:
            audio_bytes = await load_frame_bytes(audio_path)
        except Exception as exc:
            logger.warning("Practice attempt %s: failed to load audio: %s", attempt_id, exc)
            attempt.status = "failed"
            attempt.error_message = f"audio_load_failed: {exc}"
            await db.commit()
            return attempt

        # No image-quality gate for a spoken answer — there's no photo to
        # reject for blur/darkness. A garbled/empty transcript surfaces
        # through Gates B/C's own empty_reason mechanism below instead,
        # same role Gate A's rejection plays for the written path.
        attempt.capture_quality_status = "ok"

        # Cloud Whisper (not the short-command local whisper-server) — a
        # spoken answer to a theory question is long-form content, the same
        # category as lecture recording, not a short deliberate command.
        # min_duration_sec is dropped well below the module default (2.0s):
        # this is a deliberate, VAD-stopped recording, not an ambient
        # snippet from a passively-running lecture capture — a short but
        # complete answer ("42", "yes") can legitimately land under 2s once
        # VAD's own silence tail is subtracted, and the default guard would
        # silently blank it, reading as "didn't catch an answer" for
        # something the student actually said.
        t0 = _time.monotonic()
        transcript = ""
        try:
            transcribed = await transcribe_cloud(
                audio_bytes, "answer.webm", settings.openai_api_key or "", min_duration_sec=0.5,
            )
            transcript = transcribed.text
        except Exception as exc:
            logger.warning("Practice attempt %s: transcription failed: %s", attempt_id, exc)
        latency["gate_bc_ms"] = round((_time.monotonic() - t0) * 1000, 1)

        t0 = _time.monotonic()
        extraction = await practice_engine.extract_steps_from_text(
            transcript, question_text, settings.openai_api_key or "",
        )
        latency["gate_bc_ms"] += round((_time.monotonic() - t0) * 1000, 1)
    else:
        if not image_path:
            attempt.status = "failed"
            attempt.error_message = "no_image_path"
            await db.commit()
            return attempt

        try:
            image_bytes = await load_frame_bytes(image_path)
            arr = np.frombuffer(image_bytes, np.uint8)
            image_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if image_bgr is None:
                raise ValueError("could not decode image")
        except Exception as exc:
            logger.warning("Practice attempt %s: failed to load image: %s", attempt_id, exc)
            attempt.status = "failed"
            attempt.error_message = f"image_load_failed: {exc}"
            await db.commit()
            return attempt

        # A student holding the device sideways/upside-down is a common real
        # capture mistake — correct it before anything downstream (quality
        # gate, vision, bbox) sees the image. Fixed mount correction first
        # (only a no-op unless this station is desk-mounted) so a reliably-
        # known 90°+mirror is already undone before the OSD-based guess
        # runs — OSD reads more reliably on an already-upright page. Either
        # step re-persists the corrected bytes at the SAME storage path
        # (save_practice_attempt_image is deterministic on session_id/
        # attempt_id) so the photo shown back to the student — and the
        # bbox circle drawn over it — both agree with what the pipeline
        # actually graded, instead of the pipeline reading a corrected copy
        # while the student sees the original sideways/mirrored one.
        original_image_bgr = image_bgr
        image_bgr = practice_engine.apply_mount_correction(image_bgr, camera_mount)
        image_bgr = practice_engine.auto_orient(image_bgr)
        if image_bgr is not original_image_bgr:
            ok, buf = cv2.imencode(".jpg", image_bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
            if ok:
                try:
                    await storage_service.save_practice_attempt_image(
                        attempt.session_id, str(attempt.id), buf.tobytes(),
                    )
                except Exception as exc:
                    logger.warning("Practice attempt %s: failed to save orientation-corrected image: %s", attempt_id, exc)

        # ---- Gate A: capture quality ----
        t0 = _time.monotonic()
        quality = practice_engine.check_capture_quality(image_bgr)
        latency["gate_a_ms"] = round((_time.monotonic() - t0) * 1000, 1)
        if not quality.is_valid:
            attempt.capture_quality_status = f"rejected_{quality.reason}"
            attempt.capture_quality_reason = quality.reason
            attempt.status = "complete"  # pipeline ran correctly; the CAPTURE is what needs a retake
            attempt.student_state = "ambiguous"
            attempt.latency_ms_breakdown = latency
            await db.commit()
            return attempt
        attempt.capture_quality_status = "ok"

        # ---- Gates B/C: step extraction (vision) ----
        t0 = _time.monotonic()
        extraction = await practice_engine.extract_steps(image_bgr, question_text, settings.openai_api_key or "")
        latency["gate_bc_ms"] = round((_time.monotonic() - t0) * 1000, 1)

        # The vision model's own bbox guess is frequently imprecise (spatial
        # grounding is a known weak point for these models, unlike reading
        # the text itself) — snap each one to the actual ink found nearby
        # before it's stored, so the mistake-circle the student sees later
        # actually lands on their handwriting (reported 2026-09-24).
        for step in extraction["steps"]:
            if step.get("bbox"):
                step["bbox"] = practice_engine.refine_bbox(image_bgr, step["bbox"])

    if extraction.get("overall_confidence", 0.0) < 0.4 or not extraction["steps"]:
        # Low confidence — never infer an error, ask for a clearer capture instead.
        # empty_reason distinguishes WHY nothing was extracted: a genuinely
        # illegible/blurry photo needs a recapture, but a perfectly sharp
        # photo of unrelated content needs a different message entirely —
        # collapsing both into "couldn't read that clearly" was a real bug
        # (caught 2026-09-10: a clean, legible textbook photo on the wrong
        # topic was reported to the student as an image-quality problem).
        empty_reason = extraction.get("empty_reason", "illegible")
        reason_code = {
            "illegible": "capture_illegible",
            "off_topic": "off_topic_content",
            "blank": "blank_page",
            "error": "recognition_unavailable",
        }.get(empty_reason, "capture_illegible")

        # For audio specifically: if Whisper actually transcribed real text
        # but the SEPARATE step-extraction call still classified it as
        # blank/off-topic/illegible, that raw transcript would otherwise be
        # silently discarded — leaving no way to tell "the mic heard
        # nothing" apart from "the mic heard something but the classifier
        # threw it away." Always surface what was actually heard.
        steps_to_store = extraction["steps"]
        if input_type == "audio" and not steps_to_store and transcript.strip():
            steps_to_store = [{"text": transcript.strip(), "bbox": None, "confidence": extraction.get("overall_confidence", 0.0)}]
            if empty_reason == "blank":
                # "blank" specifically means Whisper itself heard nothing —
                # contradicted by having real transcript text here, so this
                # is actually the off-topic/unclear case, not a silent mic.
                reason_code = "off_topic_content"

        attempt.recognized_steps = steps_to_store
        attempt.recognition_confidence = extraction.get("overall_confidence", 0.0)
        attempt.validation_status = "ambiguous"
        attempt.validation_reason_code = reason_code
        attempt.student_state = "ambiguous"
        attempt.status = "complete"
        attempt.latency_ms_breakdown = latency
        await db.commit()
        return attempt

    attempt.recognized_steps = extraction["steps"]
    attempt.recognition_confidence = extraction["overall_confidence"]

    # Previous step for Gate D's consecutive-transformation check: the last
    # attempt's last recognized step, if this question has been attempted before.
    prev_attempt = (
        await db.execute(
            select(PracticeAttempt)
            .where(
                PracticeAttempt.question_id == attempt.question_id,
                PracticeAttempt.id != attempt.id,
                PracticeAttempt.attempt_no < attempt.attempt_no,
            )
            .order_by(PracticeAttempt.attempt_no.desc())
            .limit(1)
        )
    ).scalars().first()
    prev_step_text = prev_attempt.recognized_steps[-1].get("text") if prev_attempt and prev_attempt.recognized_steps else None

    # Near-duplicate guard: with a station auto-capturing every 10-20s, a
    # capture can easily land before the student has written anything new
    # since the last one — same page, same mistake, just re-photographed.
    # Running full Gates D-H on that isn't a fresh independent failed
    # attempt, and counting it toward the escalation streak was exactly how
    # a single unresolved mistake burned through all 4 hint levels and hit
    # "get your teacher" inside a minute (caught 2026-09-11 from real Pi
    # usage — 10 consecutive identical-cause captures in ~30s). If nothing
    # meaningfully changed, carry the previous result forward unchanged
    # instead of re-litigating it — cheaper too, skips a vision-model-priced
    # validation call for no new information.
    def _normalize(steps: list[dict]) -> str:
        # Alphanumeric content only — real handwriting recognition can vary
        # call-to-call on spacing/punctuation ("23+48=61" vs "23 + 48 = 61")
        # even when it's genuinely the same photographed work, so an exact
        # string match would under-detect duplicates. This still requires
        # the actual digits/letters to match, just not their formatting.
        joined = " ".join(s.get("text", "") for s in steps)
        return re.sub(r"[^a-z0-9]+", "", joined.lower())

    if prev_attempt and prev_attempt.recognized_steps and prev_attempt.status == "complete":
        if _normalize(extraction["steps"]) == _normalize(prev_attempt.recognized_steps):
            attempt.validation_status = prev_attempt.validation_status
            attempt.validation_reason_code = "no_new_work_since_last_capture"
            attempt.error_step_index = prev_attempt.error_step_index
            attempt.misconception_code = prev_attempt.misconception_code
            attempt.student_state = prev_attempt.student_state
            attempt.hint_level = prev_attempt.hint_level
            attempt.hint_text = prev_attempt.hint_text
            attempt.hint_hash = prev_attempt.hint_hash
            attempt.gate_d_result = prev_attempt.gate_d_result
            attempt.status = "complete"
            attempt.latency_ms_breakdown = latency
            await db.commit()
            await db.refresh(attempt)
            return attempt

    # help_streak = how many consecutive prior attempts on this question were
    # genuine MISTAKES (see _MISTAKE_STATUSES), walking back from the most
    # recent one until the first progressing attempt (or the start).
    # "incomplete"/"ambiguous" attempts are skipped entirely — with a station
    # auto-capturing every 10-20s, several "incomplete" snapshots in a row
    # just mean the student hasn't finished writing yet, not that they're
    # struggling; counting those toward the streak was the actual bug behind
    # captures getting stuck at "teacher_required" almost immediately.
    prior_attempts = (
        await db.execute(
            select(PracticeAttempt)
            .where(
                PracticeAttempt.question_id == attempt.question_id,
                PracticeAttempt.id != attempt.id,
                PracticeAttempt.attempt_no < attempt.attempt_no,
            )
            .order_by(PracticeAttempt.attempt_no.desc())
        )
    ).scalars().all()
    help_streak = 0
    for a in prior_attempts:
        if a.validation_reason_code == "no_new_work_since_last_capture":
            continue  # a carried-forward duplicate, not an independent attempt — see the guard above
        if a.validation_status in ("solved", "valid_progress", "alternative_valid_method"):
            break
        if a.validation_status not in _MISTAKE_STATUSES:
            continue  # incomplete/ambiguous/None — neutral, doesn't count
        help_streak += 1

    # ---- Gate D: deterministic check ----
    t0 = _time.monotonic()
    step_texts = [s.get("text", "") for s in extraction["steps"]]
    gate_d_result = run_gate_d(step_texts, prev_step_text)
    latency["gate_d_ms"] = round((_time.monotonic() - t0) * 1000, 1)
    attempt.gate_d_result = gate_d_result

    # ---- Gates E/F: solution-path validation + misconception classification ----
    t0 = _time.monotonic()
    validation = await validate_step(
        question, extraction["steps"], gate_d_result,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_brain_model,
        openai_api_key=settings.openai_api_key or "",
        local_enabled=settings.practice_local_llm_enabled,
    )
    latency["gate_ef_ms"] = round((_time.monotonic() - t0) * 1000, 1)

    attempt.validation_status = validation["validation_status"]
    attempt.validation_reason_code = validation["reason_code"]
    attempt.error_step_index = validation["error_step_index"]
    attempt.misconception_code = validation["misconception_code"]
    attempt.student_state = derive_student_state(validation["validation_status"], help_streak)

    # Once solved, stop the station's auto-capture loop — same effect as
    # the student tapping Pause themselves. Without this, the loop keeps
    # firing every capture_interval_sec regardless of whether there's
    # still a live question to grade, which measured on real usage
    # (2026-09-24) produced two compounding problems: (1) the very next
    # capture after "solved" — the student closing the notebook, moving
    # their hand away, starting the next problem — reads a genuinely worse
    # frame of a no-longer-relevant page and can flip a correct "solved"
    # back to a false "conceptual_misconception"/"arithmetic_slip", which
    # reads to the student as the hint suddenly being wrong; (2) captures
    # keep piling up against content that has nothing to do with this
    # question at all. On one real question's history this was 39 of 76
    # total attempts (51%) landing as "off_topic_content" — pure waste,
    # not signal. `status = "idle"` is the exact same field the station's
    # own toggle-capturing endpoint sets; the capture device's frontend
    # already reacts to this on its next poll (see the station-status
    # sync effect in practice-station/[stationId]/page.tsx) — no separate
    # signal needed.
    if station is not None and attempt.student_state == "solved" and station.status == "capturing":
        station.status = "idle"

    # Column-level pinpoint for a carry/borrow arithmetic_slip — sharper
    # than circling the whole line (refine_bbox already ran on every
    # step's bbox up above; this narrows the ERROR step specifically down
    # to the one digit a column_hint identifies, e.g. "the ones column"
    # rather than the whole "47+38=815"). Image-only: there's no photo to
    # re-target on the spoken-answer path. Best-effort — silently keeps
    # the step's existing (already refine_bbox'd) bbox on any failure.
    column_hint = validation.get("column_hint")
    if (
        column_hint and input_type == "image" and image_bgr is not None
        and attempt.error_step_index is not None
        and 0 <= attempt.error_step_index < len(extraction["steps"])
    ):
        step = extraction["steps"][attempt.error_step_index]
        if step.get("bbox"):
            column_bbox = practice_engine.locate_arithmetic_column(
                image_bgr, step["bbox"], column_hint["column"],
            )
            if column_bbox:
                step["bbox"] = column_bbox
                attempt.recognized_steps = extraction["steps"]

    # ---- Gates G/H: hint (if needed) + leakage guard ----
    hint_level = select_hint_level(validation["validation_status"], help_streak)
    attempt.hint_level = hint_level

    if hint_level in (1, 2, 3, 4):
        t0 = _time.monotonic()
        hint = await generate_hint(
            question, hint_level, validation,
            ollama_base_url=settings.ollama_base_url,
            ollama_model=settings.ollama_brain_model,
            openai_api_key=settings.openai_api_key or "",
            local_enabled=settings.practice_local_llm_enabled,
        )
        leaked = await check_hint_leakage(
            question, hint["hint_text"],
            ollama_base_url=settings.ollama_base_url,
            ollama_model=settings.ollama_brain_model,
            openai_api_key=settings.openai_api_key or "",
            local_enabled=settings.practice_local_llm_enabled,
        )
        latency["gate_g_ms"] = round((_time.monotonic() - t0) * 1000, 1)

        if leaked or not hint["hint_text"]:
            # Reject and fall back to the lowest-information level rather
            # than showing nothing — a silent failure here reads to the
            # student as "no help available" with no explanation.
            attempt.hint_text = (
                "Try re-checking your last step against what the question is asking."
            )
            attempt.hint_level = 1
        else:
            attempt.hint_text = hint["hint_text"]
        attempt.hint_hash = hashlib.sha256((attempt.hint_text or "").encode()).hexdigest()[:16]
    elif hint_level == 5:
        # Escalating to the teacher shouldn't mean the student sees nothing
        # at all in the meantime — carry forward the last real hint they
        # were given (from the L1-4 attempt right before this one hit the
        # ceiling) so there's still something to try while waiting, rather
        # than a blank "get your teacher" with no other content.
        attempt.hint_text = prev_attempt.hint_text if prev_attempt and prev_attempt.hint_text else None
        attempt.post_hint_outcome = "escalated_to_teacher"

    # ---- Gate H: post-hint outcome, from the PREVIOUS attempt's perspective ----
    if prev_attempt and prev_attempt.hint_level and prev_attempt.hint_level > 0:
        if validation["validation_status"] in ("solved", "valid_progress", "alternative_valid_method"):
            prev_attempt.post_hint_outcome = "resolved"
        elif hint_level == 5:
            prev_attempt.post_hint_outcome = "escalated_to_teacher"
        else:
            prev_attempt.post_hint_outcome = "still_stuck"

    attempt.latency_ms_breakdown = latency
    attempt.status = "complete"
    await db.commit()
    await db.refresh(attempt)
    return attempt


# =============================================================================
# Batch student-region detection — one photo covering several students
# =============================================================================

async def detect_student_regions(image_bytes: bytes, question_text: str) -> list[dict]:
    """
    One vision call: find each student's name + the bounding box of their
    own work in a single wide photo. Returns [{"name", "bbox"}, ...] with
    bbox in the app-wide normalized 0-1000 space — empty list is a valid,
    non-error result (see build_batch_student_detection_prompt).

    Raises RuntimeError if AI isn't configured, propagates any call/parse
    failure to the caller (the router turns that into a clear HTTP error —
    this is a teacher-initiated action expecting an immediate result, not
    a background task, so silent partial failure would be worse than a
    surfaced error here).
    """
    from app.config import get_settings
    from app.ai import build_batch_student_detection_prompt, parse_batch_student_detection, call_openai_vision

    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("AI features are not configured (missing OpenAI API key)")

    prompt = build_batch_student_detection_prompt(question_text)
    raw_response, _ = await call_openai_vision(
        api_key=settings.openai_api_key,
        model=settings.openai_model_default,
        system=prompt.system,
        user_text=prompt.user,
        image_data=image_bytes,
        image_media_type="image/jpeg",
        max_tokens=1500,
        timeout_sec=settings.ai_request_timeout_sec,
        # "low" detail (the call's own default) downsamples aggressively —
        # nowhere near enough resolution to read 5-10 separate handwritten
        # names and tell adjacent students' work apart in one wide photo.
        detail="high",
    )
    return parse_batch_student_detection(raw_response)


def crop_student_region(image_bytes: bytes, bbox: list[float]) -> bytes | None:
    """
    Crop one normalized-0-1000 bbox out of the full photo and re-encode as
    JPEG — the per-student image that gets fed into the exact same
    single-attempt grading pipeline (_persist_attempt + process_attempt)
    as a normal one-student photo capture. Returns None if the source
    image won't decode or the crop ends up degenerate (e.g. a bbox that
    clamps to zero width/height at an image edge).
    """
    import numpy as np
    import cv2

    arr = np.frombuffer(image_bytes, np.uint8)
    image_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image_bgr is None:
        return None

    h, w = image_bgr.shape[:2]
    x1, y1, x2, y2 = bbox
    px1 = max(0, min(w - 1, round(x1 / 1000 * w)))
    py1 = max(0, min(h - 1, round(y1 / 1000 * h)))
    px2 = max(px1 + 1, min(w, round(x2 / 1000 * w)))
    py2 = max(py1 + 1, min(h, round(y2 / 1000 * h)))
    if px2 - px1 < 8 or py2 - py1 < 8:
        return None

    crop = image_bgr[py1:py2, px1:px2]
    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        return None
    return buf.tobytes()
