"""Seed/refresh the misconception library: python scripts/seed_misconceptions.py"""
import asyncio

from app.database import _get_session_factory
from app.services.misconception_library import seed_library


async def main() -> None:
    async with _get_session_factory()() as db:
        inserted, updated = await seed_library(db)
    print(f"misconceptions: {inserted} inserted, {updated} updated")


if __name__ == "__main__":
    asyncio.run(main())
