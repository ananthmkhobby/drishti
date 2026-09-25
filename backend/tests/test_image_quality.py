"""
Tests for frame upload validation — image type, file size, session state, frame limits,
timestamp parsing, and required-field enforcement.

These complement test_frames.py with edge-case and boundary coverage.

Run:
    cd backend && source .venv/bin/activate
    python -m pytest tests/test_image_quality.py -v
"""

import io
import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from tests.conftest import TEACHER_ID, CLASSROOM_ID

# ── Shared image fixtures ─────────────────────────────────────────────────────

# Minimal valid 1x1 JPEG (~280 bytes)
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

# Minimal valid 1x1 PNG (67 bytes)
_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x81\x81D\x85\xf2X\x00\x00\x00\x00IEND\xaeB`\x82"
)

SESSION_PAYLOAD = {
    "teacher_id": TEACHER_ID,
    "classroom_id": CLASSROOM_ID,
    "subject": "Physics",
    "grade": "Grade 9",
    "board_type": "chalkboard",
    "capture_mode": "time_based",
    "capture_interval_sec": 30,
}

UPLOAD_META = {
    "captured_at": "2026-05-27T10:00:00Z",
    "sequence_no": "1",
    "local_frame_id": "iq-test-001",
}


async def _create_session(client: AsyncClient) -> str:
    r = await client.post("/v1/sessions", json=SESSION_PAYLOAD)
    assert r.status_code == 201
    return r.json()["session_id"]


async def _upload(client: AsyncClient, session_id: str,
                  filename: str, data: bytes, content_type: str,
                  local_id: str = "iq-001", seq: str = "1"):
    return await client.post(
        f"/v1/sessions/{session_id}/frames",
        files={"image": (filename, io.BytesIO(data), content_type)},
        data={"captured_at": "2026-05-27T10:00:00Z", "sequence_no": seq,
              "local_frame_id": local_id},
    )


# ── Accepted image types ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_jpeg_is_accepted(client: AsyncClient):
    """JPEG images (image/jpeg) are accepted → 202."""
    sid = await _create_session(client)
    r = await _upload(client, sid, "photo.jpg", _TINY_JPEG, "image/jpeg", "acc-jpeg-001")
    assert r.status_code == 202
    assert r.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_png_is_accepted(client: AsyncClient):
    """PNG images (image/png) are accepted → 202 (both board capture formats are valid)."""
    sid = await _create_session(client)
    r = await _upload(client, sid, "board.png", _TINY_PNG, "image/png", "acc-png-001")
    assert r.status_code == 202
    assert r.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_jpg_content_type_is_accepted(client: AsyncClient):
    """image/jpg (non-canonical but common) is also accepted → 202."""
    sid = await _create_session(client)
    r = await _upload(client, sid, "board.jpg", _TINY_JPEG, "image/jpg", "acc-jpg-001")
    assert r.status_code == 202


# ── Rejected image types ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pdf_is_rejected_with_invalid_image_type(client: AsyncClient):
    """PDF upload → 400 INVALID_IMAGE_TYPE."""
    sid = await _create_session(client)
    r = await _upload(client, sid, "doc.pdf", b"%PDF-1.4", "application/pdf", "rej-pdf-001")
    assert r.status_code == 400
    assert r.json()["error"] == "INVALID_IMAGE_TYPE"


@pytest.mark.asyncio
async def test_gif_is_rejected_with_invalid_image_type(client: AsyncClient):
    """GIF upload → 400 INVALID_IMAGE_TYPE."""
    sid = await _create_session(client)
    r = await _upload(client, sid, "anim.gif", b"GIF89a", "image/gif", "rej-gif-001")
    assert r.status_code == 400
    assert r.json()["error"] == "INVALID_IMAGE_TYPE"


@pytest.mark.asyncio
async def test_webp_is_rejected_with_invalid_image_type(client: AsyncClient):
    """WebP upload → 400 INVALID_IMAGE_TYPE (only JPEG/PNG accepted)."""
    sid = await _create_session(client)
    r = await _upload(client, sid, "capture.webp", b"RIFF\x00\x00\x00\x00WEBPVP8 ",
                      "image/webp", "rej-webp-001")
    assert r.status_code == 400
    assert r.json()["error"] == "INVALID_IMAGE_TYPE"


@pytest.mark.asyncio
async def test_bmp_is_rejected_with_invalid_image_type(client: AsyncClient):
    """BMP upload → 400 INVALID_IMAGE_TYPE."""
    sid = await _create_session(client)
    r = await _upload(client, sid, "pic.bmp", b"BM\x00\x00\x00\x00", "image/bmp", "rej-bmp-001")
    assert r.status_code == 400
    assert r.json()["error"] == "INVALID_IMAGE_TYPE"


@pytest.mark.asyncio
async def test_plain_text_is_rejected_with_invalid_image_type(client: AsyncClient):
    """Plain-text upload → 400 INVALID_IMAGE_TYPE."""
    sid = await _create_session(client)
    r = await _upload(client, sid, "note.txt", b"hello world", "text/plain", "rej-txt-001")
    assert r.status_code == 400
    assert r.json()["error"] == "INVALID_IMAGE_TYPE"


# ── File size validation ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_oversized_image_rejected(client: AsyncClient):
    """Image larger than 10 MB → 400 IMAGE_TOO_LARGE."""
    sid = await _create_session(client)
    # 11 MB: prepend JPEG header bytes so content_type is valid but size exceeds limit
    oversized = _TINY_JPEG[:3] + b"\x00" * (11 * 1024 * 1024)
    r = await _upload(client, sid, "big.jpg", oversized, "image/jpeg", "size-big-001")
    assert r.status_code == 400
    assert r.json()["error"] == "IMAGE_TOO_LARGE"


@pytest.mark.asyncio
async def test_small_image_not_rejected_for_size(client: AsyncClient):
    """Tiny JPEG well under 1 MB is not rejected for size."""
    sid = await _create_session(client)
    r = await _upload(client, sid, "tiny.jpg", _TINY_JPEG, "image/jpeg", "size-tiny-001")
    assert r.status_code == 202


# ── Session state validation ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_to_completed_session_rejected(client: AsyncClient):
    """Frames cannot be uploaded to a completed session → 400 SESSION_NOT_ACTIVE."""
    sid = await _create_session(client)

    patch_r = await client.patch(f"/v1/sessions/{sid}", json={"status": "completed"})
    assert patch_r.status_code == 200
    assert patch_r.json()["status"] == "completed"

    r = await _upload(client, sid, "board.jpg", _TINY_JPEG, "image/jpeg", "state-comp-001")
    assert r.status_code == 400
    assert r.json()["error"] == "SESSION_NOT_ACTIVE"


@pytest.mark.asyncio
async def test_upload_to_active_session_accepted(client: AsyncClient):
    """Frames can be uploaded to an active session → 202."""
    sid = await _create_session(client)
    r = await _upload(client, sid, "board.jpg", _TINY_JPEG, "image/jpeg", "state-active-001")
    assert r.status_code == 202


@pytest.mark.asyncio
async def test_upload_to_nonexistent_session_returns_404(client: AsyncClient):
    """Session that does not exist → 404 SESSION_NOT_FOUND."""
    r = await _upload(
        client, "00000000-0000-0000-0000-000000000000",
        "board.jpg", _TINY_JPEG, "image/jpeg", "state-gone-001",
    )
    assert r.status_code == 404
    assert r.json()["error"] == "SESSION_NOT_FOUND"


# ── Frame limit enforcement ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_frame_limit_reached_error(client: AsyncClient):
    """When max_frames_per_session is mocked to 1, the 2nd upload returns FRAME_LIMIT_REACHED."""
    sid = await _create_session(client)

    mock_cfg = MagicMock()
    mock_cfg.max_frame_size_mb = 10
    mock_cfg.max_frames_per_session = 1

    with patch("app.routers.frames.get_settings", return_value=mock_cfg):
        # First upload — within limit
        r1 = await _upload(client, sid, "board.jpg", _TINY_JPEG, "image/jpeg", "limit-first")
        assert r1.status_code == 202, f"Expected 202, got {r1.status_code}: {r1.text}"

        # Second upload — limit exceeded
        r2 = await _upload(client, sid, "board.jpg", _TINY_JPEG, "image/jpeg", "limit-second", "2")
        assert r2.status_code == 400
        assert r2.json()["error"] == "FRAME_LIMIT_REACHED"


@pytest.mark.asyncio
async def test_duplicate_local_frame_id_returns_409(client: AsyncClient):
    """Re-uploading the same local_frame_id → 409 DUPLICATE_FRAME."""
    sid = await _create_session(client)

    data = {"captured_at": "2026-05-27T10:00:00Z", "sequence_no": "1",
            "local_frame_id": "dedup-iq-001"}
    files = {"image": ("board.jpg", io.BytesIO(_TINY_JPEG), "image/jpeg")}

    r1 = await client.post(f"/v1/sessions/{sid}/frames", files=files, data=data)
    assert r1.status_code == 202

    files2 = {"image": ("board.jpg", io.BytesIO(_TINY_JPEG), "image/jpeg")}
    r2 = await client.post(f"/v1/sessions/{sid}/frames", files=files2, data=data)
    assert r2.status_code == 409
    assert r2.json()["error"] == "DUPLICATE_FRAME"


# ── Timestamp validation ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_timestamp_returns_400(client: AsyncClient):
    """Malformed captured_at value → 400 INVALID_TIMESTAMP."""
    sid = await _create_session(client)
    r = await client.post(
        f"/v1/sessions/{sid}/frames",
        files={"image": ("board.jpg", io.BytesIO(_TINY_JPEG), "image/jpeg")},
        data={"captured_at": "not-a-date", "sequence_no": "1",
              "local_frame_id": "ts-bad-001"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "INVALID_TIMESTAMP"


@pytest.mark.asyncio
async def test_dd_mm_yyyy_timestamp_returns_400(client: AsyncClient):
    """DD/MM/YYYY is not ISO 8601 → 400 INVALID_TIMESTAMP."""
    sid = await _create_session(client)
    r = await client.post(
        f"/v1/sessions/{sid}/frames",
        files={"image": ("board.jpg", io.BytesIO(_TINY_JPEG), "image/jpeg")},
        data={"captured_at": "27/05/2026", "sequence_no": "1",
              "local_frame_id": "ts-dmy-001"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "INVALID_TIMESTAMP"


@pytest.mark.asyncio
async def test_valid_iso_timestamp_accepted(client: AsyncClient):
    """Correct ISO 8601 timestamp with Z suffix is accepted."""
    sid = await _create_session(client)
    r = await client.post(
        f"/v1/sessions/{sid}/frames",
        files={"image": ("board.jpg", io.BytesIO(_TINY_JPEG), "image/jpeg")},
        data={"captured_at": "2026-05-27T10:30:00Z", "sequence_no": "1",
              "local_frame_id": "ts-valid-001"},
    )
    assert r.status_code == 202


@pytest.mark.asyncio
async def test_iso_timestamp_with_offset_accepted(client: AsyncClient):
    """ISO 8601 with explicit timezone offset (+05:30) is accepted."""
    sid = await _create_session(client)
    r = await client.post(
        f"/v1/sessions/{sid}/frames",
        files={"image": ("board.jpg", io.BytesIO(_TINY_JPEG), "image/jpeg")},
        data={"captured_at": "2026-05-27T15:30:00+05:30", "sequence_no": "1",
              "local_frame_id": "ts-offset-001"},
    )
    assert r.status_code == 202


# ── Missing required form fields ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_sequence_no_returns_422(client: AsyncClient):
    """Omitting required sequence_no form field → 422 Unprocessable Entity."""
    sid = await _create_session(client)
    r = await client.post(
        f"/v1/sessions/{sid}/frames",
        files={"image": ("board.jpg", io.BytesIO(_TINY_JPEG), "image/jpeg")},
        data={"captured_at": "2026-05-27T10:00:00Z", "local_frame_id": "miss-seq-001"},
        # sequence_no deliberately omitted
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_missing_local_frame_id_returns_422(client: AsyncClient):
    """Omitting required local_frame_id form field → 422 Unprocessable Entity."""
    sid = await _create_session(client)
    r = await client.post(
        f"/v1/sessions/{sid}/frames",
        files={"image": ("board.jpg", io.BytesIO(_TINY_JPEG), "image/jpeg")},
        data={"captured_at": "2026-05-27T10:00:00Z", "sequence_no": "1"},
        # local_frame_id deliberately omitted
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_missing_image_field_returns_422(client: AsyncClient):
    """Omitting the image file entirely → 422 Unprocessable Entity."""
    sid = await _create_session(client)
    r = await client.post(
        f"/v1/sessions/{sid}/frames",
        data={"captured_at": "2026-05-27T10:00:00Z", "sequence_no": "1",
              "local_frame_id": "miss-img-001"},
        # No files= parameter
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_missing_captured_at_returns_422(client: AsyncClient):
    """Omitting required captured_at form field → 422 Unprocessable Entity."""
    sid = await _create_session(client)
    r = await client.post(
        f"/v1/sessions/{sid}/frames",
        files={"image": ("board.jpg", io.BytesIO(_TINY_JPEG), "image/jpeg")},
        data={"sequence_no": "1", "local_frame_id": "miss-ts-001"},
        # captured_at deliberately omitted
    )
    assert r.status_code == 422


# ── Response body structure ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_response_has_required_fields(client: AsyncClient):
    """Successful upload response contains frame_id, status, and message."""
    sid = await _create_session(client)
    r = await _upload(client, sid, "board.jpg", _TINY_JPEG, "image/jpeg", "resp-check-001")
    assert r.status_code == 202
    body = r.json()
    assert "frame_id" in body
    assert body["status"] == "queued"
    assert body["message"] == "Frame queued for processing"
    # frame_id should be a valid UUID string
    uuid_obj = None
    try:
        uuid_obj = __import__("uuid").UUID(body["frame_id"])
    except ValueError:
        pytest.fail(f"frame_id is not a valid UUID: {body['frame_id']}")
    assert uuid_obj is not None
