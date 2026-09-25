from typing import AsyncGenerator
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

_engine = None
_session_factory = None


def _get_engine():
    global _engine
    if _engine is None:
        from app.config import get_settings
        s = get_settings()
        is_sqlite = "sqlite" in s.database_url
        _engine = create_async_engine(
            s.database_url,
            echo=s.debug,
            pool_pre_ping=True,
            # SQLite doesn't support these pool args
            **({"pool_size": 10, "max_overflow": 20} if "postgresql" in s.database_url else {}),
            # SQLite's default journal mode takes an exclusive lock for the
            # whole duration of any write, so two requests writing at once —
            # entirely normal here given how much runs as a BackgroundTask
            # (chapter detection, guided-practice grading, OCR reprocessing,
            # audience analysis, sync processing...) — routinely collided
            # with a plain foreground request's own commit. Confirmed as the
            # cause of "internal error" on textbook upload: a `db.commit()`
            # landing mid-write from an unrelated background job raised
            # sqlite3.OperationalError: database is locked, which (before
            # generic_exception_handler existed) fell straight through to a
            # bare, unlogged 500. `timeout` here is belt-and-suspenders with
            # the PRAGMA below — both set SQLite's busy-wait window so a
            # write blocked by another writer retries instead of failing
            # immediately.
            #
            # Deliberately NOT switching journal_mode to WAL. Confirmed live
            # on the Pi (2026-09-21): even against a freshly integrity-checked
            # dev.db, with the service that could race it stopped first,
            # `PRAGMA journal_mode=WAL` corrupted the file on the very next
            # connection — twice, identically. WAL requires shared-memory
            # (mmap) support that isn't reliable on every SD-card filesystem
            # setup, and this Pi's is apparently one of them. busy_timeout
            # alone (default rollback-journal mode) still fixes the actual
            # bug — writers retry instead of failing immediately — just
            # without WAL's extra benefit of reads never blocking on writes.
            # Do not re-add WAL here without confirming the target
            # filesystem actually supports it.
            **({"connect_args": {"timeout": 30}} if is_sqlite else {}),
        )
        if is_sqlite:
            @event.listens_for(_engine.sync_engine, "connect")
            def _set_sqlite_pragmas(dbapi_connection, _connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.close()
    return _engine


def _get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            _get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def reset_engine():
    """Reset engine and session factory. Used in tests to swap databases."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None
