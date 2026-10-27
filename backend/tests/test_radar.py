"""
Tests for the Class Misconception Radar (app/services/radar_service.py).

Pure clustering rules (no DB):
  - a planted cluster (>=3 desks AND >=40% of attempting desks) qualifies
  - below the desk floor, or below the share floor, does not
  - a desk's repeated attempts count once, and only its LATEST attempt counts
    (a desk that recovered is not stuck)
  - desks stuck with no library code go to "unclassified", never an alert
  - attempts outside the recency window and non-complete attempts are ignored

Alert reconciliation + API (DB-backed; scoped to a fresh session each time
because the test DB persists across tests):
  - evaluate twice -> still one row (dedupe)
  - dismissed stays dismissed until the cluster grows by REOPEN_GROWTH
  - false_alarm stays suppressed
  - a cluster that stops qualifying resolves
  - GET /practice/radar returns the hydrated alert; PATCH dismisses it
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.misconception import Misconception
from app.models.practice_attempt import PracticeAttempt
from app.models.practice_question import PracticeQuestion
from app.models.practice_radar_alert import PracticeRadarAlert
from app.models.practice_station import PracticeStation
from app.models.session import Session
from app.services import radar_service
from tests.conftest import CLASSROOM_ID, TEACHER_ID

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def _att(qid, sid, status="conceptual_misconception", code="M-NUM-01", minutes_ago=5,
         attempt_no=1, row_status="complete"):
    return PracticeAttempt(
        question_id=qid, session_id=uuid.uuid4(), station_id=sid, attempt_no=attempt_no,
        status=row_status, validation_status=status, misconception_code=code,
        created_at=NOW - timedelta(minutes=minutes_ago),
    )


# ─── pure clustering ────────────────────────────────────────────────────────


def test_planted_cluster_qualifies():
    q = uuid.uuid4()
    desks = [uuid.uuid4() for _ in range(6)]
    attempts = [_att(q, d) for d in desks[:3]] + [_att(q, d, status="valid_progress", code=None) for d in desks[3:]]
    r = radar_service.find_clusters(attempts, now=NOW)
    assert len(r.clusters) == 1
    c = r.clusters[0]
    assert c.code == "M-NUM-01" and len(c.station_ids) == 3 and c.attempting_count == 6


def test_below_desk_floor_does_not_qualify():
    q = uuid.uuid4()
    attempts = [_att(q, uuid.uuid4()) for _ in range(2)]
    assert radar_service.find_clusters(attempts, now=NOW).clusters == []


def test_below_share_floor_does_not_qualify():
    q = uuid.uuid4()
    stuck = [_att(q, uuid.uuid4()) for _ in range(3)]
    fine = [_att(q, uuid.uuid4(), status="valid_progress", code=None) for _ in range(8)]
    # 3 of 11 = 27% < 40%
    assert radar_service.find_clusters(stuck + fine, now=NOW).clusters == []


def test_repeat_attempts_count_once_and_latest_wins():
    q = uuid.uuid4()
    a, b, c = (uuid.uuid4() for _ in range(3))
    attempts = [
        _att(q, a, minutes_ago=30, attempt_no=1), _att(q, a, minutes_ago=20, attempt_no=2),
        _att(q, a, minutes_ago=10, attempt_no=3),
        _att(q, b), _att(q, c, minutes_ago=30),
        # c has since recovered
        _att(q, c, status="valid_progress", code=None, minutes_ago=2, attempt_no=2),
    ]
    assert radar_service.find_clusters(attempts, now=NOW).clusters == []


def test_unclassified_is_reported_but_never_clusters():
    q = uuid.uuid4()
    attempts = [_att(q, uuid.uuid4(), status="arithmetic_slip", code=None) for _ in range(4)]
    r = radar_service.find_clusters(attempts, now=NOW)
    assert r.clusters == [] and len(r.unclassified[q]) == 4


def test_stale_and_incomplete_attempts_are_ignored():
    q = uuid.uuid4()
    attempts = [
        _att(q, uuid.uuid4(), minutes_ago=radar_service.WINDOW_MINUTES + 10),
        _att(q, uuid.uuid4(), row_status="processing"),
        _att(q, uuid.uuid4()),
    ]
    assert radar_service.find_clusters(attempts, now=NOW).clusters == []


def test_different_codes_do_not_merge():
    q = uuid.uuid4()
    attempts = [_att(q, uuid.uuid4(), code="A"), _att(q, uuid.uuid4(), code="B"), _att(q, uuid.uuid4(), code="A")]
    assert radar_service.find_clusters(attempts, now=NOW).clusters == []


# ─── DB-backed reconciliation ───────────────────────────────────────────────


async def _class(db: AsyncSession, n_desks: int):
    session = Session(
        teacher_id=uuid.UUID(TEACHER_ID), classroom_id=uuid.UUID(CLASSROOM_ID),
        subject="Math", grade="Grade 5", board_type="chalkboard",
        capture_mode="time_based", capture_interval_sec=30, status="active",
    )
    db.add(session)
    await db.flush()
    q = PracticeQuestion(session_id=session.id, text="Which is larger, 0.5 or 0.45?", subject="Math", topic="Decimals")
    db.add(q)
    await db.flush()
    stations = []
    for i in range(n_desks):
        s = PracticeStation(session_id=session.id, label=f"Desk {i + 1}", capture_interval_sec=10,
                            status="capturing", active_question_id=q.id)
        db.add(s)
        stations.append(s)
    await db.commit()
    return session, q, stations


async def _stick(db, session, q, station, code="M-NUM-01", status="conceptual_misconception"):
    db.add(PracticeAttempt(
        question_id=q.id, session_id=session.id, station_id=station.id, attempt_no=1,
        status="complete", validation_status=status, misconception_code=code,
    ))
    await db.commit()


async def _rows(db, session):
    return list((await db.execute(
        select(PracticeRadarAlert).where(PracticeRadarAlert.session_id == session.id)
    )).scalars().all())


@pytest.mark.asyncio
async def test_evaluate_is_idempotent(db: AsyncSession):
    session, q, stations = await _class(db, 4)
    for s in stations[:3]:
        await _stick(db, session, q, s)
    await radar_service.evaluate_and_alert(db, session.id)
    await radar_service.evaluate_and_alert(db, session.id)
    rows = await _rows(db, session)
    assert len(rows) == 1 and rows[0].status == "new" and rows[0].desk_count == 3


@pytest.mark.asyncio
async def test_dismissed_reopens_only_on_growth(db: AsyncSession):
    session, q, stations = await _class(db, 6)
    for s in stations[:3]:
        await _stick(db, session, q, s)
    await radar_service.evaluate_and_alert(db, session.id)
    row = (await _rows(db, session))[0]
    await radar_service.update_alert_status(db, row, "dismissed")

    await _stick(db, session, q, stations[3])  # 4 desks: +1, not enough
    await radar_service.evaluate_and_alert(db, session.id)
    assert (await _rows(db, session))[0].status == "dismissed"

    await _stick(db, session, q, stations[4])  # 5 desks: +2 -> reopen
    await radar_service.evaluate_and_alert(db, session.id)
    row = (await _rows(db, session))[0]
    assert row.status == "new" and row.desk_count == 5


@pytest.mark.asyncio
async def test_false_alarm_stays_suppressed(db: AsyncSession):
    session, q, stations = await _class(db, 6)
    for s in stations[:3]:
        await _stick(db, session, q, s)
    await radar_service.evaluate_and_alert(db, session.id)
    await radar_service.update_alert_status(db, (await _rows(db, session))[0], "false_alarm")
    for s in stations[3:6]:
        await _stick(db, session, q, s)
    data = await radar_service.get_active_alerts(db, session.id)
    assert data["alerts"] == []
    assert (await _rows(db, session))[0].status == "false_alarm"


@pytest.mark.asyncio
async def test_cluster_that_recovers_resolves(db: AsyncSession):
    session, q, stations = await _class(db, 3)
    for s in stations:
        await _stick(db, session, q, s)
    await radar_service.evaluate_and_alert(db, session.id)
    # two desks recover
    for s in stations[:2]:
        db.add(PracticeAttempt(
            question_id=q.id, session_id=session.id, station_id=s.id, attempt_no=2,
            status="complete", validation_status="valid_progress",
            created_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        ))
    await db.commit()
    data = await radar_service.get_active_alerts(db, session.id)
    assert data["alerts"] == []
    assert (await _rows(db, session))[0].status == "resolved"


@pytest.mark.asyncio
async def test_radar_api_hydrates_and_dismisses(client, db: AsyncSession):
    session, q, stations = await _class(db, 4)
    db.add(Misconception(
        code=f"T-RADAR-{uuid.uuid4().hex[:6]}", subject_key="math", grade_min=1, grade_max=10,
        topic="Decimals", title="Longer decimal means larger", description="Treats 0.45 as bigger than 0.5.",
        typical_work="0.45 > 0.5 because 45 > 5", source_citation="test", source_type="research",
    ))
    await db.commit()
    lib = (await db.execute(select(Misconception).where(Misconception.code.like("T-RADAR-%")))).scalars().first()
    for s in stations[:3]:
        await _stick(db, session, q, s, code=lib.code)

    r = await client.get(f"/v1/sessions/{session.id}/practice/radar")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["alerts"]) == 1
    alert = body["alerts"][0]
    assert alert["title"] == "Longer decimal means larger"
    assert alert["desk_count"] == 3 and alert["attempting_count"] == 3
    assert {d["label"] for d in alert["desks"]} <= {"Desk 1", "Desk 2", "Desk 3", "Desk 4"}

    p = await client.patch(f"/v1/radar-alerts/{alert['id']}", json={"status": "dismissed"})
    assert p.status_code == 200 and p.json()["status"] == "dismissed"
    again = await client.get(f"/v1/sessions/{session.id}/practice/radar")
    assert again.json()["alerts"] == []

    bad = await client.patch(f"/v1/radar-alerts/{alert['id']}", json={"status": "bogus"})
    assert bad.status_code == 422
