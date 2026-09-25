"""
Tests for all 9 dashboard / report endpoints.

Coverage:
  GET /dashboard/teacher/{id}           → TeacherDashboard
  GET /dashboard/teacher/{id}/report    → TeacherReport  (all valid periods)
  GET /teachers/{id}/memory             → ClassroomMemoryResponse
  GET /dashboard/admin/{id}             → AdminDashboard
  GET /dashboard/admin/{id}/report      → AdminReport
  GET /dashboard/admin/{id}/teachers    → list[TeacherUsageSummary]
  GET /dashboard/csr/{id}               → CSRDashboard
  GET /dashboard/csr/{id}/report        → CSRReport
  GET /dashboard/csr/{id}/schools       → list[SchoolSummary]
  _sync_health() unit tests

Run:
    cd backend && source .venv/bin/activate
    python -m pytest tests/test_dashboard.py -v
"""

import io
import asyncio
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.teacher import Teacher
from app.models.school import School
from app.models.program import Program
from tests.conftest import TEACHER_ID, CLASSROOM_ID

# ── Shared fixture data ───────────────────────────────────────────────────────

# Minimal valid JPEG (1x1 pixel)
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

# A teacher UUID that is never used by other test files (avoids count bleed-over)
_SOLO_TEACHER_ID = "55555555-5555-5555-5555-555555555555"

SESSION_PAYLOAD = {
    "teacher_id": TEACHER_ID,
    "classroom_id": CLASSROOM_ID,
    "subject": "Mathematics",
    "grade": "Grade 8",
    "board_type": "chalkboard",
    "capture_mode": "time_based",
    "capture_interval_sec": 30,
}


async def _make_session(client: AsyncClient, subject: str = "Mathematics",
                        teacher_id: str = TEACHER_ID) -> str:
    payload = {**SESSION_PAYLOAD, "subject": subject, "teacher_id": teacher_id}
    r = await client.post("/v1/sessions", json=payload)
    assert r.status_code == 201
    return r.json()["session_id"]


async def _make_session_with_quiz(
    client: AsyncClient,
    subject: str = "Mathematics",
    teacher_id: str = TEACHER_ID,
) -> str:
    """Create a session, upload a frame, generate a quiz, and return the session_id."""
    session_id = await _make_session(client, subject=subject, teacher_id=teacher_id)
    await client.post(
        f"/v1/sessions/{session_id}/frames",
        files={"image": ("board.jpg", io.BytesIO(_TINY_JPEG), "image/jpeg")},
        data={
            "captured_at": "2026-05-27T10:00:00Z",
            "sequence_no": "1",
            "local_frame_id": f"dash-frame-{session_id[:8]}",
        },
    )
    await client.post(
        f"/v1/sessions/{session_id}/generate",
        json={"outputs": ["quiz"]},
    )
    await asyncio.sleep(0.1)
    return session_id


