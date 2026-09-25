#!/usr/bin/env python3
"""
Initialize the development database (SQLite or PostgreSQL).

Usage
-----
  # SQLite — zero external dependencies (default dev path)
  DATABASE_URL=sqlite+aiosqlite:///./dev.db python scripts/create_db.py

  # PostgreSQL — requires running postgres (docker compose up -d postgres)
  DATABASE_URL=postgresql+asyncpg://aci:aci@localhost:5432/aci python scripts/create_db.py

SQLite notes
------------
* Alembic migrations use postgresql.JSONB and cannot run against SQLite.
  This script uses SQLAlchemy's create_all() which maps JSON columns to TEXT
  automatically — structurally identical for development purposes.
* For PostgreSQL you should use `alembic upgrade head` instead (see Makefile).
"""
import asyncio
import os
import sys

# Allow running from repo root or from backend/
_here = os.path.dirname(os.path.abspath(__file__))
_backend = os.path.dirname(_here)
if _backend not in sys.path:
    sys.path.insert(0, _backend)


def _add_missing_sqlite_columns(sync_conn, metadata) -> list[str]:
    """
    create_all() only creates missing TABLES — a table that already exists
    is left untouched even if a model gained new columns since. On SQLite
    (no Alembic support here — see module docstring), that silently leaves
    the DB schema behind the code until something crashes on the missing
    column. This adds any columns present in the models but missing from
    the actual table, via SQLite's ALTER TABLE ... ADD COLUMN (works for
    simple nullable/defaulted columns, which covers every column added so
    far). Returns the list of "table.column" additions made.
    """
    from sqlalchemy import inspect

    inspector = inspect(sync_conn)
    existing_tables = set(inspector.get_table_names())
    added = []

    for table in metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # brand new table — create_all() already handled it
        existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing_cols:
                continue
            col_type = col.type.compile(dialect=sync_conn.dialect)
            sync_conn.exec_driver_sql(
                f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col_type}'
            )
            added.append(f"{table.name}.{col.name}")

    return added


async def main() -> None:
    from app.database import _get_engine, reset_engine  # noqa: F401

    # Ensure any previously cached engine (wrong URL) is discarded
    reset_engine()

    # Importing the models package registers all ORM classes on Base.metadata
    import app.models  # noqa: F401
    from app.models.base import Base

    engine = _get_engine()
    db_url = str(engine.url)

    print(f"Target database: {db_url}")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if "sqlite" in db_url:
            added = await conn.run_sync(_add_missing_sqlite_columns, Base.metadata)
            if added:
                print(f"✓ Added {len(added)} missing column(s) to existing tables:")
                for name in added:
                    print(f"    {name}")

    table_names = list(Base.metadata.tables.keys())
    table_names.sort()
    print(f"✓ {len(table_names)} tables created:")
    for name in table_names:
        print(f"    {name}")

    await engine.dispose()
    print("\nDone. Database is ready.")


if __name__ == "__main__":
    asyncio.run(main())
