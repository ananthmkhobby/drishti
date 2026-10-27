"""
Class Misconception Radar — cross-desk pattern detection.

Each desk (practice station) is graded independently, so a teacher only sees
one desk at a time. The radar looks across desks: when several desks working
the SAME question are stuck on the SAME misconception (by library code), that
is a teaching problem rather than a student problem, and the teacher is told
once so they can address the room.

Thresholds are deliberately conservative — a false "the class is stuck"
alarm costs the teacher's trust faster than a missed one costs anything:
  * at least MIN_DESKS desks in the cluster, AND
  * the cluster is at least MIN_SHARE of the desks that attempted the question
  * only each desk's LATEST complete attempt counts (a desk that repeated the
    mistake five times is one desk, and a desk that has since recovered is not
    stuck any more)
  * only attempts inside WINDOW_MINUTES count (stale desks drop out)
Desks stuck without a library code (e.g. plain arithmetic slips) are reported
as "unclassified" for transparency but never raise an alert — we won't claim a
shared misconception we can't name.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.misconception import Misconception
from app.models.practice_attempt import PracticeAttempt
from app.models.practice_question import PracticeQuestion
from app.models.practice_radar_alert import PracticeRadarAlert
from app.models.practice_station import PracticeStation
from app.services.practice_service import _MISTAKE_STATUSES

logger = logging.getLogger(__name__)

MIN_DESKS = 3
MIN_SHARE = 0.4
WINDOW_MINUTES = 120
# A dismissed alert only comes back if the cluster has clearly grown since.
REOPEN_GROWTH = 2


@dataclass
class Cluster:
    question_id: uuid.UUID
    code: str
    station_ids: list[uuid.UUID]
    attempting_count: int


@dataclass
class RadarResult:
    clusters: list[Cluster] = field(default_factory=list)
    # question_id -> station_ids stuck with no usable library code
    unclassified: dict[uuid.UUID, list[uuid.UUID]] = field(default_factory=dict)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def find_clusters(
    attempts: list[PracticeAttempt],
    now: datetime | None = None,
    window_minutes: int = WINDOW_MINUTES,
    min_desks: int = MIN_DESKS,
    min_share: float = MIN_SHARE,
) -> RadarResult:
    """Pure: no DB access. `attempts` may be any mix; filtering happens here."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=window_minutes)

    latest: dict[tuple[uuid.UUID, uuid.UUID], PracticeAttempt] = {}
    for a in attempts:
        if a.station_id is None or a.status != "complete":
            continue
        ts = _aware(a.created_at)
        if ts is None or ts < cutoff:
            continue
        key = (a.question_id, a.station_id)
        cur = latest.get(key)
        if cur is None or (_aware(a.created_at), a.attempt_no) > (_aware(cur.created_at), cur.attempt_no):
            latest[key] = a

    by_question: dict[uuid.UUID, list[PracticeAttempt]] = {}
    for (qid, _sid), a in latest.items():
        by_question.setdefault(qid, []).append(a)

    result = RadarResult()
    for qid, rows in by_question.items():
        attempting = len(rows)
        stuck = [a for a in rows if a.validation_status in _MISTAKE_STATUSES]
        by_code: dict[str, list[uuid.UUID]] = {}
        unclassified: list[uuid.UUID] = []
        for a in stuck:
            if a.misconception_code:
                by_code.setdefault(a.misconception_code, []).append(a.station_id)
            else:
                unclassified.append(a.station_id)
        if unclassified:
            result.unclassified[qid] = unclassified
        for code, sids in by_code.items():
            if len(sids) >= min_desks and len(sids) / attempting >= min_share:
                result.clusters.append(Cluster(qid, code, sids, attempting))
    result.clusters.sort(key=lambda c: (-len(c.station_ids), str(c.question_id)))
    return result


async def _load_attempts(db: AsyncSession, session_id: uuid.UUID) -> list[PracticeAttempt]:
    return list((
        await db.execute(
            select(PracticeAttempt).where(
                PracticeAttempt.session_id == session_id,
                PracticeAttempt.station_id.is_not(None),
                PracticeAttempt.status == "complete",
            )
        )
    ).scalars().all())


