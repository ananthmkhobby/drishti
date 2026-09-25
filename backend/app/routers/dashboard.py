"""
Dashboard router — summary widgets and detailed reports for all three roles.

Endpoints
─────────
GET /dashboard/teacher/{teacher_id}              → TeacherDashboard  (summary widget)
GET /dashboard/teacher/{teacher_id}/report       → TeacherReport     (full reports page)
GET /teachers/{teacher_id}/memory                → ClassroomMemoryResponse

GET /dashboard/admin/{school_id}                 → AdminDashboard    (summary widget)
GET /dashboard/admin/{school_id}/report          → AdminReport       (full report)
GET /dashboard/admin/{school_id}/teachers        → list[TeacherUsageSummary]

GET /dashboard/csr/{program_id}                  → CSRDashboard      (summary widget)
GET /dashboard/csr/{program_id}/report           → CSRReport         (full report)
GET /dashboard/csr/{program_id}/schools          → list[SchoolSummary]
"""

import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import select, func, text, distinct, case

from app.dependencies import CurrentTeacher, DB
from app.exceptions import ACIError
from app.models.session import Session
from app.models.ai_output import AIOutput
from app.models.quiz_question import QuizQuestion
from app.models.classroom_memory import ClassroomMemory
from app.models.missing_concept import MissingConcept
from app.models.teacher import Teacher
from app.models.school import School
from app.models.program import Program
from collections import Counter

from app.schemas.dashboard import (
    # Shared types
    SessionTimeSeries,
    SubjectCount,
    BloomCount,
    SyncBreakdown,
    TopicEntry,
    MissingConceptItem,
    QuizSessionSummary,
    # Role-specific schemas
    TeacherDashboard,
    TeacherReport,
    ClassroomMemoryResponse,
    AdminDashboard,
    AdminReport,
    TeacherUsageSummary,
    CSRDashboard,
    CSRReport,
    SchoolSummary,
    ConceptCoverageEntry,
    UnitSummary,
    UnitDetail,
    UnitSessionEntry,
    RecurringGap,
)

router = APIRouter(tags=["Dashboard"])

_VALID_PERIODS = {7, 30, 90, 365}


