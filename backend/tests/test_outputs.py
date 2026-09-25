import io
import asyncio
import pytest
from httpx import AsyncClient
from tests.conftest import TEACHER_ID, CLASSROOM_ID

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

SESSION_PAYLOAD = {
    "teacher_id": TEACHER_ID,
    "classroom_id": CLASSROOM_ID,
    "subject": "Physics",
    "grade": "Grade 9",
    "board_type": "chalkboard",
    "capture_mode": "time_based",
    "capture_interval_sec": 30,
}


async def _create_session_with_frame(client: AsyncClient) -> tuple[str, str]:
    r = await client.post("/v1/sessions", json=SESSION_PAYLOAD)
    session_id = r.json()["session_id"]
    fr = await client.post(
        f"/v1/sessions/{session_id}/frames",
        files={"image": ("board.jpg", io.BytesIO(_TINY_JPEG), "image/jpeg")},
        data={"captured_at": "2026-05-27T10:00:00Z", "sequence_no": "1", "local_frame_id": f"frame-{session_id[:8]}"},
    )
    frame_id = fr.json()["frame_id"]
    return session_id, frame_id


@pytest.mark.asyncio
async def test_trigger_generation(client: AsyncClient):
    session_id, _ = await _create_session_with_frame(client)

    r = await client.post(
        f"/v1/sessions/{session_id}/generate",
        json={"outputs": ["notes", "summary", "quiz"]},
    )
    assert r.status_code == 202
    body = r.json()
    assert "job_id" in body
    assert body["status"] == "queued"
    assert body["estimated_sec"] == 90


