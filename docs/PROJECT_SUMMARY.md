# ACI – Project Summary

**Product:** AI Chalkboard Intelligence (ACI)
**Org:** Xperimentor
**Version:** 1.00.0000.00
**Updated:** 28-May-2026
**Classification:** Internal / Engineering

---

## What It Is

ACI is an **offline-first AI classroom intelligence platform** that converts board-based teaching (chalk, marker, smart) into structured, AI-generated learning assets. It is not an OCR tool or a smartboard replacement — it is **AI infrastructure for real classrooms**.

---

## Problem It Solves

| Problem | Impact |
|---|---|
| Board content disappears after class | Teaching knowledge lost |
| Teachers recreate notes repeatedly | Burnout, time waste |
| Students miss classes | Learning gaps |
| No classroom memory across sessions | Poor continuity |
| Manual quiz creation | Teacher fatigue |
| No analytics on what was taught | Zero visibility |
| Weak internet blocks smartboards | Rural exclusion |

---

## Technology Stack

| Layer | Technology |
|---|---|
| Mobile App | Android Native (Phase 2) |
| Frontend | Next.js 15 (App Router), TypeScript, Tailwind CSS, SWR |
| Backend | FastAPI (async), SQLAlchemy (async), Alembic |
| OCR | Placeholder → PaddleOCR (primary), Tesseract (fallback) |
| AI | OpenAI GPT-4o / GPT-4o-mini (placeholder when no key) |
| Database | PostgreSQL (prod), SQLite+aiosqlite (test) |
| Object Storage | AWS S3 / local filesystem (`USE_S3=false` for dev) |
| Queue/Worker | FastAPI BackgroundTasks (MVP) → Celery + Redis (Phase 2) |
| Auth | JWT (Phase 2); `SKIP_AUTH=true` for dev/test |

---

## Implementation Status

### ✅ Backend — Fully Implemented

**Data Models (14 tables, 4 Alembic migrations):**
`teachers`, `schools`, `programs`, `classrooms`, `sessions`, `frames`, `ocr_results`,
`ai_outputs`, `quiz_questions`, `missing_concepts`, `experiment_suggestions`,
`classroom_memory`, `jobs`, `tiqer_export_log`, `sync_queue`, `devices`

**REST API (7 routers, ~30 endpoints):**

| Router | Key Endpoints |
|---|---|
| sessions | POST/GET/PATCH sessions, list with filters |
| frames | POST upload (validated), GET list, GET OCR result |
| outputs | GET outputs, GET quiz, POST generate, POST export-tiqer, GET tiqer-preview |
| jobs | GET job status |
| sync | POST device/register, POST sessions/bulk, POST frames/bulk, GET status, POST ack |
| dashboard | 9 endpoints — teacher/admin/CSR summary + full report + list |
| health | GET /health |

**Frame Upload Validation:**
- Types: JPEG and PNG only (`INVALID_IMAGE_TYPE` 400)
- Size: ≤10 MB (`IMAGE_TOO_LARGE` 400)
- Session state: active only (`SESSION_NOT_ACTIVE` 400)
- Limit: ≤200 frames/session (`FRAME_LIMIT_REACHED` 400)
- Dedup: unique `local_frame_id` per session (`DUPLICATE_FRAME` 409)
- Timestamp: ISO 8601 required (`INVALID_TIMESTAMP` 400)

**AI Pipeline (placeholder + real path):**
Generates: notes, summary, quiz (MCQ + T/F with Bloom tags), bloom distribution,
missing concepts, experiment suggestions, analogies, homework.
Falls back to placeholder JSON when `OPENAI_API_KEY` is absent.

**TiQer Export:**
Full schema-v1.0 payload builder, audit log (`tiqer_export_log`), preview endpoint,
`?download=true` triggers `Content-Disposition: attachment`, marks `tiqer_exported=True` on all questions.

**Dashboard / Reports (9 endpoints):**
- Teacher: summary widget + full report (20+ fields, time-series, bloom, subjects, topics, quiz sessions, missing concepts)
- Admin: school-level summary + full report with per-teacher usage list
- CSR: program-level summary + full report with school list + concept coverage
- All reports: period=7/30/90/365, DB-agnostic time-series (Python bucketing)
- `_sync_health()` derives healthy/degraded/offline/unknown from fail/pending ratios

**Offline Sync:**
Device registration, bulk session/frame upload, server-side sync_queue mirror,
retry with backoff, ack endpoint, sync status by device fingerprint.

### ✅ Frontend — Fully Implemented

**Pages (Next.js App Router, all under `/(dashboard)`):**

| Route | Description |
|---|---|
| `/sessions` | Session list with status badges, sync indicators |
| `/sessions/new` | Session creation form |
| `/sessions/[id]/capture` | Frame capture interface |
| `/sessions/[id]/ocr` | OCR result viewer |
| `/sessions/[id]/notes` | AI-generated notes |
| `/sessions/[id]/quiz` | Quiz question review |
| `/sessions/[id]/tiqer` | TiQer export (full form, BloomBar, QuestionRow, collapsible JSON, download) |
| `/sessions/[id]/missing-concepts` | Missing concept alerts |
| `/sessions/[id]/experiments` | Experiment suggestions |
| `/reports` | Teacher reports page |
| `/sync` | Sync status page |

