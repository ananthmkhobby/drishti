#!/usr/bin/env python3
"""
Idempotently ensure a Teacher row exists for settings.dev_teacher_id when
skip_auth is on.

Confirmed live 2026-09-21, migrating the Pi off SQLite (repeated
corruption) onto Postgres: sessions.teacher_id is a real foreign key to
teachers.id, but nothing ever created a teachers row for dev_teacher_id —
this worked on SQLite only because SQLite doesn't enforce foreign keys by
default. The very first session-creation request against a fresh Postgres
database (which does enforce them) fails with a foreign-key violation,
which the sessions router's IntegrityError handler then misreports as
"DUPLICATE_SESSION" (it assumes any IntegrityError there means a
local_session_id race). Run this once after standing up a fresh database,
before the app serves any real traffic.

Usage: DATABASE_URL=... python scripts/seed_dev_teacher.py
"""
import asyncio
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_backend = os.path.dirname(_here)
if _backend not in sys.path:
    sys.path.insert(0, _backend)


async def main() -> None:
    from app.config import get_settings
    from app.database import _get_session_factory, reset_engine
    from app.models.teacher import Teacher
    from sqlalchemy import select

    reset_engine()
    settings = get_settings()

    if not settings.skip_auth:
        print("skip_auth is off — no dev teacher to seed, nothing to do.")
        return

    factory = _get_session_factory()
    async with factory() as db:
        existing = await db.get(Teacher, settings.dev_teacher_id)
        if existing:
            print(f"Dev teacher {settings.dev_teacher_id} already exists — nothing to do.")
            return

        # A stale row with the same email (e.g. re-seeding after an id
        # change) would otherwise trip the unique constraint on email.
        by_email = (
            await db.execute(select(Teacher).where(Teacher.email == "dev@drishti.local"))
        ).scalar_one_or_none()
        if by_email:
            print(f"Found existing dev@drishti.local teacher ({by_email.id}) — leaving it as-is.")
            return

        db.add(Teacher(
            id=settings.dev_teacher_id,
            name="Dev Teacher",
            email="dev@drishti.local",
            role="teacher",
            is_active=True,
            is_verified=True,
        ))
        await db.commit()
        print(f"✓ Seeded dev teacher {settings.dev_teacher_id}")


if __name__ == "__main__":
    asyncio.run(main())
