"""
Misconception library access — grade parsing, candidate retrieval for the
grader, and idempotent seeding. See app/models/misconception.py for what the
library is and what its review_status means.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.misconception_seed import MISCONCEPTION_SEED
from app.models.misconception import Misconception

_GRADE_RE = re.compile(r"(?<!\d)(\d{1,2})(?!\d)")

# 1-3: concrete/early literacy; 4-7: middle; 8-10: secondary. Beyond that the
# library has no content, so callers get None and fall back to unfiltered.
def parse_grade(grade: str | None) -> int | None:
    """'Grade 8', '8th', 'Class 10', '10' -> int. Anything unparseable or
    outside 1-12 -> None (treated as 'unknown', never guessed)."""
    if not grade:
        return None
    m = _GRADE_RE.search(str(grade))
    if not m:
        return None
    n = int(m.group(1))
    return n if 1 <= n <= 12 else None


def grade_band(grade: int | None) -> str | None:
    if grade is None:
        return None
    if grade <= 3:
        return "early"
    if grade <= 7:
        return "middle"
    return "senior"


def library_subject_keys(subject_key: str, subject_text: str | None = None) -> list[str]:
    """Which library subject keys apply to a question. 'science' (biology,
    earth & space, general science) is shared by physics/chemistry questions
    too, since general-science misconceptions often show up there."""
    if subject_key in ("physics", "chemistry"):
        return [subject_key, "science"]
    if subject_key in ("math", "history", "language"):
        return [subject_key]
    text = (subject_text or "").lower()
    if any(k in text for k in ("science", "biology", "evs", "environment", "geography")):
        return ["science"]
    return []


_WORD = re.compile(r"[a-z]{4,}")


def rank_candidates(rows: list[dict], keys: list[str], grade: int | None, topic_text: str, limit: int = 8) -> list[dict]:
    """Pure ranking over library rows (dicts with the Misconception fields) —
    shared by the live grader (rows from the DB) and the offline eval runner
    (rows straight from the shipped seed), so both pick candidates the same way."""
    words = set(_WORD.findall((topic_text or "").lower()))
    pool = [
        r for r in rows
        if r["subject_key"] in keys and (grade is None or r["grade_min"] <= grade <= r["grade_max"])
    ]

    def score(r: dict) -> int:
        hay = f"{r['topic']} {r['title']} {r['description']} {r['typical_work']}".lower()
        return sum(1 for w in words if w in hay)

    pool.sort(key=lambda r: (-score(r), r["code"]))
    return [
        {"code": r["code"], "title": r["title"], "description": r["description"], "typical_work": r["typical_work"]}
        for r in pool[:limit]
    ]


async def get_candidates(
    db: AsyncSession, subject_key: str, subject_text: str | None, grade: int | None,
    topic_text: str, limit: int = 8,
) -> list[dict]:
    """Best-matching library entries for this subject/grade/topic. Empty list
    (not an error) when nothing applies — the grader then relies on the
    question's own known_misconceptions only."""
    keys = library_subject_keys(subject_key, subject_text)
    if not keys:
        return []
    stmt = select(Misconception).where(Misconception.subject_key.in_(keys))
    if grade is not None:
        stmt = stmt.where(Misconception.grade_min <= grade, Misconception.grade_max >= grade)
    rows = [
        {c: getattr(m, c) for c in ("code", "subject_key", "grade_min", "grade_max", "topic", "title", "description", "typical_work")}
        for m in (await db.execute(stmt)).scalars().all()
    ]
    return rank_candidates(rows, keys, grade, topic_text, limit)


async def seed_library(db: AsyncSession) -> tuple[int, int]:
    """Idempotent upsert of the shipped seed. Never downgrades an entry a
    teacher already confirmed. Returns (inserted, updated)."""
    existing = {m.code: m for m in (await db.execute(select(Misconception))).scalars().all()}
    inserted = updated = 0
    for row in MISCONCEPTION_SEED:
        cur = existing.get(row["code"])
        if cur is None:
            db.add(Misconception(**row, review_status="unreviewed"))
            inserted += 1
        else:
            for k, v in row.items():
                setattr(cur, k, v)  # review_status deliberately untouched
            updated += 1
    await db.commit()
    return inserted, updated
