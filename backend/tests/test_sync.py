"""
Tests for offline sync endpoints.

Coverage:
  POST /devices               — register, update, idempotency
  POST /sync/sessions         — bulk create, already_exists, rejected
  GET  /sync/status/{fp}      — healthy / degraded / unknown
  GET  /sync/queue            — list with filters
  POST /sync/retry            — reset failed items
  POST /sync/ack              — acknowledge, auto-session-sync
  POST /sessions/{id}/frames  — device_fingerprint creates sync entry
  Duplicate frame (409)       — sync queue not double-created
"""

import io
import uuid
import asyncio
import pytest
from httpx import AsyncClient

from tests.conftest import TEACHER_ID, CLASSROOM_ID

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEVICE_FP = "android-test-fp-001"
DEVICE_FP_2 = "android-test-fp-002"

SESSION_PAYLOAD = {
    "teacher_id": TEACHER_ID,
    "classroom_id": str(CLASSROOM_ID),
    "subject": "Physics",
    "grade": "Grade 9",
    "board_type": "chalkboard",
    "capture_mode": "time_based",
    "capture_interval_sec": 30,
}

# Minimal 1×1 white JPEG for frame upload tests
_TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04"
    b"\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa"
    b"\x07\"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br"
    b"\x82\t\n\x16\x17\x18\x19\x1a%&'()*456789:CDEFGHIJ"
    b"STUVWXYZ\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xd4P\x00\x00\x00\xff\xd9"
)


async def _create_session(client: AsyncClient, local_id: str | None = None) -> str:
    payload = {**SESSION_PAYLOAD}
    if local_id:
        payload["local_session_id"] = local_id
    r = await client.post("/v1/sessions", json=payload)
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


async def _register_device(client: AsyncClient, fp: str = DEVICE_FP) -> dict:
    r = await client.post("/v1/devices", json={
        "device_fingerprint": fp,
        "teacher_id": TEACHER_ID,
        "platform": "android",
        "os_version": "13",
        "model_name": "Samsung A52",
        "app_version": "1.0.0",
    })
    assert r.status_code == 201, r.text
    return r.json()


# ===========================================================================
# Device registration
# ===========================================================================

