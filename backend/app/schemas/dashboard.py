"""
Dashboard and report response schemas.

All three roles are represented:
  - Teacher  — own sessions, topics, quizzes, sync
  - Admin    — school-wide view, teacher list
  - CSR/NGO  — program-wide view, school list
"""

from __future__ import annotations

import uuid
from typing import Any
from pydantic import BaseModel


# ── Shared building blocks ────────────────────────────────────────────────────

class SessionTimeSeries(BaseModel):
    """(date, count) pair for time-series charts."""
    date: str        # YYYY-MM-DD
    count: int


class SubjectCount(BaseModel):
    subject: str
    count: int


class BloomCount(BaseModel):
    bloom_level: str
    count: int


class SyncBreakdown(BaseModel):
    pending: int  = 0
    syncing: int  = 0
    synced:  int  = 0
    failed:  int  = 0


class TopicEntry(BaseModel):
    topic: str
    frequency: int   # how many quiz questions cover this topic


class MissingConceptItem(BaseModel):
    concept_id: str
    concept: str
    concept_type: str           # prerequisite_gap | incomplete_topic | skipped
    description: str | None
    session_id: str
    session_subject: str | None
    resolved: bool
    created_at: str             # ISO-8601


class QuizSessionSummary(BaseModel):
    session_id: str
    subject: str | None
    grade: str | None
    question_count: int
    exported_to_tiqer: int
    created_at: str


# ── Teacher dashboard / summary ───────────────────────────────────────────────

class TeacherDashboard(BaseModel):
    """Kept for backward-compat with existing GET /dashboard/teacher/{id}."""
    teacher_id: uuid.UUID
    sessions_conducted:       int
    topics_covered:           int
    ai_outputs_generated:     int
    tiqer_sessions:           int
    missing_concepts_flagged: int
    pending_sync:             int


class ClassroomMemoryResponse(BaseModel):
    teacher_id:       uuid.UUID
    last_session:     dict | None
    pending_concepts: list[str]
    suggested_next:   str | None
    quick_revision:   str | None


# ── Teacher full report ───────────────────────────────────────────────────────

class TeacherReport(BaseModel):
    """
    Full teacher report — powers the /reports page.
    All counts are scoped to the requested period unless noted as ``_total``.
    """
    teacher_id:   uuid.UUID
    period_days:  int

    # ── Summary counts ──────────────────────────────────────────────────────
    sessions_total:            int   # all-time
    sessions_this_period:      int   # within period_days
    ai_outputs_total:          int   # ready outputs, all-time
    ai_outputs_this_period:    int
    quizzes_generated:         int   # sessions that have at least 1 quiz question
    quizzes_exported_to_tiqer: int   # distinct tiqer_exported questions
    topics_count:              int   # distinct non-null topics across all quiz questions
    missing_concepts_total:    int
    missing_concepts_resolved: int
    sync_pending:              int
    sync_failed:               int
    sync_completed:            int   # synced sessions

    # ── Time series (period_days) ───────────────────────────────────────────
    sessions_over_time: list[SessionTimeSeries]

    # ── Breakdowns ──────────────────────────────────────────────────────────
    subject_breakdown:    list[SubjectCount]    # subject → session count
    topics_covered:       list[TopicEntry]      # topic → question frequency
    bloom_distribution:   list[BloomCount]      # bloom_level → question count
    sync_breakdown:       SyncBreakdown

    # ── Recent detail rows ──────────────────────────────────────────────────
    recent_missing_concepts: list[MissingConceptItem]
    quiz_sessions:           list[QuizSessionSummary]


# ── Unit View ────────────────────────────────────────────────────────────────

class UnitSummary(BaseModel):
    """One row in the units list — a subject+grade pair."""
    subject: str
    grade: str
    session_count: int
    first_date: str    # YYYY-MM-DD
    last_date: str     # YYYY-MM-DD


