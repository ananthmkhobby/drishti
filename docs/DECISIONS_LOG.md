# ACI – Decisions Log

Captures key architectural and product decisions with rationale. Newest entries first.

---

## [ADR-019] UUID conversion required for direct DB queries in tests
**Date:** 2026-05-28
**Status:** Accepted

**Decision:** When querying `Uuid`-typed columns directly via SQLAlchemy in tests (not through the HTTP client), pass `uuid.UUID(str_value)` objects, not raw strings.

**Rationale:** SQLAlchemy's `Uuid` type processor calls `.hex` on the value. Strings don't have `.hex`. The HTTP client path works because FastAPI/Pydantic coerces path parameters, but direct ORM queries in test code bypass that layer.

**Pattern:**
```python
from sqlalchemy import select
import uuid
rows = await db.execute(
    select(QuizQuestion).where(QuizQuestion.session_id == uuid.UUID(session_id_str))
)
```

---

## [ADR-018] CSS-only charts for reports page (no chart library)
**Date:** 2026-05-28
**Status:** Accepted

**Decision:** All charts on the `/reports` page are built with pure CSS (`width: N%` on Tailwind divs). No recharts, chart.js, or d3 installed.

**Rationale:** The frontend has zero charting dependencies. Adding a chart library for MVP dashboards adds ~300 KB to the bundle and a new dependency surface. CSS bar charts with Tailwind are sufficient for the data density needed (≤30 bars, ≤10 categories). They're also accessible without JS and render server-side.

**Components built:**
- `SparkGrid` — daily session frequency bars, hover tooltip
- `BarRow` — horizontal bar with label + count + optional badge
- Stacked sync bar — proportional pending/syncing/synced/failed segments

**When to revisit:** If Admin/CSR reports need scatter plots, heat maps, or multi-axis charts, add Recharts at that point.

---

## [ADR-017] DB-agnostic time-series bucketing in Python
**Date:** 2026-05-28
**Status:** Accepted

**Decision:** Fetch raw `created_at` datetimes from the DB and bucket by day in Python, rather than using DB-level `DATE_TRUNC` (PostgreSQL) or `strftime` (SQLite).

**Rationale:** PostgreSQL and SQLite use incompatible date functions. Using Python-side bucketing means the same query works in both test (SQLite) and production (PostgreSQL) without dialect switching. The performance tradeoff is acceptable: period queries fetch at most `365 * max_sessions_per_day` rows, which is tiny.

**Pattern:**
```python
rows = await db.execute(select(Session.created_at).where(...))
day_counts = {}
for dt in rows.scalars():
    day = dt.strftime("%Y-%m-%d")
    day_counts[day] = day_counts.get(day, 0) + 1
series = [SessionTimeSeries(date=day, count=day_counts.get(day, 0)) for day in all_days]
```

---

## [ADR-016] Backward-compatible dashboard schema evolution
**Date:** 2026-05-28
**Status:** Accepted

**Decision:** Keep the original `TeacherDashboard`, `AdminDashboard`, `CSRDashboard` summary schemas unchanged. Add new `TeacherReport`, `AdminReport`, `CSRReport` schemas alongside them.

**Rationale:** The summary endpoints (`GET /dashboard/teacher/{id}`) are already wired into the frontend sessions page. Changing their schema would break existing consumers. New full-report endpoints (`GET /dashboard/teacher/{id}/report`) return the richer schema without affecting anything.

**Mapping:**
- `GET /dashboard/teacher/{id}` → `TeacherDashboard` (7 fields, unchanged)
- `GET /dashboard/teacher/{id}/report?period=N` → `TeacherReport` (21 fields, new)

---

## [ADR-015] TiQer preview endpoint does not write audit log
**Date:** 2026-05-28
**Status:** Accepted

**Decision:** `GET /sessions/{id}/outputs/quiz/tiqer-preview` returns the TiQer payload JSON but does NOT create a `TiQerExportLog` row. Only `POST .../export-tiqer` creates the audit record.

