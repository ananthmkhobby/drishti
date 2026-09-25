# Skill: Dashboard & Reports

**Purpose:** Reference for the 9 dashboard/report endpoints, their response schemas, query patterns, and the three-role data hierarchy (Teacher → Admin → CSR).

---

## Role Hierarchy

```
CSR / NGO Program
  └── Schools  (program_id FK)
        └── Teachers  (school_id FK)
              └── Sessions  (teacher_id FK)
                    └── Frames, QuizQuestions, AIOutputs, MissingConcepts
```

---

## Endpoint Map

| Endpoint | Response Schema | Notes |
|---|---|---|
| `GET /dashboard/teacher/{id}` | `TeacherDashboard` | 7 summary counts |
| `GET /dashboard/teacher/{id}/report?period=N` | `TeacherReport` | 21 fields, time-series |
| `GET /teachers/{id}/memory` | `ClassroomMemoryResponse` | Last session + pending concepts |
| `GET /dashboard/admin/{school_id}` | `AdminDashboard` | School-wide summary |
| `GET /dashboard/admin/{school_id}/report?period=N` | `AdminReport` | Per-teacher breakdown |
| `GET /dashboard/admin/{school_id}/teachers` | `list[TeacherUsageSummary]` | Sorted by session_count desc |
| `GET /dashboard/csr/{program_id}` | `CSRDashboard` | Program-wide summary |
| `GET /dashboard/csr/{program_id}/report?period=N` | `CSRReport` | Per-school breakdown |
| `GET /dashboard/csr/{program_id}/schools?period=N` | `list[SchoolSummary]` | Sorted by total_sessions desc |

**Valid period values:** `7`, `30` (default), `90`, `365`. Any other value silently coerces to 30.

---

## TeacherReport Fields (most used)

```python
class TeacherReport(BaseModel):
    teacher_id:               uuid.UUID
    period_days:              int               # 7/30/90/365
    sessions_total:           int               # all-time
    sessions_this_period:     int
    ai_outputs_total:         int               # ready outputs, all-time
    ai_outputs_this_period:   int
    quizzes_generated:        int               # sessions with ≥1 question
    quizzes_exported_to_tiqer: int              # individual questions exported
    topics_count:             int               # distinct non-null topics
    missing_concepts_total:   int
    missing_concepts_resolved: int
    sync_pending:             int
    sync_failed:              int
    sync_completed:           int
    sessions_over_time:       list[SessionTimeSeries]   # len == period_days
    subject_breakdown:        list[SubjectCount]        # sorted by count desc
    topics_covered:           list[TopicEntry]          # top 50, sorted by freq
    bloom_distribution:       list[BloomCount]          # sorted by count desc
    sync_breakdown:           SyncBreakdown             # pending/syncing/synced/failed
    recent_missing_concepts:  list[MissingConceptItem]  # last 10 unresolved
    quiz_sessions:            list[QuizSessionSummary]  # last 20 sessions with quiz
```

---

## Time-Series Pattern

All `sessions_over_time` lists have exactly `period_days` entries, one per calendar day, with zeros for days with no sessions:

```python
# DB-agnostic — works on both SQLite (test) and PostgreSQL (prod)
rows = await db.execute(
    select(Session.created_at).where(Session.teacher_id == teacher_id, Session.created_at >= since)
)
day_counts = {}
for dt in rows.scalars():
    day = dt.strftime("%Y-%m-%d")
    day_counts[day] = day_counts.get(day, 0) + 1

series = [
    SessionTimeSeries(date=day, count=day_counts.get(day, 0))
    for i in range(period)
    for day in [(now - timedelta(days=period-1-i)).strftime("%Y-%m-%d")]
]
```

---

## Sync Health

```python
def _sync_health(pending: int, failed: int, total: int) -> str:
    if total == 0:                              return "unknown"
    if failed / total > 0.30:                  return "offline"
    if failed / total > 0.10 or \
       pending / total > 0.50:                 return "degraded"
    return "healthy"
```

Used in: `TeacherUsageSummary.sync_health`, `SchoolSummary.sync_health`.

---

## Frontend: Reports Page (`/reports`)

- **Period selector:** segmented button, changes `period` query param, triggers SWR refetch
- **SWR polling:** `refreshInterval: 60_000`, stale banner while `isValidating`
- **CSS charts (no library):**
  - `SparkGrid` — daily bars, ≤30d shows days, >30d buckets to weeks
  - `BarRow` — horizontal bar with flex layout, optional badge
  - Stacked sync bar — proportional colored segments
- **Topics expander:** shows 12 by default, "Show all N" button
- **AdminReadyPanel:** dashed card shown when no admin/CSR data, shows endpoint paths

---

## Empty / Unknown ID Handling

All three report endpoints handle missing rows gracefully:
- Unknown `school_id` (no `School` row) → `school_name` = ID string, all counts zero
- Unknown `program_id` → `program_name` = ID string, all counts zero
- School/program with no teachers → empty lists, time-series filled with zeros

This means the endpoints never return 404 — they always return a structurally valid response.

---

## Test Coverage

All 9 endpoints are covered in `tests/test_dashboard.py` (46 tests):
- Zero-count states for all three roles
- All required fields present (schema contracts)
- All period lengths (7/30/90/365)
- Sorted lists (subject_breakdown, teachers, schools)
- Bloom distribution after quiz generation
- Quiz sessions list after generation
- `_sync_health()` unit tests (8 boundary cases)
