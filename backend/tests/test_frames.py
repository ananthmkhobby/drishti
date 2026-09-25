import io
import asyncio
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

# Minimal 1x1 white JPEG (~631 bytes) — valid image for upload tests
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


async def _create_session(client: AsyncClient) -> str:
    r = await client.post("/v1/sessions", json=SESSION_PAYLOAD)
    assert r.status_code == 201
    return r.json()["session_id"]


@pytest.mark.asyncio
async def test_upload_frame(client: AsyncClient):
    session_id = await _create_session(client)

    r = await client.post(
        f"/v1/sessions/{session_id}/frames",
        files={"image": ("board.jpg", io.BytesIO(_TINY_JPEG), "image/jpeg")},
        data={
            "captured_at": "2026-05-27T10:00:00Z",
            "sequence_no": "1",
            "local_frame_id": "frame-local-001",
        },
    )
    assert r.status_code == 202
    body = r.json()
    assert "frame_id" in body
    assert body["status"] == "queued"
    assert body["message"] == "Frame queued for processing"


@pytest.mark.asyncio
async def test_upload_frame_increments_count(client: AsyncClient):
    session_id = await _create_session(client)

    await client.post(
        f"/v1/sessions/{session_id}/frames",
        files={"image": ("board.jpg", io.BytesIO(_TINY_JPEG), "image/jpeg")},
        data={"captured_at": "2026-05-27T10:00:00Z", "sequence_no": "1", "local_frame_id": "fc-001"},
    )

    r = await client.get(f"/v1/sessions/{session_id}")
    assert r.json()["frame_count"] == 1


@pytest.mark.asyncio
async def test_duplicate_frame_returns_409(client: AsyncClient):
    session_id = await _create_session(client)

    data = {"captured_at": "2026-05-27T10:00:00Z", "sequence_no": "1", "local_frame_id": "dedup-001"}
    files = {"image": ("board.jpg", io.BytesIO(_TINY_JPEG), "image/jpeg")}

    r1 = await client.post(f"/v1/sessions/{session_id}/frames", files=files, data=data)
    assert r1.status_code == 202

    files2 = {"image": ("board.jpg", io.BytesIO(_TINY_JPEG), "image/jpeg")}
    r2 = await client.post(f"/v1/sessions/{session_id}/frames", files=files2, data=data)
    assert r2.status_code == 409
    assert r2.json()["error"] == "DUPLICATE_FRAME"


@pytest.mark.asyncio
async def test_upload_wrong_content_type(client: AsyncClient):
    session_id = await _create_session(client)

    r = await client.post(
        f"/v1/sessions/{session_id}/frames",
        files={"image": ("doc.pdf", io.BytesIO(b"%PDF"), "application/pdf")},
        data={"captured_at": "2026-05-27T10:00:00Z", "sequence_no": "1", "local_frame_id": "bad-001"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "INVALID_IMAGE_TYPE"


@pytest.mark.asyncio
async def test_list_frames(client: AsyncClient):
    session_id = await _create_session(client)

    for i in range(3):
        await client.post(
            f"/v1/sessions/{session_id}/frames",
            files={"image": ("board.jpg", io.BytesIO(_TINY_JPEG), "image/jpeg")},
            data={
                "captured_at": "2026-05-27T10:00:00Z",
                "sequence_no": str(i + 1),
                "local_frame_id": f"list-frame-{i}",
            },
        )

    r = await client.get(f"/v1/sessions/{session_id}/frames")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["frames"]) == 3
    # Frames ordered by sequence_no
    seq_nos = [f["sequence_no"] for f in body["frames"]]
    assert seq_nos == [1, 2, 3]


@pytest.mark.asyncio
async def test_get_ocr_result_after_background_task(client: AsyncClient):
    session_id = await _create_session(client)

    r = await client.post(
        f"/v1/sessions/{session_id}/frames",
        files={"image": ("board.jpg", io.BytesIO(_TINY_JPEG), "image/jpeg")},
        data={
            "captured_at": "2026-05-27T10:00:00Z",
            "sequence_no": "1",
            "local_frame_id": "ocr-test-001",
        },
    )
    frame_id = r.json()["frame_id"]

    # Background task runs async — give it a tick to complete
    await asyncio.sleep(0.1)

    r2 = await client.get(f"/v1/frames/{frame_id}/ocr")
    assert r2.status_code == 200
    body = r2.json()
    assert body["frame_id"] == frame_id
    assert "ocr_text" in body
    assert body["engine_used"] == "placeholder"


@pytest.mark.asyncio
async def test_get_ocr_not_found(client: AsyncClient):
    r = await client.get("/v1/frames/00000000-0000-0000-0000-000000000000/ocr")
    assert r.status_code == 404
    assert r.json()["error"] == "FRAME_NOT_FOUND"
