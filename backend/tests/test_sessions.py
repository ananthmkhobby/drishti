import pytest
from httpx import AsyncClient
from tests.conftest import TEACHER_ID, CLASSROOM_ID


SESSION_PAYLOAD = {
    "teacher_id": TEACHER_ID,
    "classroom_id": CLASSROOM_ID,
    "subject": "Physics",
    "grade": "Grade 9",
    "board_type": "chalkboard",
    "capture_mode": "time_based",
    "capture_interval_sec": 30,
}


@pytest.mark.asyncio
async def test_create_session(client: AsyncClient):
    r = await client.post("/v1/sessions", json=SESSION_PAYLOAD)
    assert r.status_code == 201
    body = r.json()
    assert "session_id" in body
    assert body["status"] == "active"
    assert "created_at" in body


@pytest.mark.asyncio
async def test_get_session(client: AsyncClient):
    create = await client.post("/v1/sessions", json=SESSION_PAYLOAD)
    session_id = create.json()["session_id"]

    r = await client.get(f"/v1/sessions/{session_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == session_id
    assert body["subject"] == "Physics"
    assert body["grade"] == "Grade 9"
    assert body["board_type"] == "chalkboard"
    assert body["frame_count"] == 0
    assert body["sync_status"] == "pending"


@pytest.mark.asyncio
async def test_get_session_not_found(client: AsyncClient):
    r = await client.get("/v1/sessions/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
    assert r.json()["error"] == "SESSION_NOT_FOUND"


@pytest.mark.asyncio
async def test_patch_session_complete(client: AsyncClient):
    create = await client.post("/v1/sessions", json=SESSION_PAYLOAD)
    session_id = create.json()["session_id"]

    r = await client.patch(f"/v1/sessions/{session_id}", json={"status": "completed"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["completed_at"] is not None


@pytest.mark.asyncio
async def test_list_sessions(client: AsyncClient):
    await client.post("/v1/sessions", json=SESSION_PAYLOAD)
    await client.post("/v1/sessions", json=SESSION_PAYLOAD)

    r = await client.get(f"/v1/sessions?teacher_id={TEACHER_ID}&limit=10")
    assert r.status_code == 200
    body = r.json()
    assert "sessions" in body
    assert body["total"] >= 2
    assert len(body["sessions"]) >= 2


@pytest.mark.asyncio
async def test_create_session_duplicate_local_id(client: AsyncClient):
    payload = {**SESSION_PAYLOAD, "local_session_id": "test-local-001"}
    r1 = await client.post("/v1/sessions", json=payload)
    assert r1.status_code == 201

    r2 = await client.post("/v1/sessions", json=payload)
    assert r2.status_code == 409
    assert r2.json()["error"] == "DUPLICATE_SESSION"


@pytest.mark.asyncio
async def test_create_session_invalid_interval(client: AsyncClient):
    payload = {**SESSION_PAYLOAD, "capture_interval_sec": 5}  # below minimum of 10
    r = await client.post("/v1/sessions", json=payload)
    assert r.status_code == 422
    assert r.json()["error"] == "VALIDATION_ERROR"