**Rationale:** Preview is a read operation — teachers use it to inspect the payload before exporting. Writing an audit row on preview would pollute the export log and make `quizzes_exported_to_tiqer` counts misleading. The `?download=true` flag on preview is a browser convenience (triggers `Content-Disposition: attachment`) and is also read-only.

---

## [ADR-014] `_sync_health()` thresholds
**Date:** 2026-05-28
**Status:** Accepted

**Decision:** Derive sync health string from two ratios:
- `failed / total > 0.30` → `"offline"`
- `failed / total > 0.10` OR `pending / total > 0.50` → `"degraded"`
- Otherwise → `"healthy"`
- `total == 0` → `"unknown"`

**Rationale:** These thresholds reflect operational expectations: >30% failure rate means a device or connectivity issue requiring attention; >10% failure or >50% pending means degraded but not critical. The function is pure (no DB) so it can be unit-tested in isolation.

**Note:** Thresholds are in-code constants, not config. If operational experience shows different breakpoints are needed, update `_sync_health()` in `app/routers/dashboard.py`.

---

## [ADR-013] Teacher model includes auth fields from day one
**Date:** 2026-05-27
**Status:** Accepted

**Decision:** The `teachers` table includes `password_hash`, `phone` (unique), `is_verified`, `role`, and `last_login_at` even though auth endpoints are Phase 2.

**Rationale:** Retrofitting auth columns onto a populated table requires a migration with careful backfill. Adding the columns now (nullable where they must be nullable) keeps schema changes minimal at auth launch. The columns carry zero runtime cost when unused.

**Alternatives considered:** Separate `teacher_credentials` table (extra join on every auth check), auth-only migration in Phase 2 (safe but adds schema churn on a live table).

---

## [ADR-012] Server-side sync_queue for device-level sync visibility
**Date:** 2026-05-27
**Status:** Accepted

**Decision:** Mirror the mobile `sync_queue` table on the server. Each row tracks one entity (session_meta or frame) per device, with status, retry count, last attempt, and error payload.

**Rationale:** Without server-side tracking, operations staff have no way to see which devices are stuck, how many retries have occurred, or what the error was. The server-side record also allows re-triggering uploads from the dashboard without modifying the mobile app. `device_fingerprint` is kept denormalized so rows survive device de-registration.

**Alternatives considered:** Log-only approach (no structured queryability), embedding sync status in the sessions table (one row per session, not per device-entity pair — loses per-device granularity).

---

## [ADR-011] Separate tables for experiment_suggestions and missing_concepts
**Date:** 2026-05-27
**Status:** Accepted

**Decision:** `experiment_suggestions` and `missing_concepts` are first-class tables, not JSONB arrays embedded in `ai_outputs`.

**Rationale:** The dashboard needs to filter experiments by topic/difficulty and track which missing concepts have been resolved in later sessions. JSONB unpacking in SQL is awkward and non-indexable. Separate rows also allow teacher-approval flags and cross-session resolution pointers (`resolved_in_session_id`). The tradeoff is two extra tables; acceptable given the queryability gain.

---

## [ADR-010] Celery + Redis for async AI processing
**Date:** 2026-05-27
**Status:** Accepted (Phase 2 — FastAPI BackgroundTasks used in MVP)

**Decision:** Use Celery with Redis as broker for all OCR and AI generation jobs in production.

**Rationale:** AI generation per session takes 30–90s. Synchronous API calls would timeout. Celery allows workers to process independently, retry on failure, and scale horizontally. For MVP, FastAPI `BackgroundTasks` is used as a simpler stand-in with the same interface — the job record (`jobs` table) and status polling flow are already in place, making the Celery migration surgical.

**Alternatives considered:** FastAPI BackgroundTasks (no retry, no distributed workers — used for MVP), AWS SQS (adds cloud dependency and cost).

