"""
Cross-session concept linking — given 2+ sessions (same or different
subjects/grades/instructors), ask the model how the concepts taught in each
actually connect, for a teacher building integrated/thematic lessons.

Deliberately ephemeral for now: this generates a result and returns it, it
doesn't persist anything new to the database. If this turns out to be used
regularly, the natural next step is a small table to save/revisit past
comparisons — not built here since there's no evidence yet that's needed.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are helping a teacher build an INTERDISCIPLINARY lesson — \
finding the same underlying idea reappearing across DIFFERENT classroom \
sessions (possibly different subjects, grades, or instructors), and turning \
that into something the teacher can actually teach WITH, not just a \
side-by-side comparison.

The bar is depth, not resemblance. "These two things are kind of similar" is \
not good enough — a teacher wants to be able to walk into class and say \
"the exact same principle you learned in physics is what's happening here \
in biology," and know how to make students SEE that, not just be told it.

Given a list of sessions (each with subject, grade, instructor, and a \
summary of what was taught), output ONLY a JSON object with this shape:

{
  "unifying_theme": "<the ONE shared underlying idea/principle running through \
these sessions, stated as a single insight a teacher could open a lesson with \
— or an honest empty string if there genuinely isn't one>",
  "overall_summary": "<1-2 sentences on how deep and useful this \
interdisciplinary link actually is, not just that a link exists>",
  "connections": [
    {
      "concept_a": "<concept from one session>",
      "concept_b": "<concept from another session>",
      "shared_principle": "<the deeper idea both concepts are actually \
specific cases of — WHY they're the same thing underneath, not just that \
they're similar>",
      "how_to_teach_it": "<concrete words or a short sequence a teacher could \
actually use in class to make students discover this connection themselves — \
e.g. a question to pose, a demonstration to run, an example that makes both \
click at once>"
    }
  ],
  "integrated_activity": "<ONE concrete classroom activity that requires \
students to actively USE both concepts TOGETHER to complete it — not two \
separate tasks placed side by side. Empty string if nothing genuine applies.>"
}

RULES:
- If there is no genuine shared principle — only a surface-level or forced \
resemblance — say so plainly in unifying_theme and overall_summary, return \
an empty connections list, and leave integrated_activity empty. A teacher \
trusting this tool needs honesty over manufactured interdisciplinary framing.
- Ground everything in what was ACTUALLY covered per the summaries given — \
never invent content that wasn't mentioned.
- Prefer 1-3 genuinely deep connections over a long list of surface ones — \
depth of interdisciplinary insight matters far more than count.
- how_to_teach_it must be usable as-is in a classroom, not a restatement of \
shared_principle in different words.
- Output ONLY the JSON object, no markdown fences, no other text."""

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _build_user_prompt(sessions: list[dict]) -> str:
    parts = []
    for i, s in enumerate(sessions, 1):
        label = f"Session {i}: {s.get('subject') or 'Subject not set'}"
        if s.get("grade"):
            label += f", {s['grade']}"
        if s.get("title"):
            label += f" — \"{s['title']}\""
        if s.get("instructor_name"):
            label += f" (taught by {s['instructor_name']})"
        content = (s.get("content") or "").strip()
        if not content:
            content = "(no notes generated yet for this session — nothing to compare)"
        # Keep each session's content bounded so N sessions doesn't blow the
        # context budget — this is a cross-session OVERVIEW comparison, not
        # a full-text analysis of any one session.
        if len(content) > 3000:
            content = content[:3000] + "\n...(truncated)"
        parts.append(f"{label}\n{content}")
    return "\n\n---\n\n".join(parts)


def _empty_result(overall_summary: str) -> dict:
    return {
        "unifying_theme": "",
        "overall_summary": overall_summary,
        "connections": [],
        "integrated_activity": "",
    }


async def generate_cross_session_links(sessions: list[dict], api_key: str, timeout_sec: int = 60) -> dict:
    """
    sessions: list of {subject, grade, title, instructor_name, content} dicts,
    content being each session's notes markdown (or a fallback summary).

    Returns {unifying_theme, overall_summary, connections: [...],
    integrated_activity} — on any failure, returns a result with an
    explanatory overall_summary rather than raising, since this is a "nice
    to have" analysis, not a step that should ever crash the page that
    requested it.
    """
    if len(sessions) < 2:
        return _empty_result("Pick at least two sessions to compare.")

    try:
        from openai import AsyncOpenAI
    except ImportError:
        return _empty_result("AI comparison is unavailable (OpenAI client not installed).")

    if not api_key:
        return _empty_result("AI comparison is unavailable (no OpenAI API key configured).")

    client = AsyncOpenAI(api_key=api_key)
    user_prompt = _build_user_prompt(sessions)

    try:
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.3,
            timeout=timeout_sec,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = resp.choices[0].message.content or ""
    except Exception as exc:
        logger.warning("Cross-session link generation failed: %s", exc)
        return _empty_result("Couldn't generate this right now — try again in a moment.")

    match = _JSON_BLOCK.search(content)
    if not match:
        logger.warning("Cross-session link: no JSON in response: %.200s", content)
        return _empty_result("Couldn't parse a result — try again.")

    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        logger.warning("Cross-session link: invalid JSON: %.200s", content)
        return _empty_result("Couldn't parse a result — try again.")

    raw_connections = data.get("connections") or []
    connections = [
        {
            "concept_a": str(c.get("concept_a", "")).strip(),
            "concept_b": str(c.get("concept_b", "")).strip(),
            "shared_principle": str(c.get("shared_principle", "")).strip(),
            "how_to_teach_it": str(c.get("how_to_teach_it", "")).strip(),
        }
        for c in raw_connections
        if isinstance(c, dict) and c.get("concept_a") and c.get("concept_b")
    ]

    return {
        "unifying_theme": str(data.get("unifying_theme", "")).strip(),
        "overall_summary": str(data.get("overall_summary", "")).strip(),
        "connections": connections,
        "integrated_activity": str(data.get("integrated_activity", "")).strip(),
    }
