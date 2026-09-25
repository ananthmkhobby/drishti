# Set env vars BEFORE any app module is imported.
# conftest.py is always executed first by pytest.
import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["SKIP_AUTH"] = "true"
os.environ["ENVIRONMENT"] = "test"
os.environ["USE_S3"] = "false"
os.environ["UPLOAD_DIR"] = "/tmp/aci-test-uploads"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-do-not-use-in-production"

import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.models.base import Base
from app.database import get_db
import app.database as _db_module

TEST_DB_URL = "sqlite+aiosqlite:///./test.db"

_test_engine = create_async_engine(TEST_DB_URL, echo=False)
_TestSessionLocal = async_sessionmaker(_test_engine, expire_on_commit=False)


@pytest.fixture(scope="session", autouse=True)
async def setup_database():
    # Wire the test engine into the database module
    _db_module._engine = _test_engine
    _db_module._session_factory = _TestSessionLocal

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _test_engine.dispose()


@pytest.fixture
async def db(setup_database) -> AsyncSession:
    async with _TestSessionLocal() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def client(db: AsyncSession):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


# Reusable factory helpers for tests
TEACHER_ID = "11111111-1111-1111-1111-111111111111"
CLASSROOM_ID = "22222222-2222-2222-2222-222222222222"
