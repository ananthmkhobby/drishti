# Skill: Testing

**Purpose:** Reference guide for writing and running tests in the ACI backend. Covers fixtures, patterns, common pitfalls, and the test-per-file breakdown.

---

## Quick Start

```bash
cd backend && source .venv/bin/activate

# Full suite (279 tests)
python -m pytest tests/ -v

# Single file
python -m pytest tests/test_dashboard.py -v

# With coverage
python -m pytest tests/ --cov=app --cov-report=term-missing

# TypeScript check (frontend)
cd frontend && npx tsc --noEmit
```

---

## Test Environment

Set in `tests/conftest.py` before any app import:

```python
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["SKIP_AUTH"] = "true"
os.environ["ENVIRONMENT"] = "test"
os.environ["USE_S3"] = "false"
os.environ["UPLOAD_DIR"] = "/tmp/aci-test-uploads"
```

SQLite is used for speed and zero setup. PostgreSQL-specific features (e.g. `DATE_TRUNC`) are intentionally avoided — all time-series bucketing is done in Python.

**SQLite FK note:** Foreign key constraints are NOT enforced by default in SQLite. This means you can create sessions with non-existent teacher UUIDs. Run integration tests against PostgreSQL before merging schema changes.

---

## Fixtures

```python
# conftest.py
TEACHER_ID  = "11111111-1111-1111-1111-111111111111"  # used in session payloads
CLASSROOM_ID = "22222222-2222-2222-2222-222222222222"

@pytest.fixture(scope="session", autouse=True)
async def setup_database():
    # Creates all tables once; drops them after the test session

@pytest.fixture
async def db(setup_database) -> AsyncSession:
    # Yields a session; rolls back uncommitted changes after each test

@pytest.fixture
async def client(db: AsyncSession):
    # Overrides get_db to use the test session; clears overrides after test
```

**Important:** The `db` and `client` fixtures share the **same session object**. Any route that calls `await db.commit()` (e.g. `POST /sessions`, `POST /frames`) permanently commits that data to `test.db`. Data from committed transactions persists across tests within the same run.

---

## Transaction Behaviour

| Operation | Commits? | Effect on other tests |
|---|---|---|
| `POST /v1/sessions` | Yes (`await db.commit()`) | Session row persists in test.db |
| `POST /v1/sessions/{id}/frames` | Yes | Frame + Job rows persist |
| `POST /v1/sessions/{id}/generate` | Yes (via background task) | AI output + quiz rows persist |
| `GET` endpoints | No | No side effects |
| Direct `db.add(); await db.flush()` | No (only flushed) | Visible to other queries in same session; rolled back at end of test |

**Consequence for count assertions:** Use `>= N` not `== N` for counts on shared `TEACHER_ID`, because previous tests may have added data. Use a private UUID that no other test touches if you need exact zero counts.

---

## Key Patterns

### Creating a session with frame + quiz (most common setup)
```python
async def _create_session_with_frame(client) -> tuple[str, str]:
    r = await client.post("/v1/sessions", json=SESSION_PAYLOAD)
    session_id = r.json()["session_id"]
    fr = await client.post(
        f"/v1/sessions/{session_id}/frames",
        files={"image": ("board.jpg", io.BytesIO(_TINY_JPEG), "image/jpeg")},
        data={"captured_at": "2026-05-27T10:00:00Z", "sequence_no": "1",
              "local_frame_id": f"frame-{session_id[:8]}"},
    )
    return session_id, fr.json()["frame_id"]
```

### Waiting for background tasks
```python
await client.post(f"/v1/sessions/{session_id}/generate", json={"outputs": ["quiz"]})
await asyncio.sleep(0.1)  # give the background task one event loop tick
```

### Inserting DB fixtures without HTTP
```python
async def test_admin_report_empty(client, db):
    school_id = uuid.uuid4()
    db.add(School(id=school_id, name="Test School", is_active=True))
    await db.flush()  # visible to queries in this session; rolled back at end of test

    # If you need these rows to survive (e.g. to create sessions against them),
    # make an API call that triggers db.commit() after the flush:
    payload = {**SESSION_PAYLOAD, "teacher_id": str(teacher_id)}
    await client.post("/v1/sessions", json=payload)  # this commits
```

### Direct ORM queries in tests — UUID type matters
```python
import uuid
from sqlalchemy import select
from app.models.quiz_question import QuizQuestion

# CORRECT — pass uuid.UUID object, not a string
rows = await db.execute(
    select(QuizQuestion).where(QuizQuestion.session_id == uuid.UUID(session_id_str))
)

# WRONG — causes 'str object has no attribute .hex'
rows = await db.execute(
    select(QuizQuestion).where(QuizQuestion.session_id == session_id_str)
)
```

### Patching settings inside a route handler
`get_settings()` is called inside the function body, so patch at the import site:
```python
from unittest.mock import patch, MagicMock

mock_cfg = MagicMock()
mock_cfg.max_frame_size_mb = 10
mock_cfg.max_frames_per_session = 1

with patch("app.routers.frames.get_settings", return_value=mock_cfg):
    r = await client.post(...)
```

---

## Test File Breakdown (279 total)

| File | Count | What it covers |
|---|---|---|
| `test_dashboard.py` | 46 | All 9 dashboard/report endpoints, `_sync_health()` unit tests |
| `test_sync.py` | 27 | Device register, bulk upload, retry logic, ack, status |
| `test_tiqer_service.py` | 63 | Payload builder, option keys, correct answer mapping, bloom/difficulty, serialisation |
| `test_ai_service.py` | 41 | All parser functions, prompt builders, token truncation, OCR fallback |
| `test_image_quality.py` | 24 | Type/size/state/frame-limit/timestamp/required-field validation |
| `test_outputs.py` | 22 | Generation, jobs, quiz, TiQer export+preview+audit log+idempotency |
| `test_sessions.py` | 7 | Create, get, patch, list, duplicate local_id, invalid interval |
| `test_frames.py` | 7 | Upload, count increment, dedup 409, wrong type, list, OCR |
| `test_health.py` | 2 | Health endpoint, version field |

---

## Minimal JPEG Fixture

Reused across test files — a valid 1×1 pixel JPEG (~280 bytes):

```python
_TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xd4P\x00\x00\x00\xff\xd9"
)
```

---

## What's Not Covered Yet

- PostgreSQL-specific tests (FK enforcement, `DATE_TRUNC`, concurrent writes)
- End-to-end test with real PaddleOCR output
- Load / performance tests (frame_count at 200-frame limit)
- Admin and CSR frontend page rendering tests
- Mobile Android sync integration tests
