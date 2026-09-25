# ACI – Test Plan

---

## Scope

Covers MVP (Stage 1): Mobile capture, OCR pipeline, AI generation, offline sync, REST API, Teacher Dashboard.

---

## Test Levels

### 1. Unit Tests

#### OCR Pipeline
| Test | What to Verify |
|---|---|
| Board detection | Returns bounding box on valid board image; returns null on non-board image |
| Perspective correction | Output image is rectangular, not trapezoid |
| Contrast enhancement | Mean pixel value of text region increases after CLAHE |
| OCR text extraction | Known test board image returns expected text (>75% word match) |
| Multi-frame merge | Duplicate text blocks appear once in merged output |
| Confidence routing | <0.65 confidence triggers Tesseract fallback |
| Diagram detection | Region classified as 'diagram' when text density < threshold |

#### AI Pipeline
| Test | What to Verify |
|---|---|
| Notes prompt | Output is valid markdown with at least one heading |
| Quiz generation | Returns valid JSON array; each item has type, text, correct, bloom_level |
| Bloom analysis | Returns counts for each Bloom level summing to total questions |
| Missing concept | Returns list type, not empty when OCR text clearly skips a prerequisite |
| Token truncation | Sessions with >4000 tokens of OCR text are truncated, not errored |

#### Sync Queue (Mobile SQLite)
| Test | What to Verify |
|---|---|
| Enqueue session | Row appears in sync_queue with status=pending |
| Status transition | pending → uploading → done on success |
| Retry increment | retry_count increases on 5xx response |
| Max retry | After 5 failures, status = skipped |
| Deduplication | Re-enqueuing same local_id does not create duplicate row |

#### API Layer
| Test | What to Verify |
|---|---|
| POST /sessions | Returns 201 with session_id |
| POST /sessions/{id}/frames | Returns 202, frame queued |
| GET /frames/{id}/ocr | Returns OCR result after processing |
| POST /sessions/{id}/generate | Returns 202 job_id |
| GET /sessions/{id}/outputs | Returns all output types with status |
| POST /sync/sessions | Accepts bulk offline sessions, returns upload tokens |
| Duplicate frame | Returns 409 on duplicate local_frame_id |

---

### 2. Integration Tests

#### End-to-End: Session to Outputs
```
1. Create teacher + session via API
2. Upload 3 test frames (known board images)
3. Wait for OCR processing (poll /jobs/{id})
4. Trigger AI generation
5. Assert:
   - notes output present and non-empty
   - quiz has ≥5 MCQ questions
   - bloom output has level distribution
   - missing_concepts output is non-null
```

#### Offline Sync Round-trip
```
1. Create session locally (SQLite, no server)
2. Capture 5 frames to local filesystem
3. Simulate reconnect (restore internet in test env)
4. Assert sync_queue clears, all items become 'done'
5. Assert server has session + frames in DB
6. Assert AI generation triggered post-sync
```

#### TiQer Export
```
1. Generate quiz for a session
2. Teacher edits one question (correct answer changed)
3. Export to TiQer
4. Assert tiqer_exported = true on all question rows
5. Assert TiQer mock API received correct payload
```

---

### 3. System / Acceptance Tests

#### OCR Accuracy Benchmark
- Use a corpus of 50 test board images (chalkboard, whiteboard, varying lighting)
- Ground truth text provided per image
- Acceptance: word-level accuracy ≥75% across corpus
- Failure categories logged: glare, blur, messy handwriting, partial erasure

#### Session Processing Time
- Submit a 20-frame session
- Measure time from last frame upload to all AI outputs ready
- Acceptance: <2 minutes end-to-end

#### Offline Reliability
- Simulate 10 sessions created offline over 48 hours with no internet
- Restore internet
- Acceptance: 100% of sessions sync within 5 minutes of reconnect (≥95% target)

#### Low-end Device Simulation
- Run mobile app on Android 10 device with 4GB RAM, 8MP camera
- Capture a 30-minute session (30s interval = ~60 frames)
- Acceptance: app does not crash, all frames stored locally, battery drain <15%

---

### 4. Security Tests

| Test | Expected |
|---|---|
| Access other teacher's session | 403 Forbidden |
| Upload frame to another teacher's session | 403 Forbidden |
| Invalid JWT | 401 Unauthorized |
| Expired JWT | 401 Unauthorized |
| SQL injection in session subject field | Input sanitised, no DB error |
| Oversized image upload (>10MB) | 400 Bad Request |
| Local SQLite accessible by other apps | Not accessible (app-private directory) |
| No facial recognition stored | Assert: no face embeddings in any DB table |

---

### 5. Performance Tests

| Scenario | Target |
|---|---|
| 100 concurrent frame uploads | P95 response < 3s |
| 50 concurrent AI generation jobs | All complete within 5 min |
| Dashboard API with 1000 sessions | P95 response < 500ms |
| Sync bulk upload (50 frames, 2G sim) | Completes without timeout |

---

## Test Data

| Asset | Source |
|---|---|
| Board images (chalkboard) | Curated set of 50 real classroom photos |
| Board images (whiteboard) | 20 synthetic + 10 real |
| OCR ground truth | Hand-transcribed per image |
| Curriculum topics | Physics Grade 8–10 (NCERT alignment) |
| Mock TiQer API | Local stub server |

---

## Test Environments

| Environment | Purpose |
|---|---|
| Local / Dev | Unit tests, developer iteration |
| CI (GitHub Actions) | Unit + integration on every PR |
| Staging | Acceptance + performance tests pre-release |
| Device Lab | Real Android device tests (low-end + mid-range) |

---

## CI Gates (PR must pass)

- All unit tests green
- All integration tests green
- No new linting errors
- OCR accuracy benchmark ≥75% (run nightly, not per PR)
- Coverage ≥70% on OCR and AI pipeline modules

---

## Out of Scope (MVP Test Plan)

- Diagram interpretation (Phase 3)
- Multilingual OCR
- Vision AI (GPT-4o Vision)
- RBAC testing (Phase 2)
- IP / Edge camera inputs