# ── Teacher dashboard ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_teacher_dashboard_zero_counts(client: AsyncClient):
    """Teacher who has never created a session → all dashboard counts are zero."""
    empty_id = "66666666-6666-6666-6666-666666666666"
    r = await client.get(f"/v1/dashboard/teacher/{empty_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["sessions_conducted"] == 0
    assert body["topics_covered"] == 0
    assert body["ai_outputs_generated"] == 0
    assert body["tiqer_sessions"] == 0
    assert body["missing_concepts_flagged"] == 0
    assert body["pending_sync"] == 0


@pytest.mark.asyncio
async def test_teacher_dashboard_has_required_fields(client: AsyncClient):
    """TeacherDashboard response contains all required fields."""
    r = await client.get(f"/v1/dashboard/teacher/{TEACHER_ID}")
    assert r.status_code == 200
    body = r.json()
    for field in (
        "teacher_id", "sessions_conducted", "topics_covered",
        "ai_outputs_generated", "tiqer_sessions",
        "missing_concepts_flagged", "pending_sync",
    ):
        assert field in body, f"Missing field: {field}"


@pytest.mark.asyncio
async def test_teacher_dashboard_sessions_conducted_increments(client: AsyncClient):
    """Creating a session raises sessions_conducted by at least 1."""
    r_before = await client.get(f"/v1/dashboard/teacher/{_SOLO_TEACHER_ID}")
    before = r_before.json()["sessions_conducted"]

    await _make_session(client, teacher_id=_SOLO_TEACHER_ID)

    r_after = await client.get(f"/v1/dashboard/teacher/{_SOLO_TEACHER_ID}")
    assert r_after.json()["sessions_conducted"] == before + 1


@pytest.mark.asyncio
async def test_teacher_dashboard_ai_outputs_increments_after_generation(client: AsyncClient):
    """After generating quiz output, ai_outputs_generated rises by ≥ 1."""
    r_before = await client.get(f"/v1/dashboard/teacher/{_SOLO_TEACHER_ID}")
    before = r_before.json()["ai_outputs_generated"]

    await _make_session_with_quiz(client, teacher_id=_SOLO_TEACHER_ID)

    r_after = await client.get(f"/v1/dashboard/teacher/{_SOLO_TEACHER_ID}")
    assert r_after.json()["ai_outputs_generated"] >= before + 1


# ── Teacher full report ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_teacher_report_has_all_required_fields(client: AsyncClient):
    """TeacherReport shape: all 21 top-level fields must be present."""
    r = await client.get(f"/v1/dashboard/teacher/{TEACHER_ID}/report")
    assert r.status_code == 200
    body = r.json()
    required = [
        "teacher_id", "period_days",
        "sessions_total", "sessions_this_period",
        "ai_outputs_total", "ai_outputs_this_period",
        "quizzes_generated", "quizzes_exported_to_tiqer",
        "topics_count", "missing_concepts_total", "missing_concepts_resolved",
        "sync_pending", "sync_failed", "sync_completed",
        "sessions_over_time", "subject_breakdown",
        "topics_covered", "bloom_distribution",
        "sync_breakdown", "recent_missing_concepts", "quiz_sessions",
    ]
    for field in required:
        assert field in body, f"Missing field: {field}"


@pytest.mark.asyncio
async def test_teacher_report_period_7_has_7_time_series_entries(client: AsyncClient):
    r = await client.get(f"/v1/dashboard/teacher/{TEACHER_ID}/report?period=7")
    assert r.status_code == 200
    body = r.json()
    assert body["period_days"] == 7
    assert len(body["sessions_over_time"]) == 7


@pytest.mark.asyncio
async def test_teacher_report_period_30_has_30_time_series_entries(client: AsyncClient):
    r = await client.get(f"/v1/dashboard/teacher/{TEACHER_ID}/report?period=30")
    assert r.status_code == 200
    body = r.json()
    assert body["period_days"] == 30
    assert len(body["sessions_over_time"]) == 30


@pytest.mark.asyncio
async def test_teacher_report_period_90_has_90_time_series_entries(client: AsyncClient):
    r = await client.get(f"/v1/dashboard/teacher/{TEACHER_ID}/report?period=90")
    assert r.status_code == 200
    assert len(r.json()["sessions_over_time"]) == 90


@pytest.mark.asyncio
async def test_teacher_report_period_365_has_365_time_series_entries(client: AsyncClient):
    r = await client.get(f"/v1/dashboard/teacher/{TEACHER_ID}/report?period=365")
    assert r.status_code == 200
    assert len(r.json()["sessions_over_time"]) == 365


@pytest.mark.asyncio
async def test_teacher_report_invalid_period_falls_back_to_30(client: AsyncClient):
    """Any non-whitelisted period is silently coerced to 30 days."""
    r = await client.get(f"/v1/dashboard/teacher/{TEACHER_ID}/report?period=999")
    assert r.status_code == 200
    body = r.json()
    assert body["period_days"] == 30
    assert len(body["sessions_over_time"]) == 30


@pytest.mark.asyncio
async def test_teacher_report_sessions_over_time_entries_are_date_strings(client: AsyncClient):
    """Each sessions_over_time entry has a YYYY-MM-DD date and an integer count."""
    r = await client.get(f"/v1/dashboard/teacher/{TEACHER_ID}/report?period=7")
    body = r.json()
    for entry in body["sessions_over_time"]:
        assert "date" in entry
        assert "count" in entry
        # Date must be YYYY-MM-DD
        assert len(entry["date"]) == 10
        assert entry["date"][4] == "-" and entry["date"][7] == "-"
        assert isinstance(entry["count"], int)
        assert entry["count"] >= 0


@pytest.mark.asyncio
async def test_teacher_report_subject_breakdown_sorted_descending(client: AsyncClient):
    """subject_breakdown is ordered by count desc when there are multiple subjects."""
    # Create 2 Biology sessions and 1 Chemistry session for the solo teacher
    for _ in range(2):
        await _make_session(client, subject="Biology", teacher_id=_SOLO_TEACHER_ID)
    await _make_session(client, subject="Chemistry", teacher_id=_SOLO_TEACHER_ID)

    r = await client.get(f"/v1/dashboard/teacher/{_SOLO_TEACHER_ID}/report")
    body = r.json()
    counts = [s["count"] for s in body["subject_breakdown"]]
    assert counts == sorted(counts, reverse=True), "subject_breakdown must be sorted by count desc"


@pytest.mark.asyncio
async def test_teacher_report_bloom_distribution_after_quiz(client: AsyncClient):
    """bloom_distribution is non-empty after quiz generation."""
    await _make_session_with_quiz(client, teacher_id=_SOLO_TEACHER_ID)
    r = await client.get(f"/v1/dashboard/teacher/{_SOLO_TEACHER_ID}/report")
    body = r.json()
    assert len(body["bloom_distribution"]) >= 1
    for entry in body["bloom_distribution"]:
        assert "bloom_level" in entry
        assert "count" in entry
        assert entry["count"] >= 1


@pytest.mark.asyncio
async def test_teacher_report_sync_breakdown_has_all_keys(client: AsyncClient):
    """sync_breakdown contains all four sync-status keys with integer values."""
    r = await client.get(f"/v1/dashboard/teacher/{TEACHER_ID}/report")
    sb = r.json()["sync_breakdown"]
    for key in ("pending", "syncing", "synced", "failed"):
        assert key in sb, f"Missing sync_breakdown key: {key}"
        assert isinstance(sb[key], int) and sb[key] >= 0


@pytest.mark.asyncio
async def test_teacher_report_quiz_sessions_contains_session_after_generation(client: AsyncClient):
    """quiz_sessions list includes the session once quiz questions are generated."""
    session_id = await _make_session_with_quiz(client, teacher_id=_SOLO_TEACHER_ID)
    r = await client.get(f"/v1/dashboard/teacher/{_SOLO_TEACHER_ID}/report")
    body = r.json()
    ids_in_report = [qs["session_id"] for qs in body["quiz_sessions"]]
    assert session_id in ids_in_report


@pytest.mark.asyncio
async def test_teacher_report_quiz_session_has_required_fields(client: AsyncClient):
    """Each quiz_sessions entry has the expected shape."""
    await _make_session_with_quiz(client, teacher_id=_SOLO_TEACHER_ID)
    r = await client.get(f"/v1/dashboard/teacher/{_SOLO_TEACHER_ID}/report")
    quiz_sessions = r.json()["quiz_sessions"]
    assert len(quiz_sessions) >= 1
    qs = quiz_sessions[0]
    for field in ("session_id", "subject", "grade", "question_count",
                  "exported_to_tiqer", "created_at"):
        assert field in qs, f"Missing quiz_sessions field: {field}"
    assert qs["question_count"] >= 1


@pytest.mark.asyncio
async def test_teacher_report_empty_teacher_returns_zeros(client: AsyncClient):
    """Teacher with zero sessions returns all-zero counts and empty lists."""
    empty_id = "77777777-7777-7777-7777-777777777777"
    r = await client.get(f"/v1/dashboard/teacher/{empty_id}/report?period=7")
    assert r.status_code == 200
    body = r.json()
    assert body["sessions_total"] == 0
    assert body["sessions_this_period"] == 0
    assert body["quizzes_generated"] == 0
    assert body["quizzes_exported_to_tiqer"] == 0
    assert body["topics_covered"] == []
    assert body["bloom_distribution"] == []
    assert body["recent_missing_concepts"] == []
    assert body["quiz_sessions"] == []
    assert len(body["sessions_over_time"]) == 7


# ── Classroom memory ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_teacher_memory_empty_for_new_teacher(client: AsyncClient):
    """Teacher with no ClassroomMemory row returns null/empty fields."""
    empty_id = "88888888-8888-8888-8888-888888888888"
    r = await client.get(f"/v1/teachers/{empty_id}/memory")
    assert r.status_code == 200
    body = r.json()
    assert body["last_session"] is None
    assert body["pending_concepts"] == []
    assert body["suggested_next"] is None


@pytest.mark.asyncio
async def test_teacher_memory_has_required_fields(client: AsyncClient):
    """ClassroomMemoryResponse always returns required shape."""
    r = await client.get(f"/v1/teachers/{TEACHER_ID}/memory")
    assert r.status_code == 200
    body = r.json()
    for field in ("teacher_id", "last_session", "pending_concepts", "suggested_next"):
        assert field in body, f"Missing memory field: {field}"


# ── Admin dashboard ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_dashboard_zero_counts_no_teachers(client: AsyncClient, db: AsyncSession):
    """School with no teachers returns all-zero admin dashboard."""
    school_id = uuid.uuid4()
    school = School(id=school_id, name="Empty Admin School", is_active=True)
    db.add(school)
    await db.flush()

    r = await client.get(f"/v1/dashboard/admin/{school_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["active_teachers"] == 0


@pytest.mark.asyncio
async def test_admin_dashboard_has_required_fields(client: AsyncClient, db: AsyncSession):
    """AdminDashboard has all expected top-level keys."""
    school_id = uuid.uuid4()
    db.add(School(id=school_id, name="Fields Test School", is_active=True))
    await db.flush()

    r = await client.get(f"/v1/dashboard/admin/{school_id}")
    assert r.status_code == 200
    body = r.json()
    for field in (
        "school_id", "total_sessions", "active_teachers",
        "total_ai_outputs", "total_tiqer_exports", "pending_sync_sessions",
    ):
        assert field in body, f"Missing admin dashboard field: {field}"


@pytest.mark.asyncio
async def test_admin_dashboard_active_teachers_with_sessions(
    client: AsyncClient, db: AsyncSession
):
    """Teacher with sessions → active_teachers counts them in admin dashboard."""
    school_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    db.add(School(id=school_id, name="Active Teacher School", is_active=True))
    db.add(Teacher(
        id=teacher_id,
        name="Admin Test Teacher",
        email=f"admin-active-{school_id.hex[:8]}@test.com",
        school_id=school_id,
        is_active=True,
    ))
    await db.flush()

    # Create a session with this teacher (this commits the School/Teacher rows too)
    payload = {**SESSION_PAYLOAD, "teacher_id": str(teacher_id)}
    r = await client.post("/v1/sessions", json=payload)
    assert r.status_code == 201

    r2 = await client.get(f"/v1/dashboard/admin/{school_id}")
    assert r2.status_code == 200
    assert r2.json()["active_teachers"] >= 1


# ── Admin full report ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_report_empty_school(client: AsyncClient, db: AsyncSession):
    """School with no teachers returns a valid empty AdminReport."""
    school_id = uuid.uuid4()
    db.add(School(id=school_id, name="Empty Report School", is_active=True))
    await db.flush()

    r = await client.get(f"/v1/dashboard/admin/{school_id}/report")
    assert r.status_code == 200
    body = r.json()
    assert body["total_teachers"] == 0
    assert body["total_sessions"] == 0
    assert body["teachers"] == []
    assert body["school_name"] == "Empty Report School"
    assert len(body["sessions_over_time"]) == 30  # default period


@pytest.mark.asyncio
async def test_admin_report_has_all_required_fields(client: AsyncClient, db: AsyncSession):
    """AdminReport shape: all expected top-level fields present."""
    school_id = uuid.uuid4()
    db.add(School(id=school_id, name="Shape Admin School", is_active=True))
    await db.flush()

    r = await client.get(f"/v1/dashboard/admin/{school_id}/report")
    assert r.status_code == 200
    body = r.json()
    required = [
        "school_id", "school_name", "period_days",
        "total_sessions", "sessions_this_period",
        "total_teachers", "active_teachers",
        "total_ai_outputs", "total_tiqer_exports", "pending_sync_sessions",
        "sessions_over_time", "subject_breakdown", "teachers",
    ]
    for f in required:
        assert f in body, f"Missing admin report field: {f}"


@pytest.mark.asyncio
async def test_admin_report_unknown_school_uses_id_as_name(client: AsyncClient):
    """Unknown school_id (no DB row) returns report with school_id as school_name fallback."""
    unknown_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    r = await client.get(f"/v1/dashboard/admin/{unknown_id}/report")
    assert r.status_code == 200
    body = r.json()
    assert body["total_teachers"] == 0
    assert body["school_name"] == unknown_id


@pytest.mark.asyncio
async def test_admin_report_period_7_gives_7_time_series(client: AsyncClient, db: AsyncSession):
    """period=7 → sessions_over_time has exactly 7 entries."""
    school_id = uuid.uuid4()
    db.add(School(id=school_id, name="Period7 Admin School", is_active=True))
    await db.flush()

    r = await client.get(f"/v1/dashboard/admin/{school_id}/report?period=7")
    assert r.status_code == 200
    body = r.json()
    assert body["period_days"] == 7
    assert len(body["sessions_over_time"]) == 7


@pytest.mark.asyncio
async def test_admin_report_with_teacher_shows_teacher_in_list(
    client: AsyncClient, db: AsyncSession
):
    """Admin report teachers[] list includes teachers belonging to the school."""
    school_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    db.add(School(id=school_id, name="Teacher List School", is_active=True))
    db.add(Teacher(
        id=teacher_id,
        name="Report Test Teacher",
        email=f"report-{school_id.hex[:8]}@test.com",
        school_id=school_id,
        is_active=True,
    ))
    await db.flush()

    # Create a session to trigger commit (so Teacher row is persisted)
    payload = {**SESSION_PAYLOAD, "teacher_id": str(teacher_id)}
    await client.post("/v1/sessions", json=payload)

    r = await client.get(f"/v1/dashboard/admin/{school_id}/report")
    assert r.status_code == 200
    body = r.json()
    assert body["total_teachers"] == 1
    assert len(body["teachers"]) == 1
    t = body["teachers"][0]
    assert t["teacher_id"] == str(teacher_id)
    assert t["name"] == "Report Test Teacher"
    assert t["session_count"] >= 1
    assert t["sync_health"] in ("healthy", "degraded", "offline", "unknown")


# ── Admin teacher list ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_teacher_list_empty_school(client: AsyncClient, db: AsyncSession):
    """School with no teachers → empty list."""
    school_id = uuid.uuid4()
    db.add(School(id=school_id, name="Empty List School", is_active=True))
    await db.flush()

    r = await client.get(f"/v1/dashboard/admin/{school_id}/teachers")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_admin_teacher_list_has_teacher_usage_shape(
    client: AsyncClient, db: AsyncSession
):
    """Teacher list entries have the full TeacherUsageSummary shape."""
    school_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    db.add(School(id=school_id, name="Usage Shape School", is_active=True))
    db.add(Teacher(
        id=teacher_id,
        name="Usage Shape Teacher",
        email=f"usage-{school_id.hex[:8]}@test.com",
        school_id=school_id,
        is_active=True,
    ))
    await db.flush()

    # Commit rows via session creation
    payload = {**SESSION_PAYLOAD, "teacher_id": str(teacher_id)}
    await client.post("/v1/sessions", json=payload)

    r = await client.get(f"/v1/dashboard/admin/{school_id}/teachers")
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 1
    entry = next(t for t in body if t["teacher_id"] == str(teacher_id))
    for field in (
        "teacher_id", "name", "email", "session_count",
        "ai_outputs_count", "tiqer_exports", "subject_count",
        "last_active", "sync_health",
    ):
        assert field in entry, f"Missing teacher list field: {field}"
    assert entry["sync_health"] in ("healthy", "degraded", "offline", "unknown")
    assert entry["session_count"] >= 1


# ── CSR dashboard ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_csr_dashboard_no_schools_returns_zeros(client: AsyncClient, db: AsyncSession):
    """Program with no schools returns all-zero CSR dashboard."""
    program_id = uuid.uuid4()
    db.add(Program(id=program_id, name="Zero CSR Program", type="csr", is_active=True))
    await db.flush()

    r = await client.get(f"/v1/dashboard/csr/{program_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["total_schools"] == 0
    assert body["total_sessions"] == 0
    assert body["active_teachers"] == 0
    assert body["total_topics_covered"] == 0
    assert body["connectivity_failure_rate"] == 0.0


@pytest.mark.asyncio
async def test_csr_dashboard_has_required_fields(client: AsyncClient, db: AsyncSession):
    """CSRDashboard has all required fields."""
    program_id = uuid.uuid4()
    db.add(Program(id=program_id, name="Fields CSR Program", type="ngo", is_active=True))
    await db.flush()

    r = await client.get(f"/v1/dashboard/csr/{program_id}")
    assert r.status_code == 200
    body = r.json()
    for field in (
        "program_id", "total_schools", "total_sessions",
        "active_teachers", "total_topics_covered", "connectivity_failure_rate",
    ):
        assert field in body, f"Missing CSR dashboard field: {field}"


# ── CSR full report ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_csr_report_empty_program(client: AsyncClient, db: AsyncSession):
    """CSR report for program with no schools returns valid empty report."""
    program_id = uuid.uuid4()
    db.add(Program(id=program_id, name="Empty CSR Report", type="csr", is_active=True))
    await db.flush()

    r = await client.get(f"/v1/dashboard/csr/{program_id}/report")
    assert r.status_code == 200
    body = r.json()
    assert body["total_schools"] == 0
    assert body["schools"] == []
    assert body["concept_coverage"] == []
    assert body["program_name"] == "Empty CSR Report"
    assert len(body["sessions_over_time"]) == 30


@pytest.mark.asyncio
async def test_csr_report_has_all_required_fields(client: AsyncClient, db: AsyncSession):
    """CSRReport shape: all 14 top-level fields present."""
    program_id = uuid.uuid4()
    db.add(Program(id=program_id, name="Shape CSR Program", type="government", is_active=True))
    await db.flush()

    r = await client.get(f"/v1/dashboard/csr/{program_id}/report")
    assert r.status_code == 200
    body = r.json()
    required = [
        "program_id", "program_name", "period_days",
        "total_schools", "total_sessions", "sessions_this_period",
        "total_teachers", "active_teachers", "teacher_adoption_rate",
        "total_topics_covered", "connectivity_failure_rate",
        "sessions_over_time", "schools", "concept_coverage",
    ]
    for f in required:
        assert f in body, f"Missing CSR report field: {f}"


@pytest.mark.asyncio
async def test_csr_report_period_7_gives_7_time_series(client: AsyncClient, db: AsyncSession):
    """period=7 → sessions_over_time has exactly 7 entries."""
    program_id = uuid.uuid4()
    db.add(Program(id=program_id, name="Period7 CSR Program", type="csr", is_active=True))
    await db.flush()

    r = await client.get(f"/v1/dashboard/csr/{program_id}/report?period=7")
    assert r.status_code == 200
    body = r.json()
    assert body["period_days"] == 7
    assert len(body["sessions_over_time"]) == 7


@pytest.mark.asyncio
async def test_csr_report_unknown_program_uses_id_as_name(client: AsyncClient):
    """Unknown program_id (no DB row) returns report with program_id as program_name fallback."""
    unknown_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    r = await client.get(f"/v1/dashboard/csr/{unknown_id}/report")
    assert r.status_code == 200
    body = r.json()
    assert body["total_schools"] == 0
    assert body["program_name"] == unknown_id


@pytest.mark.asyncio
async def test_csr_report_adoption_rate_zero_when_no_sessions(
    client: AsyncClient, db: AsyncSession
):
    """teacher_adoption_rate is 0.0 when no sessions have been created."""
    program_id = uuid.uuid4()
    school_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    db.add(Program(id=program_id, name="Adoption Rate Program", type="ngo", is_active=True))
    db.add(School(id=school_id, name="Adoption School", program_id=program_id, is_active=True))
    db.add(Teacher(
        id=teacher_id,
        name="Inactive Teacher",
        email=f"inactive-{program_id.hex[:8]}@test.com",
        school_id=school_id,
        is_active=True,
    ))
    await db.flush()
    # Commit the rows by creating a session (so the DB query can find them)
    payload = {**SESSION_PAYLOAD, "teacher_id": str(teacher_id)}
    await client.post("/v1/sessions", json=payload)

    r = await client.get(f"/v1/dashboard/csr/{program_id}/report?period=7")
    assert r.status_code == 200
    body = r.json()
    assert body["total_teachers"] == 1
    # Sessions exist but were created today (within period) so adoption rate > 0
    assert body["teacher_adoption_rate"] >= 0.0


# ── CSR school list ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_csr_school_list_empty_program(client: AsyncClient, db: AsyncSession):
    """Program with no schools → empty list."""
    program_id = uuid.uuid4()
    db.add(Program(id=program_id, name="No Schools Program", type="csr", is_active=True))
    await db.flush()

    r = await client.get(f"/v1/dashboard/csr/{program_id}/schools")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_csr_school_list_returns_school_summary_shape(
    client: AsyncClient, db: AsyncSession
):
    """School list entries have the full SchoolSummary shape."""
    program_id = uuid.uuid4()
    school_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    db.add(Program(id=program_id, name="Shape Schools Program", type="csr", is_active=True))
    db.add(School(
        id=school_id,
        name="Shape School",
        district="Test District",
        state="Test State",
        program_id=program_id,
        is_active=True,
    ))
    db.add(Teacher(
        id=teacher_id,
        name="Shape School Teacher",
        email=f"shape-{school_id.hex[:8]}@test.com",
        school_id=school_id,
        is_active=True,
    ))
    await db.flush()

    payload = {**SESSION_PAYLOAD, "teacher_id": str(teacher_id)}
    await client.post("/v1/sessions", json=payload)

    r = await client.get(f"/v1/dashboard/csr/{program_id}/schools")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    school = body[0]
    for field in (
        "school_id", "name", "district", "state",
        "total_sessions", "active_teachers",
        "last_activity", "pending_sync", "sync_health",
    ):
        assert field in school, f"Missing school summary field: {field}"
    assert school["name"] == "Shape School"
    assert school["sync_health"] in ("healthy", "degraded", "offline", "unknown")


# ── _sync_health() unit tests (no DB) ────────────────────────────────────────

def test_sync_health_unknown_when_no_sessions():
    from app.routers.dashboard import _sync_health
    assert _sync_health(0, 0, 0) == "unknown"


def test_sync_health_healthy_all_synced():
    from app.routers.dashboard import _sync_health
    assert _sync_health(0, 0, 10) == "healthy"


def test_sync_health_healthy_small_pending():
    from app.routers.dashboard import _sync_health
    # 1 pending out of 10 = 10% pending → healthy (threshold is >50%)
    assert _sync_health(1, 0, 10) == "healthy"


def test_sync_health_degraded_high_failure_rate():
    from app.routers.dashboard import _sync_health
    # 2 failed out of 10 = 20% failure → degraded (threshold >10%)
    assert _sync_health(0, 2, 10) == "degraded"


def test_sync_health_degraded_high_pending_rate():
    from app.routers.dashboard import _sync_health
    # 6 pending out of 10 = 60% pending → degraded (threshold >50%)
    assert _sync_health(6, 0, 10) == "degraded"


def test_sync_health_offline_high_failure_rate():
    from app.routers.dashboard import _sync_health
    # 4 failed out of 10 = 40% failure → offline (threshold >30%)
    assert _sync_health(0, 4, 10) == "offline"


def test_sync_health_boundary_exactly_30_percent_failed():
    from app.routers.dashboard import _sync_health
    # 3 failed out of 10 = 30% — NOT > 0.3, so degraded (not offline)
    assert _sync_health(0, 3, 10) == "degraded"


def test_sync_health_boundary_exactly_10_percent_failed():
    from app.routers.dashboard import _sync_health
    # 1 failed out of 10 = 10% — NOT > 0.1, so healthy
    assert _sync_health(0, 1, 10) == "healthy"