**Reports Page features:**
- Period selector (7/30/90/365 days)
- SWR polling every 60s with stale-data banner
- CSS-only charts (no external chart library): `SparkGrid` daily bar chart, `BarRow` horizontal bars, stacked sync bar
- Subject breakdown, Bloom distribution, top topics (expandable), recent missing concepts, quiz sessions table
- Admin/CSR "future ready" panel showing upcoming role endpoints

**API Client (`src/lib/api.ts`):**
Full TypeScript interfaces for all 30+ response types.
All API methods typed end-to-end.

### ✅ Tests — 279 Tests, All Passing

| File | Tests | Coverage |
|---|---|---|
| test_dashboard.py | 46 | All 9 dashboard endpoints + `_sync_health()` unit tests |
| test_sync.py | 27 | Device register, bulk upload, retry, ack, status |
| test_tiqer_service.py | 63 | Payload builder, correct answers, bloom/difficulty, serialisation |
| test_ai_service.py | 41 | Parser functions, prompt builders, token truncation, fallback |
| test_image_quality.py | 24 | Type/size/state/limit/timestamp/required-field validation |
| test_outputs.py | 22 | Generation, jobs, quiz, TiQer export+preview+audit+idempotency |
| test_sessions.py | 7 | CRUD, duplicate local_id, invalid interval |
| test_frames.py | 7 | Upload, count increment, dedup 409, wrong type, list, OCR |
| test_health.py | 2 | Health endpoint |

---

## Architecture Overview

```
Android App (Phase 2)
    │ HTTPS (offline → queued)
    ▼
Next.js Frontend  ──── SWR polling ────▶  FastAPI Backend
(port 3000)                               (port 8000 / prefix /v1)
                                               │
                              ┌────────────────┼────────────────┐
                              ▼                ▼                ▼
                         PostgreSQL     AWS S3 / local    BackgroundTasks
                         (sessions,      (frame images,   (OCR + AI gen)
                          quiz, sync)     outputs)
```

**Request flow (frame upload → AI output):**
1. `POST /v1/sessions/{id}/frames` — validates, stores image, creates Frame + Job, queues OCR background task
2. Background OCR runs `ocr_service.run_placeholder_ocr()` — populates `ocr_results`
3. `POST /v1/sessions/{id}/generate` — triggers AI generation background task
4. AI service reads OCR text → calls OpenAI (or placeholder) → stores `ai_outputs` + `quiz_questions`
5. `GET /v1/sessions/{id}/outputs` — returns all output statuses and data

---

## Pending Work

### Phase 1 (near-term)
- [ ] Real PaddleOCR integration (replace placeholder)
- [ ] Celery + Redis for production async (replace `BackgroundTasks`)
- [ ] AWS S3 integration (`USE_S3=true` path)
- [ ] Mobile Android app (capture, local SQLite, sync queue)
- [ ] Auth endpoints (JWT login/register — schema already in DB)
- [ ] Role-based access control (teacher/admin/superadmin)

### Phase 2
- [ ] Admin and CSR frontend pages (backend endpoints already done)
- [ ] Classroom memory "Continue My Class" UI panel
- [ ] Push notifications (sync completion, AI ready)
- [ ] Real TiQer API integration (currently stub)
- [ ] PDF/export output generation

### Phase 3
- [ ] Vision intelligence (diagram detection, board replay)
- [ ] Multilingual OCR and AI outputs
- [ ] Student-facing app

---

## Known Issues / Constraints

| Issue | Impact | Mitigation |
|---|---|---|
| `BackgroundTasks` has no retry | OCR/AI failure is silent | Move to Celery in Phase 2 |
| SQLite FK not enforced in tests | FK violations won't be caught in CI | Run integration tests against PostgreSQL |
| `SKIP_AUTH=true` in dev | All requests bypass auth | Never deploy with this flag |
| Placeholder OCR returns lorem ipsum | AI outputs are synthetic in dev | Acceptable for Phase 1 API development |
| DB queries not scoped to auth teacher | Any teacher can query any session | Add ownership checks at auth layer (Phase 2) |
| Reports page has no Admin/CSR UI | Admin/CSR endpoints exist but no UI | AdminPanel chip shown; Phase 2 work |

---

## Dev Quick-Start

```bash
# Backend
cd backend && source .venv/bin/activate
DATABASE_URL=sqlite+aiosqlite:///./dev.db SKIP_AUTH=true uvicorn app.main:app --reload

# Frontend
cd frontend && npm run dev

# Tests (all 279)
cd backend && python -m pytest tests/ -v

# TypeScript check
cd frontend && npx tsc --noEmit
```

---

## Key Design Principles

- **Teacher-first:** assist, never audit
- **Offline-first:** teaching never stops because internet failed
- **Low-friction:** minimal behavior change for teachers
- **Classroom-realistic:** designed for messy, real-world conditions
- **Low-cost:** affordable at rural school budgets