@pytest.mark.asyncio
async def test_get_job_status(client: AsyncClient):
    session_id, _ = await _create_session_with_frame(client)

    gen = await client.post(
        f"/v1/sessions/{session_id}/generate",
        json={"outputs": ["notes", "summary"]},
    )
    job_id = gen.json()["job_id"]

    # Background task needs a tick to complete
    await asyncio.sleep(0.1)

    r = await client.get(f"/v1/jobs/{job_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == job_id
    assert body["type"] == "ai_generation"
    assert body["status"] == "completed"
    assert body["progress"] == 100
    assert body["error"] is None


@pytest.mark.asyncio
async def test_get_session_outputs(client: AsyncClient):
    session_id, _ = await _create_session_with_frame(client)

    await client.post(
        f"/v1/sessions/{session_id}/generate",
        json={"outputs": ["notes", "summary", "missing_concepts"]},
    )
    await asyncio.sleep(0.1)

    r = await client.get(f"/v1/sessions/{session_id}/outputs")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == session_id
    outputs = body["outputs"]
    assert "notes" in outputs
    assert "summary" in outputs
    assert outputs["notes"]["status"] == "ready"
    assert outputs["summary"]["status"] == "ready"


@pytest.mark.asyncio
async def test_get_quiz_questions(client: AsyncClient):
    session_id, _ = await _create_session_with_frame(client)

    await client.post(
        f"/v1/sessions/{session_id}/generate",
        json={"outputs": ["quiz"]},
    )
    await asyncio.sleep(0.1)

    r = await client.get(f"/v1/sessions/{session_id}/outputs/quiz")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == session_id
    questions = body["questions"]
    assert len(questions) >= 1
    for q in questions:
        assert "id" in q
        assert q["type"] in ("mcq", "true_false", "poll")
        assert "text" in q
        assert "bloom_level" in q


@pytest.mark.asyncio
async def test_export_tiqer(client: AsyncClient):
    session_id, _ = await _create_session_with_frame(client)

    await client.post(f"/v1/sessions/{session_id}/generate", json={"outputs": ["quiz"]})
    await asyncio.sleep(0.1)

    r = await client.post(
        f"/v1/sessions/{session_id}/outputs/quiz/export-tiqer",
        json={"tiqer_class_id": "class-abc-123"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "exported"
    assert "tiqer_session_id" in body


@pytest.mark.asyncio
async def test_get_outputs_empty_before_generation(client: AsyncClient):
    session_id, _ = await _create_session_with_frame(client)

    r = await client.get(f"/v1/sessions/{session_id}/outputs")
    assert r.status_code == 200
    assert r.json()["outputs"] == {}


@pytest.mark.asyncio
async def test_quiz_not_ready_without_generation(client: AsyncClient):
    session_id, _ = await _create_session_with_frame(client)

    r = await client.get(f"/v1/sessions/{session_id}/outputs/quiz")
    assert r.status_code == 404
    assert r.json()["error"] == "QUIZ_NOT_READY"


@pytest.mark.asyncio
async def test_job_not_found(client: AsyncClient):
    r = await client.get("/v1/jobs/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
    assert r.json()["error"] == "JOB_NOT_FOUND"


@pytest.mark.asyncio
async def test_generate_session_not_found(client: AsyncClient):
    r = await client.post(
        "/v1/sessions/00000000-0000-0000-0000-000000000000/generate",
        json={"outputs": ["notes"]},
    )
    assert r.status_code == 404
    assert r.json()["error"] == "SESSION_NOT_FOUND"


# ── Extended TiQer tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_export_tiqer_marks_questions_as_exported(client: AsyncClient, db):
    """After export-tiqer, all quiz questions for the session have tiqer_exported=True."""
    import uuid as _uuid
    from sqlalchemy import select as sa_select
    from app.models.quiz_question import QuizQuestion

    session_id, _ = await _create_session_with_frame(client)
    await client.post(f"/v1/sessions/{session_id}/generate", json={"outputs": ["quiz"]})
    await asyncio.sleep(0.1)

    r = await client.post(
        f"/v1/sessions/{session_id}/outputs/quiz/export-tiqer",
        json={"tiqer_class_id": "cls-export-mark-001"},
    )
    assert r.status_code == 200

    # Verify DB flag — session_id must be a UUID object for the Uuid column type
    rows = (
        await db.execute(
            sa_select(QuizQuestion).where(
                QuizQuestion.session_id == _uuid.UUID(session_id)
            )
        )
    ).scalars().all()
    assert len(rows) >= 1
    assert all(q.tiqer_exported for q in rows), (
        "All quiz questions should have tiqer_exported=True after export"
    )


@pytest.mark.asyncio
async def test_export_tiqer_creates_audit_log(client: AsyncClient, db):
    """export-tiqer writes exactly one TiQerExportLog row for the session."""
    import uuid as _uuid
    from sqlalchemy import select as sa_select
    from app.models.tiqer_export_log import TiQerExportLog

    session_id, _ = await _create_session_with_frame(client)
    await client.post(f"/v1/sessions/{session_id}/generate", json={"outputs": ["quiz"]})
    await asyncio.sleep(0.1)

    tiqer_class_id = "cls-audit-log-001"
    r = await client.post(
        f"/v1/sessions/{session_id}/outputs/quiz/export-tiqer",
        json={"tiqer_class_id": tiqer_class_id},
    )
    assert r.status_code == 200

    logs = (
        await db.execute(
            sa_select(TiQerExportLog).where(
                TiQerExportLog.session_id == _uuid.UUID(session_id)
            )
        )
    ).scalars().all()
    assert len(logs) == 1
    log = logs[0]
    assert log.tiqer_class_id == tiqer_class_id
    assert log.question_count >= 1
    assert log.tiqer_session_id  # non-empty


@pytest.mark.asyncio
async def test_export_tiqer_response_shape(client: AsyncClient):
    """export-tiqer response has the expected top-level fields."""
    session_id, _ = await _create_session_with_frame(client)
    await client.post(f"/v1/sessions/{session_id}/generate", json={"outputs": ["quiz"]})
    await asyncio.sleep(0.1)

    r = await client.post(
        f"/v1/sessions/{session_id}/outputs/quiz/export-tiqer",
        json={"tiqer_class_id": "cls-shape-001"},
    )
    assert r.status_code == 200
    body = r.json()
    for field in ("tiqer_session_id", "status", "question_count", "exported_at", "payload"):
        assert field in body, f"Missing export response field: {field}"
    assert body["status"] == "exported"
    assert body["question_count"] >= 1


@pytest.mark.asyncio
async def test_export_tiqer_payload_schema(client: AsyncClient):
    """The payload inside the export response follows the TiQer schema v1.0."""
    session_id, _ = await _create_session_with_frame(client)
    await client.post(f"/v1/sessions/{session_id}/generate", json={"outputs": ["quiz"]})
    await asyncio.sleep(0.1)

    r = await client.post(
        f"/v1/sessions/{session_id}/outputs/quiz/export-tiqer",
        json={"tiqer_class_id": "cls-schema-001"},
    )
    assert r.status_code == 200
    payload = r.json()["payload"]
    for field in ("export_id", "schema_version", "tiqer_class_id", "session_id",
                  "exported_at", "teacher_id", "question_count", "questions", "metadata"):
        assert field in payload, f"Missing payload field: {field}"
    assert payload["schema_version"] == "1.0"
    assert payload["tiqer_class_id"] == "cls-schema-001"
    assert len(payload["questions"]) >= 1


@pytest.mark.asyncio
async def test_export_tiqer_payload_question_shape(client: AsyncClient):
    """Each question in the TiQer payload has the full question schema."""
    session_id, _ = await _create_session_with_frame(client)
    await client.post(f"/v1/sessions/{session_id}/generate", json={"outputs": ["quiz"]})
    await asyncio.sleep(0.1)

    r = await client.post(
        f"/v1/sessions/{session_id}/outputs/quiz/export-tiqer",
        json={"tiqer_class_id": "cls-q-shape-001"},
    )
    assert r.status_code == 200
    questions = r.json()["payload"]["questions"]
    assert len(questions) >= 1
    q = questions[0]
    for field in ("question_id", "sequence", "type", "text", "correct_answer",
                  "bloom_level", "skill_tag", "topic", "grade", "subject", "difficulty"):
        assert field in q, f"Missing question field: {field}"
    assert q["type"] in ("mcq", "true_false")
    assert q["difficulty"] in ("easy", "medium", "hard")


@pytest.mark.asyncio
async def test_export_tiqer_re_export_is_idempotent(client: AsyncClient):
    """Re-exporting the same session returns 200 (not an error)."""
    session_id, _ = await _create_session_with_frame(client)
    await client.post(f"/v1/sessions/{session_id}/generate", json={"outputs": ["quiz"]})
    await asyncio.sleep(0.1)

    payload = {"tiqer_class_id": "cls-reexport-001"}
    r1 = await client.post(
        f"/v1/sessions/{session_id}/outputs/quiz/export-tiqer", json=payload
    )
    assert r1.status_code == 200

    r2 = await client.post(
        f"/v1/sessions/{session_id}/outputs/quiz/export-tiqer", json=payload
    )
    assert r2.status_code == 200, "Re-export of the same session should succeed (200)"


@pytest.mark.asyncio
async def test_export_tiqer_without_quiz_returns_404(client: AsyncClient):
    """Attempting to export before quiz generation → 404 QUIZ_NOT_READY."""
    session_id, _ = await _create_session_with_frame(client)
    # No generate call → no quiz questions

    r = await client.post(
        f"/v1/sessions/{session_id}/outputs/quiz/export-tiqer",
        json={"tiqer_class_id": "cls-empty-001"},
    )
    assert r.status_code == 404
    assert r.json()["error"] == "QUIZ_NOT_READY"


@pytest.mark.asyncio
async def test_tiqer_preview_returns_valid_json_payload(client: AsyncClient):
    """GET tiqer-preview returns a JSON payload without creating an audit log."""
    session_id, _ = await _create_session_with_frame(client)
    await client.post(f"/v1/sessions/{session_id}/generate", json={"outputs": ["quiz"]})
    await asyncio.sleep(0.1)

    r = await client.get(
        f"/v1/sessions/{session_id}/outputs/quiz/tiqer-preview"
        f"?tiqer_class_id=PREVIEW"
    )
    assert r.status_code == 200
    body = r.json()
    # Preview should return the full TiQer payload
    for field in ("export_id", "schema_version", "questions"):
        assert field in body, f"Missing preview payload field: {field}"
    assert body["tiqer_class_id"] == "PREVIEW"
    assert len(body["questions"]) >= 1


@pytest.mark.asyncio
async def test_tiqer_preview_with_custom_class_id(client: AsyncClient):
    """GET tiqer-preview?tiqer_class_id=CLS-123 pre-fills class ID in the payload."""
    session_id, _ = await _create_session_with_frame(client)
    await client.post(f"/v1/sessions/{session_id}/generate", json={"outputs": ["quiz"]})
    await asyncio.sleep(0.1)

    class_id = "CLS-CUSTOM-XYZ"
    r = await client.get(
        f"/v1/sessions/{session_id}/outputs/quiz/tiqer-preview"
        f"?tiqer_class_id={class_id}"
    )
    assert r.status_code == 200
    assert r.json()["tiqer_class_id"] == class_id


@pytest.mark.asyncio
async def test_tiqer_preview_download_returns_attachment_header(client: AsyncClient):
    """GET tiqer-preview?download=true sets Content-Disposition: attachment."""
    session_id, _ = await _create_session_with_frame(client)
    await client.post(f"/v1/sessions/{session_id}/generate", json={"outputs": ["quiz"]})
    await asyncio.sleep(0.1)

    r = await client.get(
        f"/v1/sessions/{session_id}/outputs/quiz/tiqer-preview?download=true"
    )
    assert r.status_code == 200
    disposition = r.headers.get("content-disposition", "")
    assert "attachment" in disposition, (
        f"Expected Content-Disposition: attachment, got: {disposition!r}"
    )


@pytest.mark.asyncio
async def test_tiqer_preview_without_quiz_returns_404(client: AsyncClient):
    """Preview before quiz generation → 404 QUIZ_NOT_READY."""
    session_id, _ = await _create_session_with_frame(client)
    # No generate → no quiz questions

    r = await client.get(
        f"/v1/sessions/{session_id}/outputs/quiz/tiqer-preview"
    )
    assert r.status_code == 404
    assert r.json()["error"] == "QUIZ_NOT_READY"


@pytest.mark.asyncio
async def test_tiqer_preview_does_not_create_audit_log(client: AsyncClient, db):
    """GET tiqer-preview should NOT write a TiQerExportLog row."""
    import uuid as _uuid
    from sqlalchemy import select as sa_select
    from app.models.tiqer_export_log import TiQerExportLog

    session_id, _ = await _create_session_with_frame(client)
    await client.post(f"/v1/sessions/{session_id}/generate", json={"outputs": ["quiz"]})
    await asyncio.sleep(0.1)

    await client.get(
        f"/v1/sessions/{session_id}/outputs/quiz/tiqer-preview?tiqer_class_id=PREVIEW"
    )

    logs = (
        await db.execute(
            sa_select(TiQerExportLog).where(
                TiQerExportLog.session_id == _uuid.UUID(session_id)
            )
        )
    ).scalars().all()
    assert len(logs) == 0, "tiqer-preview must not create audit log rows"


@pytest.mark.asyncio
async def test_export_tiqer_session_not_found(client: AsyncClient):
    """export-tiqer on a non-existent session → 404 SESSION_NOT_FOUND."""
    r = await client.post(
        "/v1/sessions/00000000-0000-0000-0000-000000000000/outputs/quiz/export-tiqer",
        json={"tiqer_class_id": "cls-gone-001"},
    )
    assert r.status_code == 404
    assert r.json()["error"] == "SESSION_NOT_FOUND"