async def evaluate_and_alert(db: AsyncSession, session_id: uuid.UUID) -> RadarResult:
    """
    Recompute the session's clusters and reconcile the alert rows. Idempotent —
    safe to call after every graded attempt and again on every radar read.
    """
    result = find_clusters(await _load_attempts(db, session_id))
    rows = list((
        await db.execute(select(PracticeRadarAlert).where(PracticeRadarAlert.session_id == session_id))
    ).scalars().all())
    by_key = {(r.question_id, r.code): r for r in rows}
    qualifying = {(c.question_id, c.code) for c in result.clusters}

    for c in result.clusters:
        count = len(c.station_ids)
        ids = [str(s) for s in c.station_ids]
        row = by_key.get((c.question_id, c.code))
        if row is None:
            db.add(PracticeRadarAlert(
                session_id=session_id, question_id=c.question_id, code=c.code,
                desk_ids=ids, desk_count=count, attempting_count=c.attempting_count, status="new",
            ))
            continue
        if row.status == "new" or row.status == "acted":
            row.desk_ids, row.desk_count, row.attempting_count = ids, count, c.attempting_count
        elif row.status == "resolved":
            row.desk_ids, row.desk_count, row.attempting_count = ids, count, c.attempting_count
            row.status = "new"
        elif row.status == "dismissed" and count >= row.desk_count + REOPEN_GROWTH:
            row.desk_ids, row.desk_count, row.attempting_count = ids, count, c.attempting_count
            row.status = "new"
        # false_alarm: stays suppressed for this question+code.

    for key, row in by_key.items():
        if key not in qualifying and row.status == "new":
            row.status = "resolved"

    try:
        await db.commit()
    except IntegrityError:
        # A concurrent evaluation inserted the same (session, question, code)
        # first; theirs is equivalent, so drop ours.
        await db.rollback()
    return result


async def get_active_alerts(db: AsyncSession, session_id: uuid.UUID) -> dict:
    """Reconcile, then return the alerts a teacher should currently see."""
    result = await evaluate_and_alert(db, session_id)
    live = {(c.question_id, c.code): c for c in result.clusters}

    rows = list((
        await db.execute(
            select(PracticeRadarAlert).where(
                PracticeRadarAlert.session_id == session_id, PracticeRadarAlert.status == "new",
            )
        )
    ).scalars().all())
    rows = [r for r in rows if (r.question_id, r.code) in live]

    stations = {
        s.id: s for s in (
            await db.execute(select(PracticeStation).where(PracticeStation.session_id == session_id))
        ).scalars().all()
    }
    q_ids = {r.question_id for r in rows} | set(result.unclassified)
    questions = {
        q.id: q for q in (
            await db.execute(select(PracticeQuestion).where(PracticeQuestion.id.in_(q_ids)))
        ).scalars().all()
    } if q_ids else {}
    codes = {r.code for r in rows}
    library = {
        m.code: m for m in (
            await db.execute(select(Misconception).where(Misconception.code.in_(codes)))
        ).scalars().all()
    } if codes else {}

    alerts = []
    for r in sorted(rows, key=lambda r: -r.desk_count):
        cluster = live[(r.question_id, r.code)]
        q = questions.get(r.question_id)
        lib = library.get(r.code)
        title, description, typical = None, None, None
        if lib:
            title, description, typical = lib.title, lib.description, lib.typical_work
        elif q and q.known_misconceptions:
            for km in q.known_misconceptions:
                if isinstance(km, dict) and km.get("code") == r.code:
                    description = km.get("description")
        alerts.append({
            "id": r.id,
            "question_id": r.question_id,
            "question_text": q.text if q else None,
            "topic": q.topic if q else None,
            "code": r.code,
            "title": title or r.code,
            "description": description,
            "typical_work": typical,
            "desk_count": len(cluster.station_ids),
            "attempting_count": cluster.attempting_count,
            "desks": [
                {"station_id": sid, "label": stations[sid].label if sid in stations else "Desk"}
                for sid in cluster.station_ids
            ],
            "status": r.status,
            "created_at": r.created_at,
        })

    unclassified = [
        {
            "question_id": qid,
            "question_text": questions[qid].text if qid in questions else None,
            "desk_count": len(sids),
        }
        for qid, sids in result.unclassified.items()
    ]
    return {"alerts": alerts, "unclassified": unclassified}


_VALID_STATUS_UPDATES = {"dismissed", "false_alarm", "acted"}


async def update_alert_status(db: AsyncSession, alert: PracticeRadarAlert, status: str) -> PracticeRadarAlert:
    if status not in _VALID_STATUS_UPDATES:
        raise ValueError(f"Invalid status {status!r}")
    alert.status = status
    await db.commit()
    await db.refresh(alert)
    return alert
