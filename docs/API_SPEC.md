# ACI – API Specification

Base URL: `https://api.aci.xperimentor.com/v1`
Auth: Bearer token (JWT) in `Authorization` header
Format: JSON (request + response)

---

## Sessions

### POST /sessions
Create a new classroom session.

**Request**
```json
{
  "teacher_id": "uuid",
  "classroom_id": "uuid",
  "subject": "Physics",
  "grade": "Grade 9",
  "board_type": "chalkboard",
  "capture_mode": "time_based",
  "capture_interval_sec": 30
}
```

**Response `201`**
```json
{
  "session_id": "uuid",
  "status": "active",
  "created_at": "2026-05-27T10:00:00Z"
}
```

---

### GET /sessions/{session_id}
Fetch session metadata and current status.

**Response `200`**
```json
{
  "session_id": "uuid",
  "teacher_id": "uuid",
  "subject": "Physics",
  "grade": "Grade 9",
  "status": "completed",
  "frame_count": 12,
  "sync_status": "synced",
  "created_at": "...",
  "completed_at": "..."
}
```

---

### PATCH /sessions/{session_id}
Update session (end session, update status).

**Request**
```json
{ "status": "completed" }
```

---

### GET /sessions?teacher_id=&from=&to=&limit=&offset=
List sessions with filters.

---

## Frames

### POST /sessions/{session_id}/frames
Upload a captured frame. Multipart form.

**Request** `multipart/form-data`
- `image`: image file (JPEG/PNG)
- `captured_at`: ISO timestamp
- `sequence_no`: integer
- `local_frame_id`: string (client UUID for dedup)

**Response `202`**
```json
{
  "frame_id": "uuid",
  "status": "queued",
  "message": "Frame queued for processing"
}
```

---

### GET /sessions/{session_id}/frames
List all frames for a session with processing status.

---

### GET /frames/{frame_id}/ocr
Get OCR result for a specific frame.

**Response `200`**
```json
{
  "frame_id": "uuid",
  "ocr_text": "Force = Mass × Acceleration\nNewton's Second Law...",
  "confidence": 0.82,
  "regions": [
    { "type": "text", "bbox": [x, y, w, h], "content": "..." },
    { "type": "diagram", "bbox": [x, y, w, h] }
  ],
  "engine_used": "paddleocr",
  "processed_at": "..."
}
```

---

## AI Outputs

### POST /sessions/{session_id}/generate
Trigger AI generation for a completed session.

**Request**
```json
{
  "outputs": ["notes", "quiz", "bloom", "summary", "missing_concepts", "experiments"]
}
```

**Response `202`**
```json
{
  "job_id": "uuid",
  "status": "queued",
  "estimated_sec": 90
}
```

---

### GET /sessions/{session_id}/outputs
Get all generated outputs for a session.

**Response `200`**
```json
{
  "session_id": "uuid",
  "outputs": {
    "notes": { "status": "ready", "url": "s3://...", "generated_at": "..." },
    "quiz": { "status": "ready", "data": [ ... ] },
    "bloom": { "status": "ready", "levels": { ... } },
    "summary": { "status": "ready", "text": "..." },
    "missing_concepts": { "status": "ready", "concepts": [ ... ] },
    "experiments": { "status": "ready", "suggestions": [ ... ] }
  }
}
```

---

### GET /sessions/{session_id}/outputs/quiz
Get quiz questions for TiQer export.

**Response `200`**
```json
{
  "session_id": "uuid",
  "questions": [
    {
      "id": "uuid",
      "type": "mcq",
      "text": "What is Newton's Second Law?",
      "options": ["F=ma", "F=mv", "F=mg", "F=ma²"],
      "correct": 0,
      "bloom_level": "understand",
      "topic": "Newton's Laws"
    },
    {
      "id": "uuid",
      "type": "true_false",
      "text": "Acceleration is directly proportional to force.",
      "correct": true,
      "bloom_level": "remember"
    }
  ]
}
```

---

### POST /sessions/{session_id}/outputs/quiz/export-tiqer
Export quiz to TiQer platform.

**Request**
```json
{ "tiqer_class_id": "string", "schedule_at": "2026-05-27T11:00:00Z" }
```

**Response `200`**
```json
{ "tiqer_session_id": "string", "status": "exported" }
```

---

## Classroom Memory

### GET /teachers/{teacher_id}/memory
Get AI classroom memory for a teacher (cross-session continuity).

**Response `200`**
```json
{
  "teacher_id": "uuid",
  "last_session": { "date": "...", "subject": "Physics", "topics": ["Newton's Laws"] },
  "pending_concepts": ["Friction", "Gravity"],
  "suggested_next": "Friction – Types and Applications",
  "quick_revision": "What is the SI unit of Force?"
}
```

---

## Sync

### POST /sync/sessions
Bulk sync offline sessions (called by mobile on reconnect).

**Request**
```json
{
  "device_id": "string",
  "sessions": [
    { "local_session_id": "string", "metadata": { ... }, "frame_count": 5 }
  ]
}
```

**Response `200`**
```json
{
  "accepted": ["local_session_id_1"],
  "rejected": [],
  "upload_tokens": { "local_session_id_1": "presigned_s3_url" }
}
```

---

### GET /sync/status/{device_id}
Get pending sync queue status for a device.

**Response `200`**
```json
{
  "device_id": "string",
  "pending_sessions": 2,
  "pending_frames": 18,
  "last_sync_at": "2026-05-27T08:00:00Z"
}
```

---

## Dashboard

### GET /dashboard/teacher/{teacher_id}
Teacher dashboard summary.

**Response `200`**
```json
{
  "sessions_conducted": 42,
  "topics_covered": 18,
  "ai_outputs_generated": 38,
  "tiqer_sessions": 12,
  "missing_concepts_flagged": 5,
  "pending_sync": 1
}
```

---

### GET /dashboard/admin/{school_id}
School admin dashboard summary.

---

### GET /dashboard/csr/{program_id}
CSR / Government program dashboard.

---

## Jobs

### GET /jobs/{job_id}
Poll async job status (OCR, AI generation).

**Response `200`**
```json
{
  "job_id": "uuid",
  "type": "ai_generation",
  "status": "completed",
  "progress": 100,
  "result_url": "...",
  "error": null
}
```

---

## Error Format

All errors return:
```json
{
  "error": "FRAME_NOT_FOUND",
  "message": "No frame found with the given ID.",
  "request_id": "uuid"
}
```

| HTTP Code | Meaning |
|---|---|
| 400 | Bad request / validation error |
| 401 | Missing or invalid auth token |
| 404 | Resource not found |
| 409 | Conflict (duplicate local_frame_id) |
| 422 | Unprocessable entity |
| 429 | Rate limit exceeded |
| 500 | Internal server error |
| 503 | AI service temporarily unavailable |