class UnitSessionEntry(BaseModel):
    """One session's contribution to a unit."""
    session_id: str
    date: str                        # YYYY-MM-DD
    title: str | None
    topics_covered: list[str]        # from combined_analysis.topics_spoken
    gaps: list[str]                  # from missing_concepts.pedagogical_gaps.conceptual_gaps
    suggested_next: list[str]        # from missing_concepts.suggested_next_steps


class RecurringGap(BaseModel):
    concept: str
    count: int   # how many sessions flagged this


class UnitDetail(BaseModel):
    subject: str
    grade: str
    sessions: list[UnitSessionEntry]
    recurring_gaps: list[RecurringGap]   # concepts missing in 2+ sessions, desc by count
    continue_from_here: list[str]        # suggested_next from the most recent session


# ── Admin dashboard / report ──────────────────────────────────────────────────

class AdminDashboard(BaseModel):
    """Backward-compat summary — GET /dashboard/admin/{school_id}."""
    school_id:             uuid.UUID
    total_sessions:        int
    active_teachers:       int
    total_ai_outputs:      int
    total_tiqer_exports:   int
    pending_sync_sessions: int


class TeacherUsageSummary(BaseModel):
    """Per-teacher row in admin teacher list."""
    teacher_id:        str
    name:              str
    email:             str
    session_count:     int
    ai_outputs_count:  int
    tiqer_exports:     int
    subject_count:     int        # distinct subjects taught
    last_active:       str | None # ISO-8601 or None
    sync_health:       str        # healthy | degraded | offline


class AdminReport(BaseModel):
    school_id:              uuid.UUID
    school_name:            str
    period_days:            int

    # ── Summary ──────────────────────────────────────────────────────────────
    total_sessions:         int
    sessions_this_period:   int
    total_teachers:         int
    active_teachers:        int   # ≥1 session in period
    total_ai_outputs:       int
    total_tiqer_exports:    int
    pending_sync_sessions:  int

    # ── Time series + breakdowns ─────────────────────────────────────────────
    sessions_over_time: list[SessionTimeSeries]
    subject_breakdown:  list[SubjectCount]

    # ── Teacher list ─────────────────────────────────────────────────────────
    teachers: list[TeacherUsageSummary]


# ── CSR / program dashboard / report ─────────────────────────────────────────

class CSRDashboard(BaseModel):
    """Backward-compat summary — GET /dashboard/csr/{program_id}."""
    program_id:               uuid.UUID
    total_schools:            int
    total_sessions:           int
    active_teachers:          int
    total_topics_covered:     int
    connectivity_failure_rate: float


class SchoolSummary(BaseModel):
    """Per-school row in CSR school list."""
    school_id:       str
    name:            str
    district:        str | None
    state:           str | None
    total_sessions:  int
    active_teachers: int
    last_activity:   str | None   # ISO-8601
    pending_sync:    int
    sync_health:     str          # healthy | degraded | offline | unknown


class ConceptCoverageEntry(BaseModel):
    topic: str
    session_count: int   # how many sessions touched this topic


class CSRReport(BaseModel):
    program_id:             uuid.UUID
    program_name:           str
    period_days:            int

    # ── Summary ──────────────────────────────────────────────────────────────
    total_schools:          int
    total_sessions:         int
    sessions_this_period:   int
    total_teachers:         int
    active_teachers:        int
    teacher_adoption_rate:  float  # active_teachers / total_teachers * 100
    total_topics_covered:   int    # distinct topics across all sessions in period
    connectivity_failure_rate: float  # failed_sync / total_sessions * 100

    # ── Time series ──────────────────────────────────────────────────────────
    sessions_over_time: list[SessionTimeSeries]

    # ── School list ──────────────────────────────────────────────────────────
    schools: list[SchoolSummary]

    # ── Concept coverage ─────────────────────────────────────────────────────
    concept_coverage: list[ConceptCoverageEntry]