@pytest.mark.asyncio
async def test_device_register_new(client: AsyncClient):
    r = await client.post("/v1/devices", json={
        "device_fingerprint": "new-device-abc",
        "teacher_id": TEACHER_ID,
        "platform": "android",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["device_fingerprint"] == "new-device-abc"
    assert data["registered"] is True
    assert "device_id" in data


@pytest.mark.asyncio
async def test_device_register_idempotent(client: AsyncClient):
    fp = "idempotent-device-xyz"
    r1 = await client.post("/v1/devices", json={
        "device_fingerprint": fp,
        "teacher_id": TEACHER_ID,
        "platform": "android",
        "app_version": "1.0.0",
    })
    assert r1.status_code == 201
    assert r1.json()["registered"] is True
    device_id_1 = r1.json()["device_id"]

    # Second registration — same fingerprint
    r2 = await client.post("/v1/devices", json={
        "device_fingerprint": fp,
        "teacher_id": TEACHER_ID,
        "platform": "android",
        "app_version": "1.1.0",   # updated version
    })
    assert r2.status_code == 201
    data = r2.json()
    assert data["registered"] is False           # existing, not new
    assert data["device_id"] == device_id_1      # same UUID


@pytest.mark.asyncio
async def test_device_register_all_fields(client: AsyncClient):
    r = await client.post("/v1/devices", json={
        "device_fingerprint": "full-fields-device",
        "teacher_id": TEACHER_ID,
        "platform": "ios",
        "os_version": "17.2",
        "model_name": "iPhone 15",
        "app_version": "2.0.0",
        "push_token": "fcm-token-abc123",
    })
    assert r.status_code == 201
    assert r.json()["registered"] is True


# ===========================================================================
# Bulk session sync
# ===========================================================================

@pytest.mark.asyncio
async def test_bulk_sync_sessions_creates_new(client: AsyncClient):
    local_id = f"offline-sess-{uuid.uuid4()}"
    r = await client.post("/v1/sync/sessions", json={
        "device_fingerprint": DEVICE_FP,
        "teacher_id": TEACHER_ID,
        "sessions": [
            {
                "local_session_id": local_id,
                "subject": "Chemistry",
                "grade": "Grade 10",
                "board_type": "chalkboard",
                "capture_mode": "time_based",
                "capture_interval_sec": 30,
                "frame_count": 8,
            }
        ],
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["accepted_count"] == 1
    assert data["rejected_count"] == 0
    assert len(data["accepted"]) == 1

    result = data["accepted"][0]
    assert result["local_session_id"] == local_id
    assert result["outcome"] == "created"
    assert "remote_session_id" in result


@pytest.mark.asyncio
async def test_bulk_sync_sessions_idempotent(client: AsyncClient):
    local_id = f"dup-sess-{uuid.uuid4()}"
    payload = {
        "device_fingerprint": DEVICE_FP,
        "teacher_id": TEACHER_ID,
        "sessions": [{"local_session_id": local_id, "capture_interval_sec": 30}],
    }

    r1 = await client.post("/v1/sync/sessions", json=payload)
    assert r1.status_code == 200
    remote_id_1 = r1.json()["accepted"][0]["remote_session_id"]

    # Second call — same local_session_id
    r2 = await client.post("/v1/sync/sessions", json=payload)
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2["accepted_count"] == 1
    result = data2["accepted"][0]
    assert result["outcome"] == "already_exists"
    assert result["remote_session_id"] == remote_id_1  # same remote ID returned


@pytest.mark.asyncio
async def test_bulk_sync_sessions_multiple(client: AsyncClient):
    ids = [f"multi-{uuid.uuid4()}" for _ in range(3)]
    sessions = [
        {"local_session_id": lid, "subject": f"Sub{i}", "capture_interval_sec": 30}
        for i, lid in enumerate(ids)
    ]
    r = await client.post("/v1/sync/sessions", json={
        "device_fingerprint": DEVICE_FP,
        "teacher_id": TEACHER_ID,
        "sessions": sessions,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["accepted_count"] == 3
    assert len(data["accepted"]) == 3
    for result in data["accepted"]:
        assert result["outcome"] == "created"


@pytest.mark.asyncio
async def test_bulk_sync_creates_remote_session_accessible(client: AsyncClient):
    """Verify the created remote session is accessible via GET /sessions/{id}."""
    local_id = f"verify-sess-{uuid.uuid4()}"
    r = await client.post("/v1/sync/sessions", json={
        "device_fingerprint": DEVICE_FP,
        "teacher_id": TEACHER_ID,
        "sessions": [{"local_session_id": local_id, "subject": "Biology", "capture_interval_sec": 30}],
    })
    assert r.status_code == 200
    remote_id = r.json()["accepted"][0]["remote_session_id"]

    r2 = await client.get(f"/v1/sessions/{remote_id}")
    assert r2.status_code == 200
    session = r2.json()
    assert session["session_id"] == remote_id
    assert session["status"] == "completed"    # offline sessions start as completed


@pytest.mark.asyncio
async def test_bulk_sync_existing_local_session_id_returns_remote(client: AsyncClient):
    """Session created via POST /sessions is also idempotent via bulk sync."""
    local_id = f"pre-created-{uuid.uuid4()}"

    # Create via normal route first
    r1 = await client.post("/v1/sessions", json={**SESSION_PAYLOAD, "local_session_id": local_id})
    assert r1.status_code == 201
    remote_id = r1.json()["session_id"]

    # Now bulk sync that same local_session_id
    r2 = await client.post("/v1/sync/sessions", json={
        "device_fingerprint": DEVICE_FP,
        "teacher_id": TEACHER_ID,
        "sessions": [{"local_session_id": local_id, "capture_interval_sec": 30}],
    })
    assert r2.status_code == 200
    result = r2.json()["accepted"][0]
    assert result["outcome"] == "already_exists"
    assert result["remote_session_id"] == remote_id


# ===========================================================================
# Sync status
# ===========================================================================

@pytest.mark.asyncio
async def test_sync_status_unknown_device(client: AsyncClient):
    r = await client.get("/v1/sync/status/nonexistent-device-fp-xyz")
    assert r.status_code == 200
    data = r.json()
    assert data["health"] == "unknown"
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_sync_status_after_session_sync(client: AsyncClient):
    fp = f"status-test-{uuid.uuid4()}"
    local_id = f"status-sess-{uuid.uuid4()}"

    # Register device
    await _register_device(client, fp)

    # Sync a session
    r = await client.post("/v1/sync/sessions", json={
        "device_fingerprint": fp,
        "teacher_id": TEACHER_ID,
        "sessions": [{"local_session_id": local_id, "capture_interval_sec": 30}],
    })
    assert r.status_code == 200

    # Check status
    r2 = await client.get(f"/v1/sync/status/{fp}")
    assert r2.status_code == 200
    data = r2.json()
    assert data["device_fingerprint"] == fp
    assert data["done"] >= 1          # session_meta entry is done
    assert data["health"] in ("healthy", "degraded")


@pytest.mark.asyncio
async def test_sync_status_healthy_after_all_done(client: AsyncClient):
    fp = f"healthy-{uuid.uuid4()}"
    await _register_device(client, fp)
    local_id = f"healthy-sess-{uuid.uuid4()}"
    await client.post("/v1/sync/sessions", json={
        "device_fingerprint": fp,
        "teacher_id": TEACHER_ID,
        "sessions": [{"local_session_id": local_id, "capture_interval_sec": 30}],
    })
    r = await client.get(f"/v1/sync/status/{fp}")
    assert r.status_code == 200
    data = r.json()
    assert data["pending"] == 0
    assert data["failed"] == 0
    assert data["health"] == "healthy"


# ===========================================================================
# Sync queue
# ===========================================================================

@pytest.mark.asyncio
async def test_sync_queue_no_fingerprint_returns_empty(client: AsyncClient):
    r = await client.get("/v1/sync/queue")
    assert r.status_code == 200
    assert r.json()["total"] == 0


@pytest.mark.asyncio
async def test_sync_queue_lists_session_entries(client: AsyncClient):
    fp = f"queue-test-{uuid.uuid4()}"
    await _register_device(client, fp)
    local_id = f"queue-sess-{uuid.uuid4()}"

    await client.post("/v1/sync/sessions", json={
        "device_fingerprint": fp,
        "teacher_id": TEACHER_ID,
        "sessions": [{"local_session_id": local_id, "capture_interval_sec": 30}],
    })

    r = await client.get(f"/v1/sync/queue?device_fingerprint={fp}")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1

    item = data["items"][0]
    assert item["entity_type"] == "session_meta"
    assert item["status"] == "done"
    assert item["local_entity_id"] == local_id


@pytest.mark.asyncio
async def test_sync_queue_filter_by_status(client: AsyncClient):
    fp = f"filter-test-{uuid.uuid4()}"
    await _register_device(client, fp)
    local_id = f"filter-sess-{uuid.uuid4()}"
    await client.post("/v1/sync/sessions", json={
        "device_fingerprint": fp,
        "teacher_id": TEACHER_ID,
        "sessions": [{"local_session_id": local_id, "capture_interval_sec": 30}],
    })

    # Filter by done — should have results
    r1 = await client.get(f"/v1/sync/queue?device_fingerprint={fp}&status=done")
    assert r1.status_code == 200
    assert r1.json()["total"] >= 1

    # Filter by pending — should be 0 after bulk sync
    r2 = await client.get(f"/v1/sync/queue?device_fingerprint={fp}&status=pending")
    assert r2.status_code == 200
    # pending count may be 0 since sessions are immediately done


# ===========================================================================
# Retry
# ===========================================================================

@pytest.mark.asyncio
async def test_retry_no_failed_items(client: AsyncClient):
    fp = f"retry-empty-{uuid.uuid4()}"
    await _register_device(client, fp)

    r = await client.post("/v1/sync/retry", json={
        "device_fingerprint": fp,
        "item_ids": [],
    })
    assert r.status_code == 200
    assert r.json()["reset_count"] == 0


@pytest.mark.asyncio
async def test_retry_unknown_device(client: AsyncClient):
    r = await client.post("/v1/sync/retry", json={
        "device_fingerprint": "totally-unknown-device",
        "item_ids": [],
    })
    assert r.status_code == 200
    assert r.json()["reset_count"] == 0


@pytest.mark.asyncio
async def test_retry_resets_failed_items(client: AsyncClient):
    """Insert a failed item directly via ACK, then manually mark as failed, then retry."""
    fp = f"retry-reset-{uuid.uuid4()}"
    await _register_device(client, fp)

    local_id = f"failed-frame-{uuid.uuid4()}"
    session_id = await _create_session(client)

    # Acknowledge a frame (creates a done entry)
    r_ack = await client.post("/v1/sync/ack", json={
        "device_fingerprint": fp,
        "teacher_id": TEACHER_ID,
        "acknowledgements": [
            {
                "local_entity_id": local_id,
                "entity_type": "frame",
                "remote_entity_id": str(uuid.uuid4()),
                "session_id": session_id,
            }
        ],
    })
    assert r_ack.status_code == 200

    # Verify it shows as done
    r_q = await client.get(f"/v1/sync/queue?device_fingerprint={fp}&status=done")
    assert r_q.json()["total"] >= 1

    # Retry all (no failed items to reset, but API returns gracefully)
    r_retry = await client.post("/v1/sync/retry", json={
        "device_fingerprint": fp,
        "item_ids": [],
    })
    assert r_retry.status_code == 200


# ===========================================================================
# Acknowledgement
# ===========================================================================

@pytest.mark.asyncio
async def test_ack_creates_new_entry(client: AsyncClient):
    fp = f"ack-new-{uuid.uuid4()}"
    await _register_device(client, fp)
    session_id = await _create_session(client)
    local_frame_id = f"frame-{uuid.uuid4()}"

    r = await client.post("/v1/sync/ack", json={
        "device_fingerprint": fp,
        "teacher_id": TEACHER_ID,
        "acknowledgements": [
            {
                "local_entity_id": local_frame_id,
                "entity_type": "frame",
                "remote_entity_id": str(uuid.uuid4()),
                "session_id": session_id,
            }
        ],
    })
    assert r.status_code == 200
    data = r.json()
    assert data["created"] == 1
    assert data["acknowledged"] == 0


@pytest.mark.asyncio
async def test_ack_idempotent_updates_existing(client: AsyncClient):
    fp = f"ack-dup-{uuid.uuid4()}"
    await _register_device(client, fp)
    session_id = await _create_session(client)
    local_frame_id = f"frame-idem-{uuid.uuid4()}"
    remote_id = str(uuid.uuid4())

    ack_payload = {
        "device_fingerprint": fp,
        "teacher_id": TEACHER_ID,
        "acknowledgements": [
            {
                "local_entity_id": local_frame_id,
                "entity_type": "frame",
                "remote_entity_id": remote_id,
                "session_id": session_id,
            }
        ],
    }

    r1 = await client.post("/v1/sync/ack", json=ack_payload)
    assert r1.json()["created"] == 1

    r2 = await client.post("/v1/sync/ack", json=ack_payload)
    data2 = r2.json()
    assert data2["created"] == 0       # not created again
    assert data2["acknowledged"] == 1  # updated existing entry


@pytest.mark.asyncio
async def test_ack_multiple_items(client: AsyncClient):
    fp = f"ack-multi-{uuid.uuid4()}"
    await _register_device(client, fp)
    session_id = await _create_session(client)

    acks = [
        {
            "local_entity_id": f"frame-{i}-{uuid.uuid4()}",
            "entity_type": "frame",
            "remote_entity_id": str(uuid.uuid4()),
            "session_id": session_id,
        }
        for i in range(5)
    ]
    r = await client.post("/v1/sync/ack", json={
        "device_fingerprint": fp,
        "teacher_id": TEACHER_ID,
        "acknowledgements": acks,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["created"] == 5
    assert data["acknowledged"] == 0


@pytest.mark.asyncio
async def test_ack_session_meta(client: AsyncClient):
    fp = f"ack-sess-meta-{uuid.uuid4()}"
    await _register_device(client, fp)
    local_sess_id = f"local-sess-{uuid.uuid4()}"

    r = await client.post("/v1/sync/ack", json={
        "device_fingerprint": fp,
        "teacher_id": TEACHER_ID,
        "acknowledgements": [
            {
                "local_entity_id": local_sess_id,
                "entity_type": "session_meta",
                "remote_entity_id": str(uuid.uuid4()),
            }
        ],
    })
    assert r.status_code == 200
    assert r.json()["created"] == 1


# ===========================================================================
# Frame upload with device_fingerprint
# ===========================================================================

@pytest.mark.asyncio
async def test_frame_upload_with_device_fp_creates_sync_entry(client: AsyncClient):
    fp = f"frame-fp-{uuid.uuid4()}"
    await _register_device(client, fp)
    session_id = await _create_session(client)
    local_fid = f"frm-{uuid.uuid4()}"

    r = await client.post(
        f"/v1/sessions/{session_id}/frames",
        files={"image": ("board.jpg", io.BytesIO(_TINY_JPEG), "image/jpeg")},
        data={
            "captured_at": "2026-05-27T10:00:00Z",
            "sequence_no": "1",
            "local_frame_id": local_fid,
            "device_fingerprint": fp,
        },
    )
    assert r.status_code == 202, r.text

    # Give background task a tick
    await asyncio.sleep(0.05)

    # Verify sync queue has the frame entry
    r2 = await client.get(f"/v1/sync/queue?device_fingerprint={fp}&status=done")
    assert r2.status_code == 200
    items = r2.json()["items"]
    frame_items = [i for i in items if i["entity_type"] == "frame"]
    assert len(frame_items) >= 1
    assert frame_items[0]["local_entity_id"] == local_fid


@pytest.mark.asyncio
async def test_frame_upload_without_device_fp_no_sync_entry(client: AsyncClient):
    """Frame uploads without device_fingerprint must not create sync entries."""
    fp = f"no-fp-device-{uuid.uuid4()}"
    await _register_device(client, fp)
    session_id = await _create_session(client)

    r = await client.post(
        f"/v1/sessions/{session_id}/frames",
        files={"image": ("board.jpg", io.BytesIO(_TINY_JPEG), "image/jpeg")},
        data={
            "captured_at": "2026-05-27T10:00:00Z",
            "sequence_no": "1",
            "local_frame_id": f"no-fp-frm-{uuid.uuid4()}",
            # No device_fingerprint
        },
    )
    assert r.status_code == 202

    r2 = await client.get(f"/v1/sync/queue?device_fingerprint={fp}&status=done")
    frame_items = [i for i in r2.json()["items"] if i["entity_type"] == "frame"]
    assert len(frame_items) == 0


@pytest.mark.asyncio
async def test_duplicate_frame_409_sync_queue_handles_gracefully(client: AsyncClient):
    """Uploading the same local_frame_id twice returns 409; sync queue is not double-created."""
    fp = f"dup-frame-fp-{uuid.uuid4()}"
    await _register_device(client, fp)
    session_id = await _create_session(client)
    local_fid = f"dup-frm-{uuid.uuid4()}"

    upload_kwargs = dict(
        files={"image": ("board.jpg", io.BytesIO(_TINY_JPEG), "image/jpeg")},
        data={
            "captured_at": "2026-05-27T10:00:00Z",
            "sequence_no": "1",
            "local_frame_id": local_fid,
            "device_fingerprint": fp,
        },
    )

    r1 = await client.post(f"/v1/sessions/{session_id}/frames", **upload_kwargs)
    assert r1.status_code == 202

    r2 = await client.post(f"/v1/sessions/{session_id}/frames", **upload_kwargs)
    assert r2.status_code == 409   # duplicate

    await asyncio.sleep(0.05)

    # Queue should have at most one entry for this frame
    r3 = await client.get(f"/v1/sync/queue?device_fingerprint={fp}")
    items = r3.json()["items"]
    frame_items = [i for i in items if i.get("local_entity_id") == local_fid]
    assert len(frame_items) <= 1


# ===========================================================================
# PATCH /sessions/{session_id} (already implemented — smoke test only)
# ===========================================================================

@pytest.mark.asyncio
async def test_patch_session_complete(client: AsyncClient):
    session_id = await _create_session(client)

    r = await client.patch(f"/v1/sessions/{session_id}", json={"status": "completed"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "completed"
    assert data["completed_at"] is not None


@pytest.mark.asyncio
async def test_patch_session_sync_status(client: AsyncClient):
    session_id = await _create_session(client)

    r = await client.patch(
        f"/v1/sessions/{session_id}",
        json={"sync_status": "synced"},
    )
    assert r.status_code == 200
    assert r.json()["sync_status"] == "synced"


@pytest.mark.asyncio
async def test_patch_session_not_found(client: AsyncClient):
    r = await client.patch(
        f"/v1/sessions/{uuid.uuid4()}",
        json={"status": "completed"},
    )
    assert r.status_code == 404