def _period_start(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _sync_health(pending: int, failed: int, total: int) -> str:
    if total == 0:
        return "unknown"
    fail_rate = failed / total
    pending_rate = pending / total
    if fail_rate > 0.3:
        return "offline"
    if fail_rate > 0.1 or pending_rate > 0.5:
        return "degraded"
    return "healthy"


# ─── Teacher dashboard ────────────────────────────────────────────────────────

@router.get("/dashboard/teacher/{teacher_id}", response_model=TeacherDashboard)
async def teacher_dashboard(teacher_id: uuid.UUID, db: DB, _: CurrentTeacher):
    """Compact summary — feeds the top-of-page stat widgets."""
    sessions_count = (
        await db.execute(
            select(func.count(Session.id)).where(Session.teacher_id == teacher_id)
        )
    ).scalar_one()

    ai_outputs_count = (
        await db.execute(
            select(func.count(AIOutput.id))
            .join(Session, AIOutput.session_id == Session.id)
            .where(Session.teacher_id == teacher_id, AIOutput.status == "ready")
        )
    ).scalar_one()

    tiqer_count = (
        await db.execute(
            select(func.count(QuizQuestion.id))
            .join(Session, QuizQuestion.session_id == Session.id)
            .where(Session.teacher_id == teacher_id, QuizQuestion.tiqer_exported.is_(True))
        )
    ).scalar_one()

    missing_count = (
        await db.execute(
            select(func.count(MissingConcept.id))
            .join(Session, MissingConcept.session_id == Session.id)
            .where(Session.teacher_id == teacher_id)
        )
    ).scalar_one()

    pending_sync = (
        await db.execute(
            select(func.count(Session.id)).where(
                Session.teacher_id == teacher_id,
                Session.sync_status.in_(["pending", "failed"]),
            )
        )
    ).scalar_one()

    topics_count = (
        await db.execute(
            select(func.count(distinct(QuizQuestion.topic)))
            .join(Session, QuizQuestion.session_id == Session.id)
            .where(Session.teacher_id == teacher_id, QuizQuestion.topic.isnot(None))
        )
    ).scalar_one()

    return TeacherDashboard(
        teacher_id=teacher_id,
        sessions_conducted=sessions_count,
        topics_covered=topics_count,
        ai_outputs_generated=ai_outputs_count,
        tiqer_sessions=tiqer_count,
        missing_concepts_flagged=missing_count,
        pending_sync=pending_sync,
    )


# ─── Teacher full report ──────────────────────────────────────────────────────

@router.get("/dashboard/teacher/{teacher_id}/report", response_model=TeacherReport)
async def teacher_report(
    teacher_id: uuid.UUID,
    db: DB,
    _: CurrentTeacher,
    period: int = Query(30, description="Look-back window in days (7 / 30 / 90 / 365)"),
):
    """
    Full report for the teacher reports page.
    Covers sessions, topics, quizzes, Bloom distribution, missing concepts, sync.
    """
    if period not in _VALID_PERIODS:
        period = 30
    since = _period_start(period)

    # ── Summary counts ────────────────────────────────────────────────────────

    sessions_total = (
        await db.execute(
            select(func.count(Session.id)).where(Session.teacher_id == teacher_id)
        )
    ).scalar_one()

    sessions_this_period = (
        await db.execute(
            select(func.count(Session.id)).where(
                Session.teacher_id == teacher_id,
                Session.created_at >= since,
            )
        )
    ).scalar_one()

    ai_total = (
        await db.execute(
            select(func.count(AIOutput.id))
            .join(Session, AIOutput.session_id == Session.id)
            .where(Session.teacher_id == teacher_id, AIOutput.status == "ready")
        )
    ).scalar_one()

    ai_this_period = (
        await db.execute(
            select(func.count(AIOutput.id))
            .join(Session, AIOutput.session_id == Session.id)
            .where(
                Session.teacher_id == teacher_id,
                AIOutput.status == "ready",
                AIOutput.created_at >= since,
            )
        )
    ).scalar_one()

    # Sessions that have at least one quiz question (= "quizzes generated")
    quizzes_generated = (
        await db.execute(
            select(func.count(distinct(QuizQuestion.session_id)))
            .join(Session, QuizQuestion.session_id == Session.id)
            .where(Session.teacher_id == teacher_id)
        )
    ).scalar_one()

    quizzes_exported = (
        await db.execute(
            select(func.count(QuizQuestion.id))
            .join(Session, QuizQuestion.session_id == Session.id)
            .where(Session.teacher_id == teacher_id, QuizQuestion.tiqer_exported.is_(True))
        )
    ).scalar_one()

    topics_count = (
        await db.execute(
            select(func.count(distinct(QuizQuestion.topic)))
            .join(Session, QuizQuestion.session_id == Session.id)
            .where(Session.teacher_id == teacher_id, QuizQuestion.topic.isnot(None))
        )
    ).scalar_one()

    missing_total = (
        await db.execute(
            select(func.count(MissingConcept.id))
            .join(Session, MissingConcept.session_id == Session.id)
            .where(Session.teacher_id == teacher_id)
        )
    ).scalar_one()

    missing_resolved = (
        await db.execute(
            select(func.count(MissingConcept.id))
            .join(Session, MissingConcept.session_id == Session.id)
            .where(Session.teacher_id == teacher_id, MissingConcept.resolved.is_(True))
        )
    ).scalar_one()

    # Sync counts
    sync_rows = (
        await db.execute(
            select(Session.sync_status, func.count(Session.id))
            .where(Session.teacher_id == teacher_id)
            .group_by(Session.sync_status)
        )
    ).all()
    sync_map: dict[str, int] = {r[0]: r[1] for r in sync_rows}
    sync_breakdown = SyncBreakdown(
        pending=sync_map.get("pending", 0),
        syncing=sync_map.get("syncing", 0),
        synced=sync_map.get("synced", 0),
        failed=sync_map.get("failed", 0),
    )

    # ── Time series: sessions per day for last `period` days ─────────────────
    # SQLite: strftime; PostgreSQL: to_char or date_trunc
    # Use a DB-agnostic approach: fetch sessions and bucket in Python
    period_sessions = (
        await db.execute(
            select(Session.created_at)
            .where(Session.teacher_id == teacher_id, Session.created_at >= since)
            .order_by(Session.created_at)
        )
    ).scalars().all()

    day_counts: dict[str, int] = {}
    for dt in period_sessions:
        day = dt.strftime("%Y-%m-%d")
        day_counts[day] = day_counts.get(day, 0) + 1

    # Fill in zeros for every day in the period
    sessions_over_time: list[SessionTimeSeries] = []
    for i in range(period):
        day = (datetime.now(timezone.utc) - timedelta(days=period - 1 - i)).strftime("%Y-%m-%d")
        sessions_over_time.append(SessionTimeSeries(date=day, count=day_counts.get(day, 0)))

    # ── Subject breakdown ─────────────────────────────────────────────────────
    subject_rows = (
        await db.execute(
            select(Session.subject, func.count(Session.id))
            .where(Session.teacher_id == teacher_id, Session.subject.isnot(None))
            .group_by(Session.subject)
            .order_by(func.count(Session.id).desc())
        )
    ).all()
    subject_breakdown = [SubjectCount(subject=r[0], count=r[1]) for r in subject_rows]

    # ── Topics covered ────────────────────────────────────────────────────────
    topic_rows = (
        await db.execute(
            select(QuizQuestion.topic, func.count(QuizQuestion.id))
            .join(Session, QuizQuestion.session_id == Session.id)
            .where(Session.teacher_id == teacher_id, QuizQuestion.topic.isnot(None))
            .group_by(QuizQuestion.topic)
            .order_by(func.count(QuizQuestion.id).desc())
            .limit(50)
        )
    ).all()
    topics_covered = [TopicEntry(topic=r[0], frequency=r[1]) for r in topic_rows]

    # ── Bloom distribution ────────────────────────────────────────────────────
    bloom_rows = (
        await db.execute(
            select(QuizQuestion.bloom_level, func.count(QuizQuestion.id))
            .join(Session, QuizQuestion.session_id == Session.id)
            .where(Session.teacher_id == teacher_id, QuizQuestion.bloom_level.isnot(None))
            .group_by(QuizQuestion.bloom_level)
            .order_by(func.count(QuizQuestion.id).desc())
        )
    ).all()
    bloom_distribution = [BloomCount(bloom_level=r[0], count=r[1]) for r in bloom_rows]

    # ── Recent missing concepts (last 10 unresolved) ──────────────────────────
    mc_rows = (
        await db.execute(
            select(MissingConcept, Session.subject)
            .join(Session, MissingConcept.session_id == Session.id)
            .where(Session.teacher_id == teacher_id, MissingConcept.resolved.is_(False))
            .order_by(MissingConcept.created_at.desc())
            .limit(10)
        )
    ).all()
    recent_missing = [
        MissingConceptItem(
            concept_id=str(mc.id),
            concept=mc.concept,
            concept_type=mc.concept_type,
            description=mc.description,
            session_id=str(mc.session_id),
            session_subject=subject,
            resolved=mc.resolved,
            created_at=mc.created_at.isoformat(),
        )
        for mc, subject in mc_rows
    ]

    # ── Quiz sessions summary ─────────────────────────────────────────────────
    quiz_sess_rows = (
        await db.execute(
            select(
                Session.id,
                Session.subject,
                Session.grade,
                Session.created_at,
                func.count(QuizQuestion.id).label("question_count"),
                func.sum(
                    case((QuizQuestion.tiqer_exported.is_(True), 1), else_=0)
                ).label("exported_count"),
            )
            .outerjoin(QuizQuestion, QuizQuestion.session_id == Session.id)
            .where(Session.teacher_id == teacher_id)
            .group_by(Session.id, Session.subject, Session.grade, Session.created_at)
            .having(func.count(QuizQuestion.id) > 0)
            .order_by(Session.created_at.desc())
            .limit(20)
        )
    ).all()
    quiz_sessions = [
        QuizSessionSummary(
            session_id=str(r.id),
            subject=r.subject,
            grade=r.grade,
            question_count=r.question_count or 0,
            exported_to_tiqer=r.exported_count or 0,
            created_at=r.created_at.isoformat(),
        )
        for r in quiz_sess_rows
    ]

    return TeacherReport(
        teacher_id=teacher_id,
        period_days=period,
        sessions_total=sessions_total,
        sessions_this_period=sessions_this_period,
        ai_outputs_total=ai_total,
        ai_outputs_this_period=ai_this_period,
        quizzes_generated=quizzes_generated,
        quizzes_exported_to_tiqer=quizzes_exported,
        topics_count=topics_count,
        missing_concepts_total=missing_total,
        missing_concepts_resolved=missing_resolved,
        sync_pending=sync_breakdown.pending,
        sync_failed=sync_breakdown.failed,
        sync_completed=sync_breakdown.synced,
        sessions_over_time=sessions_over_time,
        subject_breakdown=subject_breakdown,
        topics_covered=topics_covered,
        bloom_distribution=bloom_distribution,
        sync_breakdown=sync_breakdown,
        recent_missing_concepts=recent_missing,
        quiz_sessions=quiz_sessions,
    )


# ─── Unit View ───────────────────────────────────────────────────────────────

@router.get("/dashboard/teacher/{teacher_id}/units", response_model=list[UnitSummary])
async def teacher_units(teacher_id: uuid.UUID, db: DB, _: CurrentTeacher):
    """Return all subject+grade pairs for this teacher, ordered by most recent session."""
    rows = (
        await db.execute(
            select(
                Session.subject,
                Session.grade,
                func.count(Session.id).label("session_count"),
                func.min(func.date(Session.created_at)).label("first_date"),
                func.max(func.date(Session.created_at)).label("last_date"),
            )
            .where(
                Session.teacher_id == teacher_id,
                Session.subject.isnot(None),
                Session.grade.isnot(None),
            )
            .group_by(Session.subject, Session.grade)
            .order_by(func.max(Session.created_at).desc())
        )
    ).all()

    return [
        UnitSummary(
            subject=r.subject,
            grade=r.grade,
            session_count=r.session_count,
            first_date=str(r.first_date),
            last_date=str(r.last_date),
        )
        for r in rows
    ]


@router.get("/dashboard/teacher/{teacher_id}/units/{subject}/{grade}", response_model=UnitDetail)
async def teacher_unit_detail(
    teacher_id: uuid.UUID,
    subject: str,
    grade: str,
    db: DB,
    _: CurrentTeacher,
):
    """Full unit detail — session timeline, recurring gaps, continue-from-here."""
    sessions = (
        await db.execute(
            select(Session)
            .where(
                Session.teacher_id == teacher_id,
                Session.subject == subject,
                Session.grade == grade,
            )
            .order_by(Session.created_at.asc())
        )
    ).scalars().all()

    if not sessions:
        raise ACIError(404, "No sessions found for this subject and grade")

    session_ids = [s.id for s in sessions]

    # Fetch combined_analysis and missing_concepts outputs for all sessions at once
    outputs = (
        await db.execute(
            select(AIOutput)
            .where(
                AIOutput.session_id.in_(session_ids),
                AIOutput.output_type.in_(["combined_analysis", "missing_concepts"]),
                AIOutput.status == "ready",
            )
        )
    ).scalars().all()

    # Index by (session_id, output_type)
    output_map: dict[tuple, dict] = {}
    for o in outputs:
        if o.content_json:
            output_map[(str(o.session_id), o.output_type)] = o.content_json

    # Track gap frequency across sessions
    gap_counter: Counter = Counter()

    session_entries: list[UnitSessionEntry] = []
    for s in sessions:
        sid = str(s.id)
        analysis = output_map.get((sid, "combined_analysis"), {})
        mc = output_map.get((sid, "missing_concepts"), {})

        # Topics from combined_analysis.topics_spoken
        topics_covered = [
            t.get("topic", "") for t in (analysis.get("topics_spoken") or [])
            if t.get("topic")
        ]

        # Gaps from missing_concepts.pedagogical_gaps.conceptual_gaps
        pg = mc.get("pedagogical_gaps") or {}
        gaps = [str(g) for g in (pg.get("conceptual_gaps") or []) if g]
        # Also check legacy format
        if not gaps:
            gaps = [str(g) for g in (mc.get("conceptual_gaps") or []) if g]

        for g in gaps:
            gap_counter[g] += 1

        # Suggested next from missing_concepts.suggested_next_steps
        suggested = [str(x) for x in (mc.get("suggested_next_steps") or []) if x]
        if not suggested and mc.get("suggested_next"):
            suggested = [mc["suggested_next"]]

        session_entries.append(UnitSessionEntry(
            session_id=sid,
            date=s.created_at.strftime("%Y-%m-%d") if s.created_at else "",
            title=s.title,
            topics_covered=topics_covered,
            gaps=gaps,
            suggested_next=suggested,
        ))

    # Recurring gaps = appeared in 2+ sessions, sorted by frequency desc
    recurring = [
        RecurringGap(concept=concept, count=count)
        for concept, count in gap_counter.most_common()
        if count >= 2
    ]

    # Continue from here = most recent session's suggested_next
    continue_from = session_entries[-1].suggested_next if session_entries else []

    return UnitDetail(
        subject=subject,
        grade=grade,
        sessions=session_entries,
        recurring_gaps=recurring,
        continue_from_here=continue_from,
    )


# ─── Classroom memory (Continue My Class panel) ───────────────────────────────

@router.get("/teachers/{teacher_id}/memory", response_model=ClassroomMemoryResponse)
async def teacher_memory(teacher_id: uuid.UUID, db: DB, _: CurrentTeacher):
    memory = (
        await db.execute(
            select(ClassroomMemory).where(ClassroomMemory.teacher_id == teacher_id)
        )
    ).scalar_one_or_none()

    if not memory:
        return ClassroomMemoryResponse(
            teacher_id=teacher_id,
            last_session=None,
            pending_concepts=[],
            suggested_next=None,
            quick_revision=None,
        )

    last_session = None
    if memory.last_session_id:
        session = await db.get(Session, memory.last_session_id)
        if session:
            last_session = {
                "date": session.created_at.isoformat(),
                "subject": session.subject,
                "topics": memory.topics_covered or [],
            }

    return ClassroomMemoryResponse(
        teacher_id=teacher_id,
        last_session=last_session,
        pending_concepts=memory.pending_concepts or [],
        suggested_next=memory.suggested_next,
        quick_revision=None,  # Phase 2: AI-generated revision question
    )


# ─── Admin dashboard ──────────────────────────────────────────────────────────

@router.get("/dashboard/admin/{school_id}", response_model=AdminDashboard)
async def admin_dashboard(school_id: uuid.UUID, db: DB, _: CurrentTeacher):
    """Compact summary widget for admin home."""
    total_sessions = (await db.execute(select(func.count(Session.id)))).scalar_one()
    total_ai_outputs = (
        await db.execute(
            select(func.count(AIOutput.id)).where(AIOutput.status == "ready")
        )
    ).scalar_one()
    total_tiqer = (
        await db.execute(
            select(func.count(QuizQuestion.id)).where(QuizQuestion.tiqer_exported.is_(True))
        )
    ).scalar_one()
    pending_sync = (
        await db.execute(
            select(func.count(Session.id)).where(
                Session.sync_status.in_(["pending", "failed"])
            )
        )
    ).scalar_one()
    active_teachers = (
        await db.execute(
            select(func.count(distinct(Session.teacher_id)))
            .join(Teacher, Session.teacher_id == Teacher.id)
            .where(Teacher.school_id == school_id)
        )
    ).scalar_one()

    return AdminDashboard(
        school_id=school_id,
        total_sessions=total_sessions,
        active_teachers=active_teachers,
        total_ai_outputs=total_ai_outputs,
        total_tiqer_exports=total_tiqer,
        pending_sync_sessions=pending_sync,
    )


@router.get("/dashboard/admin/{school_id}/report", response_model=AdminReport)
async def admin_report(
    school_id: uuid.UUID,
    db: DB,
    _: CurrentTeacher,
    period: int = Query(30, description="Look-back window in days"),
):
    """Full admin report — all teachers in the school."""
    if period not in _VALID_PERIODS:
        period = 30
    since = _period_start(period)

    # Verify school exists
    school = await db.get(School, school_id)
    school_name = school.name if school else str(school_id)

    # All teacher IDs in this school
    teacher_ids_rows = (
        await db.execute(
            select(Teacher.id).where(Teacher.school_id == school_id, Teacher.is_active.is_(True))
        )
    ).scalars().all()
    teacher_ids = list(teacher_ids_rows)

    total_teachers = len(teacher_ids)

    if not teacher_ids:
        # Return empty report for school with no teachers yet
        return AdminReport(
            school_id=school_id,
            school_name=school_name,
            period_days=period,
            total_sessions=0,
            sessions_this_period=0,
            total_teachers=0,
            active_teachers=0,
            total_ai_outputs=0,
            total_tiqer_exports=0,
            pending_sync_sessions=0,
            sessions_over_time=[
                SessionTimeSeries(
                    date=(datetime.now(timezone.utc) - timedelta(days=period - 1 - i)).strftime("%Y-%m-%d"),
                    count=0,
                )
                for i in range(period)
            ],
            subject_breakdown=[],
            teachers=[],
        )

    # Session totals
    total_sessions = (
        await db.execute(
            select(func.count(Session.id)).where(Session.teacher_id.in_(teacher_ids))
        )
    ).scalar_one()

    sessions_this_period = (
        await db.execute(
            select(func.count(Session.id)).where(
                Session.teacher_id.in_(teacher_ids),
                Session.created_at >= since,
            )
        )
    ).scalar_one()

    active_teachers = (
        await db.execute(
            select(func.count(distinct(Session.teacher_id))).where(
                Session.teacher_id.in_(teacher_ids),
                Session.created_at >= since,
            )
        )
    ).scalar_one()

    total_ai_outputs = (
        await db.execute(
            select(func.count(AIOutput.id))
            .join(Session, AIOutput.session_id == Session.id)
            .where(Session.teacher_id.in_(teacher_ids), AIOutput.status == "ready")
        )
    ).scalar_one()

    total_tiqer = (
        await db.execute(
            select(func.count(QuizQuestion.id))
            .join(Session, QuizQuestion.session_id == Session.id)
            .where(Session.teacher_id.in_(teacher_ids), QuizQuestion.tiqer_exported.is_(True))
        )
    ).scalar_one()

    pending_sync = (
        await db.execute(
            select(func.count(Session.id)).where(
                Session.teacher_id.in_(teacher_ids),
                Session.sync_status.in_(["pending", "failed"]),
            )
        )
    ).scalar_one()

    # Time series
    period_sessions_dt = (
        await db.execute(
            select(Session.created_at).where(
                Session.teacher_id.in_(teacher_ids),
                Session.created_at >= since,
            )
        )
    ).scalars().all()
    day_counts: dict[str, int] = {}
    for dt in period_sessions_dt:
        day = dt.strftime("%Y-%m-%d")
        day_counts[day] = day_counts.get(day, 0) + 1
    sessions_over_time = [
        SessionTimeSeries(
            date=(datetime.now(timezone.utc) - timedelta(days=period - 1 - i)).strftime("%Y-%m-%d"),
            count=day_counts.get(
                (datetime.now(timezone.utc) - timedelta(days=period - 1 - i)).strftime("%Y-%m-%d"), 0
            ),
        )
        for i in range(period)
    ]

    # Subject breakdown
    subj_rows = (
        await db.execute(
            select(Session.subject, func.count(Session.id))
            .where(Session.teacher_id.in_(teacher_ids), Session.subject.isnot(None))
            .group_by(Session.subject)
            .order_by(func.count(Session.id).desc())
        )
    ).all()
    subject_breakdown = [SubjectCount(subject=r[0], count=r[1]) for r in subj_rows]

    # Per-teacher stats
    teacher_rows = (
        await db.execute(
            select(Teacher).where(Teacher.id.in_(teacher_ids))
        )
    ).scalars().all()

    teachers: list[TeacherUsageSummary] = []
    for t in teacher_rows:
        sess_count = (
            await db.execute(
                select(func.count(Session.id)).where(Session.teacher_id == t.id)
            )
        ).scalar_one()

        last_session_dt = (
            await db.execute(
                select(func.max(Session.created_at)).where(Session.teacher_id == t.id)
            )
        ).scalar_one()

        ai_count = (
            await db.execute(
                select(func.count(AIOutput.id))
                .join(Session, AIOutput.session_id == Session.id)
                .where(Session.teacher_id == t.id, AIOutput.status == "ready")
            )
        ).scalar_one()

        tiqer_count = (
            await db.execute(
                select(func.count(QuizQuestion.id))
                .join(Session, QuizQuestion.session_id == Session.id)
                .where(Session.teacher_id == t.id, QuizQuestion.tiqer_exported.is_(True))
            )
        ).scalar_one()

        subj_count = (
            await db.execute(
                select(func.count(distinct(Session.subject))).where(
                    Session.teacher_id == t.id, Session.subject.isnot(None)
                )
            )
        ).scalar_one()

        pending_t = (
            await db.execute(
                select(func.count(Session.id)).where(
                    Session.teacher_id == t.id, Session.sync_status.in_(["pending", "failed"])
                )
            )
        ).scalar_one()
        failed_t = (
            await db.execute(
                select(func.count(Session.id)).where(
                    Session.teacher_id == t.id, Session.sync_status == "failed"
                )
            )
        ).scalar_one()

        teachers.append(TeacherUsageSummary(
            teacher_id=str(t.id),
            name=t.name,
            email=t.email,
            session_count=sess_count,
            ai_outputs_count=ai_count,
            tiqer_exports=tiqer_count,
            subject_count=subj_count,
            last_active=last_session_dt.isoformat() if last_session_dt else None,
            sync_health=_sync_health(pending_t, failed_t, sess_count),
        ))

    # Sort by session count desc
    teachers.sort(key=lambda t: t.session_count, reverse=True)

    return AdminReport(
        school_id=school_id,
        school_name=school_name,
        period_days=period,
        total_sessions=total_sessions,
        sessions_this_period=sessions_this_period,
        total_teachers=total_teachers,
        active_teachers=active_teachers,
        total_ai_outputs=total_ai_outputs,
        total_tiqer_exports=total_tiqer,
        pending_sync_sessions=pending_sync,
        sessions_over_time=sessions_over_time,
        subject_breakdown=subject_breakdown,
        teachers=teachers,
    )


@router.get("/dashboard/admin/{school_id}/teachers", response_model=list[TeacherUsageSummary])
async def admin_teacher_list(school_id: uuid.UUID, db: DB, _: CurrentTeacher):
    """Teacher list with usage stats for admin view."""
    teacher_rows = (
        await db.execute(
            select(Teacher).where(Teacher.school_id == school_id, Teacher.is_active.is_(True))
        )
    ).scalars().all()

    result: list[TeacherUsageSummary] = []
    for t in teacher_rows:
        sess_count = (
            await db.execute(
                select(func.count(Session.id)).where(Session.teacher_id == t.id)
            )
        ).scalar_one()
        last_dt = (
            await db.execute(
                select(func.max(Session.created_at)).where(Session.teacher_id == t.id)
            )
        ).scalar_one()
        ai_count = (
            await db.execute(
                select(func.count(AIOutput.id))
                .join(Session, AIOutput.session_id == Session.id)
                .where(Session.teacher_id == t.id, AIOutput.status == "ready")
            )
        ).scalar_one()
        tiqer_count = (
            await db.execute(
                select(func.count(QuizQuestion.id))
                .join(Session, QuizQuestion.session_id == Session.id)
                .where(Session.teacher_id == t.id, QuizQuestion.tiqer_exported.is_(True))
            )
        ).scalar_one()
        subj_count = (
            await db.execute(
                select(func.count(distinct(Session.subject))).where(
                    Session.teacher_id == t.id, Session.subject.isnot(None)
                )
            )
        ).scalar_one()
        pending_t = (
            await db.execute(
                select(func.count(Session.id)).where(
                    Session.teacher_id == t.id, Session.sync_status.in_(["pending", "failed"])
                )
            )
        ).scalar_one()
        failed_t = (
            await db.execute(
                select(func.count(Session.id)).where(
                    Session.teacher_id == t.id, Session.sync_status == "failed"
                )
            )
        ).scalar_one()
        result.append(TeacherUsageSummary(
            teacher_id=str(t.id),
            name=t.name,
            email=t.email,
            session_count=sess_count,
            ai_outputs_count=ai_count,
            tiqer_exports=tiqer_count,
            subject_count=subj_count,
            last_active=last_dt.isoformat() if last_dt else None,
            sync_health=_sync_health(pending_t, failed_t, sess_count),
        ))

    result.sort(key=lambda t: t.session_count, reverse=True)
    return result


# ─── CSR dashboard ────────────────────────────────────────────────────────────

@router.get("/dashboard/csr/{program_id}", response_model=CSRDashboard)
async def csr_dashboard(program_id: uuid.UUID, db: DB, _: CurrentTeacher):
    """Compact summary widget for CSR/program home."""
    school_ids = (
        await db.execute(
            select(School.id).where(School.program_id == program_id, School.is_active.is_(True))
        )
    ).scalars().all()

    total_schools = len(school_ids)

    if not school_ids:
        return CSRDashboard(
            program_id=program_id,
            total_schools=0,
            total_sessions=0,
            active_teachers=0,
            total_topics_covered=0,
            connectivity_failure_rate=0.0,
        )

    teacher_ids = (
        await db.execute(
            select(Teacher.id).where(Teacher.school_id.in_(school_ids))
        )
    ).scalars().all()

    total_sessions = (
        await db.execute(
            select(func.count(Session.id)).where(Session.teacher_id.in_(teacher_ids))
        )
    ).scalar_one() if teacher_ids else 0

    active_teachers = (
        await db.execute(
            select(func.count(distinct(Session.teacher_id))).where(
                Session.teacher_id.in_(teacher_ids)
            )
        )
    ).scalar_one() if teacher_ids else 0

    topics_count = (
        await db.execute(
            select(func.count(distinct(QuizQuestion.topic)))
            .join(Session, QuizQuestion.session_id == Session.id)
            .where(Session.teacher_id.in_(teacher_ids), QuizQuestion.topic.isnot(None))
        )
    ).scalar_one() if teacher_ids else 0

    failed_sync = (
        await db.execute(
            select(func.count(Session.id)).where(
                Session.teacher_id.in_(teacher_ids), Session.sync_status == "failed"
            )
        )
    ).scalar_one() if teacher_ids else 0

    failure_rate = round(failed_sync / total_sessions * 100, 1) if total_sessions else 0.0

    return CSRDashboard(
        program_id=program_id,
        total_schools=total_schools,
        total_sessions=total_sessions,
        active_teachers=active_teachers,
        total_topics_covered=topics_count,
        connectivity_failure_rate=failure_rate,
    )


@router.get("/dashboard/csr/{program_id}/report", response_model=CSRReport)
async def csr_report(
    program_id: uuid.UUID,
    db: DB,
    _: CurrentTeacher,
    period: int = Query(30, description="Look-back window in days"),
):
    """Full CSR/program report — all schools, sessions, teachers, concepts."""
    if period not in _VALID_PERIODS:
        period = 30
    since = _period_start(period)

    program = await db.get(Program, program_id)
    program_name = program.name if program else str(program_id)

    school_rows = (
        await db.execute(
            select(School).where(School.program_id == program_id, School.is_active.is_(True))
        )
    ).scalars().all()
    total_schools = len(school_rows)

    if not school_rows:
        return CSRReport(
            program_id=program_id,
            program_name=program_name,
            period_days=period,
            total_schools=0,
            total_sessions=0,
            sessions_this_period=0,
            total_teachers=0,
            active_teachers=0,
            teacher_adoption_rate=0.0,
            total_topics_covered=0,
            connectivity_failure_rate=0.0,
            sessions_over_time=[
                SessionTimeSeries(
                    date=(datetime.now(timezone.utc) - timedelta(days=period - 1 - i)).strftime("%Y-%m-%d"),
                    count=0,
                )
                for i in range(period)
            ],
            schools=[],
            concept_coverage=[],
        )

    school_ids = [s.id for s in school_rows]

    teacher_ids = (
        await db.execute(
            select(Teacher.id).where(Teacher.school_id.in_(school_ids))
        )
    ).scalars().all()
    total_teachers = len(teacher_ids)

    total_sessions = (
        await db.execute(
            select(func.count(Session.id)).where(Session.teacher_id.in_(teacher_ids))
        )
    ).scalar_one() if teacher_ids else 0

    sessions_this_period = (
        await db.execute(
            select(func.count(Session.id)).where(
                Session.teacher_id.in_(teacher_ids), Session.created_at >= since
            )
        )
    ).scalar_one() if teacher_ids else 0

    active_teachers = (
        await db.execute(
            select(func.count(distinct(Session.teacher_id))).where(
                Session.teacher_id.in_(teacher_ids), Session.created_at >= since
            )
        )
    ).scalar_one() if teacher_ids else 0

    adoption_rate = round(active_teachers / total_teachers * 100, 1) if total_teachers else 0.0

    topics_count = (
        await db.execute(
            select(func.count(distinct(QuizQuestion.topic)))
            .join(Session, QuizQuestion.session_id == Session.id)
            .where(
                Session.teacher_id.in_(teacher_ids),
                QuizQuestion.topic.isnot(None),
                Session.created_at >= since,
            )
        )
    ).scalar_one() if teacher_ids else 0

    failed_sync = (
        await db.execute(
            select(func.count(Session.id)).where(
                Session.teacher_id.in_(teacher_ids), Session.sync_status == "failed"
            )
        )
    ).scalar_one() if teacher_ids else 0
    failure_rate = round(failed_sync / total_sessions * 100, 1) if total_sessions else 0.0

    # Time series
    ts_rows = (
        await db.execute(
            select(Session.created_at).where(
                Session.teacher_id.in_(teacher_ids), Session.created_at >= since
            )
        )
    ).scalars().all() if teacher_ids else []
    day_counts: dict[str, int] = {}
    for dt in ts_rows:
        day = dt.strftime("%Y-%m-%d")
        day_counts[day] = day_counts.get(day, 0) + 1
    sessions_over_time = [
        SessionTimeSeries(
            date=(datetime.now(timezone.utc) - timedelta(days=period - 1 - i)).strftime("%Y-%m-%d"),
            count=day_counts.get(
                (datetime.now(timezone.utc) - timedelta(days=period - 1 - i)).strftime("%Y-%m-%d"), 0
            ),
        )
        for i in range(period)
    ]

    # Concept coverage
    concept_rows = (
        await db.execute(
            select(QuizQuestion.topic, func.count(distinct(QuizQuestion.session_id)))
            .join(Session, QuizQuestion.session_id == Session.id)
            .where(
                Session.teacher_id.in_(teacher_ids),
                QuizQuestion.topic.isnot(None),
                Session.created_at >= since,
            )
            .group_by(QuizQuestion.topic)
            .order_by(func.count(distinct(QuizQuestion.session_id)).desc())
            .limit(30)
        )
    ).all() if teacher_ids else []
    concept_coverage = [ConceptCoverageEntry(topic=r[0], session_count=r[1]) for r in concept_rows]

    # Per-school summary
    schools: list[SchoolSummary] = []
    for school in school_rows:
        school_teacher_ids = (
            await db.execute(select(Teacher.id).where(Teacher.school_id == school.id))
        ).scalars().all()

        s_total = (
            await db.execute(
                select(func.count(Session.id)).where(Session.teacher_id.in_(school_teacher_ids))
            )
        ).scalar_one() if school_teacher_ids else 0

        s_active_teachers = (
            await db.execute(
                select(func.count(distinct(Session.teacher_id))).where(
                    Session.teacher_id.in_(school_teacher_ids), Session.created_at >= since
                )
            )
        ).scalar_one() if school_teacher_ids else 0

        last_dt = (
            await db.execute(
                select(func.max(Session.created_at)).where(
                    Session.teacher_id.in_(school_teacher_ids)
                )
            )
        ).scalar_one() if school_teacher_ids else None

        s_pending = (
            await db.execute(
                select(func.count(Session.id)).where(
                    Session.teacher_id.in_(school_teacher_ids),
                    Session.sync_status.in_(["pending", "failed"]),
                )
            )
        ).scalar_one() if school_teacher_ids else 0

        s_failed = (
            await db.execute(
                select(func.count(Session.id)).where(
                    Session.teacher_id.in_(school_teacher_ids), Session.sync_status == "failed"
                )
            )
        ).scalar_one() if school_teacher_ids else 0

        schools.append(SchoolSummary(
            school_id=str(school.id),
            name=school.name,
            district=school.district,
            state=school.state,
            total_sessions=s_total,
            active_teachers=s_active_teachers,
            last_activity=last_dt.isoformat() if last_dt else None,
            pending_sync=s_pending,
            sync_health=_sync_health(s_pending, s_failed, s_total),
        ))

    schools.sort(key=lambda s: s.total_sessions, reverse=True)

    return CSRReport(
        program_id=program_id,
        program_name=program_name,
        period_days=period,
        total_schools=total_schools,
        total_sessions=total_sessions,
        sessions_this_period=sessions_this_period,
        total_teachers=total_teachers,
        active_teachers=active_teachers,
        teacher_adoption_rate=adoption_rate,
        total_topics_covered=topics_count,
        connectivity_failure_rate=failure_rate,
        sessions_over_time=sessions_over_time,
        schools=schools,
        concept_coverage=concept_coverage,
    )


@router.get("/dashboard/csr/{program_id}/schools", response_model=list[SchoolSummary])
async def csr_school_list(
    program_id: uuid.UUID,
    db: DB,
    _: CurrentTeacher,
    period: int = Query(30),
):
    """School list with stats for CSR view."""
    if period not in _VALID_PERIODS:
        period = 30
    since = _period_start(period)

    school_rows = (
        await db.execute(
            select(School).where(School.program_id == program_id, School.is_active.is_(True))
        )
    ).scalars().all()

    result: list[SchoolSummary] = []
    for school in school_rows:
        teacher_ids = (
            await db.execute(select(Teacher.id).where(Teacher.school_id == school.id))
        ).scalars().all()

        s_total = (
            await db.execute(
                select(func.count(Session.id)).where(Session.teacher_id.in_(teacher_ids))
            )
        ).scalar_one() if teacher_ids else 0

        s_active = (
            await db.execute(
                select(func.count(distinct(Session.teacher_id))).where(
                    Session.teacher_id.in_(teacher_ids), Session.created_at >= since
                )
            )
        ).scalar_one() if teacher_ids else 0

        last_dt = (
            await db.execute(
                select(func.max(Session.created_at)).where(
                    Session.teacher_id.in_(teacher_ids)
                )
            )
        ).scalar_one() if teacher_ids else None

        s_pending = (
            await db.execute(
                select(func.count(Session.id)).where(
                    Session.teacher_id.in_(teacher_ids),
                    Session.sync_status.in_(["pending", "failed"]),
                )
            )
        ).scalar_one() if teacher_ids else 0

        s_failed = (
            await db.execute(
                select(func.count(Session.id)).where(
                    Session.teacher_id.in_(teacher_ids), Session.sync_status == "failed"
                )
            )
        ).scalar_one() if teacher_ids else 0

        result.append(SchoolSummary(
            school_id=str(school.id),
            name=school.name,
            district=school.district,
            state=school.state,
            total_sessions=s_total,
            active_teachers=s_active,
            last_activity=last_dt.isoformat() if last_dt else None,
            pending_sync=s_pending,
            sync_health=_sync_health(s_pending, s_failed, s_total),
        ))

    result.sort(key=lambda s: s.total_sessions, reverse=True)
    return result