---

## [ADR-009] SQLite + filesystem for mobile local storage
**Date:** 2026-05-27
**Status:** Accepted

**Decision:** Use SQLite (via SQLCipher for encryption) for metadata and local filesystem for image files on Android.

**Rationale:** Room (Android SQLite wrapper) is mature, offline-native, and supports complex queries. Storing images in SQLite BLOBs would balloon DB size and hurt performance. Filesystem separation keeps image management simple.

---

## [ADR-008] PaddleOCR as primary OCR engine
**Date:** 2026-05-27
**Status:** Accepted (placeholder in use for Phase 1 API development)

**Decision:** Use PaddleOCR as the primary OCR engine with Tesseract as fallback.

**Rationale:** PaddleOCR outperforms Tesseract on handwritten, low-quality, and non-standard text. Tesseract is retained as fallback and cross-validation. Currently a placeholder returns synthetic OCR text — the interface is identical to what real PaddleOCR will produce, so integration is a drop-in.

---

## [ADR-007] Time-based capture as default MVP mode
**Date:** 2026-05-27
**Status:** Accepted

**Decision:** Default capture mode for MVP is time-based (frame every 20–60s, configurable).

**Rationale:** Lowest friction for teachers. No setup, no triggers, no hardware changes. Motion-based capture requires reliable change detection. Time-based is predictable, testable, works on any Android phone.

**Trade-off:** Some redundant frames captured. Handled by multi-frame merge deduplication.

---

## [ADR-006] GPT-4o as default AI model
**Date:** 2026-05-27
**Status:** Accepted

**Decision:** Use GPT-4o for all AI generation tasks in MVP. Route simple tasks to GPT-4o-mini for cost reduction.

**Rationale:** GPT-4o provides the best quality for structured JSON output (quiz generation, bloom analysis) and long-form notes. At ~$0.035 per session, cost is acceptable for MVP volume.

---

## [ADR-005] Offline-first as a non-negotiable constraint
**Date:** 2026-05-27
**Status:** Accepted

**Decision:** The entire capture-to-local-storage flow must work without any internet. Sync to server is always deferred.

**Rationale:** Target deployments are rural Indian schools with unreliable or absent internet. This is a fundamental design constraint, not a feature.

**Consequence:** All AI processing is server-side (post-sync). Teachers see AI outputs only after sync completes.

---

## [ADR-004] Android native for mobile MVP
**Date:** 2026-05-27
**Status:** Accepted

**Decision:** Build the mobile app as Android native (Kotlin / Java).

**Rationale:** Target devices are low-end Android phones (Snapdragon 680, 4GB RAM). Android native gives full control over camera APIs, background services, and SQLite. Cross-platform frameworks add overhead and camera limitations on low-end hardware.

---

## [ADR-003] FastAPI over Django for backend
**Date:** 2026-05-27
**Status:** Accepted

**Decision:** Use FastAPI as the backend framework.

**Rationale:** FastAPI's async-native design fits the upload + queue workflow. Auto-generated OpenAPI docs reduce documentation burden. Pydantic provides built-in request validation.

---

## [ADR-002] AWS S3 for image and output storage
**Date:** 2026-05-27
**Status:** Accepted

**Decision:** Store all uploaded frames and AI-generated outputs in AWS S3 with private bucket policy.

**Rationale:** S3 is reliable, scales without ops work. `USE_S3=false` uses local filesystem for dev/test.

---

## [ADR-001] No facial recognition — ever
**Date:** 2026-05-27
**Status:** Permanent policy

**Decision:** ACI will never capture, store, or process facial data of students or teachers.

**Rationale:** Ethical requirement for a school platform. Students are minors. Government and CSR deployments have strict data governance requirements.

**Enforcement:** No face detection libraries in the pipeline. Code review must reject any PR introducing face embedding or recognition APIs.
