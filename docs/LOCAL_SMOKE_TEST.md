# ACI — Local Smoke Test

A manual, end-to-end test of the MVP happy path.  Run this after every clean install or
significant backend change.  Takes about 5 minutes.

All steps use `curl` against the running backend, then spot-check the frontend UI.
No mocking — this exercises the real database, real background tasks, and the real TiQer
serialisation pipeline.

---

## Prerequisites

Backend and frontend must already be running (see `LOCAL_RUNBOOK.md`):

```
Terminal A → cd backend && make dev          # http://localhost:8000
Terminal B → cd frontend && npm run dev      # http://localhost:3000
```

`SKIP_AUTH=true` must be set in `backend/.env` (default for Track A / Track B dev).

Set this once for the whole session:

```bash
export BASE=http://localhost:8000
export V1=$BASE/v1
export TEACHER_ID=00000000-0000-0000-0000-000000000001
```

---

## Test Data

Sample board images are included in `backend/tests/fixtures/`:

| File | Content | Size |
|---|---|---|
| `sample_board_physics.jpg` | Newton's Laws chalkboard | ~45 KB |
| `sample_board_math.jpg` | Quadratic equations chalkboard | ~42 KB |
| `sample_blank.jpg` | Minimal white JPEG | ~1 KB |

Regenerate them at any time:
```bash
cd backend
.venv/bin/python - << 'EOF'
import cv2, numpy as np, os

def make_board(lines, path):
    h, w = 480, 640
    img = np.full((h, w, 3), (30, 30, 30), dtype=np.uint8)
    cv2.rectangle(img, (10, 10), (w-10, h-10), (60, 60, 60), 2)
    y = 60
    for line in lines:
        display = line.lstrip("#= ").strip()
        if display:
            scale = 1.2 if line.startswith("#") else (0.8 if line.startswith("  ") else 1.0)
            thick  = 2 if not line.startswith("  ") else 1
            cv2.putText(img, display, (30, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (220,220,220), thick, cv2.LINE_AA)
        y += 44
    cv2.imwrite(path, img, [cv2.IMWRITE_JPEG_QUALITY, 90])

os.makedirs("tests/fixtures", exist_ok=True)

make_board([
    "# Newton's Laws of Motion", "",
    "1st Law: Object at rest stays at rest",
    "  (unless acted upon by a force)", "",
    "2nd Law: F = m * a",
    "  Force = Mass x Acceleration", "",
    "3rd Law: Every action has equal",
    "  and opposite reaction", "",
    "Example: F = 5 kg x 2 m/s^2 = 10 N",
], "tests/fixtures/sample_board_physics.jpg")

make_board([
    "# Quadratic Equations", "",
    "Standard form: ax^2 + bx + c = 0", "",
    "Quadratic Formula:",
    "  x = (-b +/- sqrt(b^2 - 4ac)) / 2a", "",
    "Discriminant: D = b^2 - 4ac",
    "  D > 0: two real roots",
    "  D = 0: one real root",
    "  D < 0: no real roots",
], "tests/fixtures/sample_board_math.jpg")

blank = np.full((200, 200, 3), 255, dtype=np.uint8)
cv2.imwrite("tests/fixtures/sample_blank.jpg", blank, [cv2.IMWRITE_JPEG_QUALITY, 85])
print("Fixtures created.")
EOF
```

---

## Step 0 — Verify Services Are Up

```bash
curl -s $BASE/health | python3 -m json.tool
```

**Expected response:**
```json
{
    "status": "ok",
    "service": "ACI Backend",
    "version": "0.1.0",
    "timestamp": "2026-05-28T00:55:05.358831+00:00"
}
```

```bash
curl -s $BASE/health/ready | python3 -m json.tool
```

**Expected response:**
```json
{
    "status": "ready",
    "checks": {
        "database": "ok"
    },
    "timestamp": "2026-05-28T00:55:05.411000+00:00"
}
```

**Checklist:**
- [ ] `status` is `"ok"` (liveness)
- [ ] `checks.database` is `"ok"` (readiness)
- [ ] Frontend loads at http://localhost:3000 with no console errors

---

## Step 1 — Create a Session

```bash
SESSION_RESP=$(curl -s -X POST $V1/sessions \
  -H "Content-Type: application/json" \
  -d "{
    \"teacher_id\": \"$TEACHER_ID\",
    \"subject\": \"Physics\",
    \"grade\": \"Grade 10\",
    \"board_type\": \"chalkboard\",
    \"local_session_id\": \"smoke-test-$(date +%s)\"
  }")
echo $SESSION_RESP | python3 -m json.tool
SESSION_ID=$(echo $SESSION_RESP | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")
echo "SESSION_ID=$SESSION_ID"
```

**Expected response:**
```json
{
    "session_id": "d089aec7-a7b0-4fc5-a304-42b9eeb83f3c",
    "status": "active",
    "created_at": "2026-05-28T00:55:23"
}
```

**Checklist:**
- [ ] HTTP 201
- [ ] `status` is `"active"`
- [ ] `session_id` is a UUID — copy it to `SESSION_ID`

**Frontend check:**
- Navigate to http://localhost:3000/sessions
- The new session should appear in the list with status badge "active"

---

## Step 2 — Upload a Board Image

```bash
curl -s -X POST $V1/sessions/$SESSION_ID/frames \
  -F "image=@backend/tests/fixtures/sample_board_physics.jpg;type=image/jpeg" \
  -F "sequence_no=1" \
  -F "local_frame_id=smoke-frame-001" \
  -F "captured_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  | python3 -m json.tool
```

> Run from the repo root. If inside `backend/`, change the path to `tests/fixtures/sample_board_physics.jpg`.

**Expected response:**
```json
{
    "frame_id": "6804dcb9-da3b-42fd-a28d-08fda9274a60",
    "status": "queued",
    "message": "Frame queued for processing"
}
```

Save the frame ID:
```bash
FRAME_ID=<paste frame_id from above>
```

**Checklist:**
- [ ] HTTP 202
- [ ] `status` is `"queued"`
- [ ] Frame file exists: `ls backend/uploads/` (or `/tmp/aci-uploads/` if `UPLOAD_DIR` was overridden)

**Frontend check:**
- Open http://localhost:3000/sessions/`$SESSION_ID`/capture
- The uploaded frame should appear in the capture strip

---

## Step 3 — Check OCR Result

OCR runs as a background task immediately after upload.  Wait ~1 second, then:

```bash
sleep 1
curl -s $V1/frames/$FRAME_ID/ocr | python3 -m json.tool
```

**Expected response (placeholder OCR — no engine installed):**
```json
{
    "frame_id": "6804dcb9-da3b-42fd-a28d-08fda9274a60",
    "ocr_text": "[OCR Placeholder] Real OCR not available.",
    "confidence": 0.0,
    "regions": [
        {
            "type": "heading",
            "bbox": [10, 10, 600, 50],
            "content": "Placeholder Heading",
            "confidence": 0.0
        },
        {
            "type": "text",
            "bbox": [10, 60, 600, 300],
            "content": "[OCR Placeholder] Install paddlepaddle + paddleocr (or pytesseract) and set SKIP_AUTH=false to enable real OCR.",
            "confidence": 0.0
        }
    ],
    "engine_used": "placeholder",
    "processed_at": "2026-05-28T00:55:29"
}
```

**Expected response (real OCR — PaddleOCR or Tesseract installed):**
```json
{
    "frame_id": "6804dcb9-da3b-42fd-a28d-08fda9274a60",
    "ocr_text": "Newton's Laws of Motion\n1st Law: Object at rest stays at rest...",
    "confidence": 0.87,
    "regions": [
        {
            "type": "text",
            "bbox": [30, 16, 580, 60],
            "content": "Newton's Laws of Motion",
            "confidence": 0.95
        }
    ],
    "engine_used": "paddleocr",
    "processed_at": "2026-05-28T00:55:29"
}
```

**Checklist:**
- [ ] HTTP 200 (not 404 `OCR_NOT_READY` — wait longer if still queued)
- [ ] `engine_used` is `"placeholder"` (no OCR extras) or `"paddleocr"` / `"tesseract"`
- [ ] `frame.ocr_status` is `"done"` — verify with: `curl -s $V1/sessions/$SESSION_ID/frames | python3 -m json.tool`

**Frontend check:**
- Open http://localhost:3000/sessions/`$SESSION_ID`/ocr
- Frame thumbnail and OCR text block should be visible

---

## Step 4 — Complete the Session

Sessions must be marked `completed` before AI generation.

```bash
curl -s -X PATCH $V1/sessions/$SESSION_ID \
  -H "Content-Type: application/json" \
  -d '{"status": "completed"}' | python3 -m json.tool
```

**Expected response:**
```json
{
    "session_id": "d089aec7-a7b0-4fc5-a304-42b9eeb83f3c",
    "teacher_id": "00000000-0000-0000-0000-000000000001",
    "classroom_id": null,
    "subject": "Physics",
    "grade": "Grade 10",
    "board_type": "chalkboard",
    "capture_mode": "time_based",
    "capture_interval_sec": 30,
    "status": "completed",
    "frame_count": 1,
    "sync_status": "pending",
    "started_at": "2026-05-28T00:55:23.440939",
    "completed_at": "2026-05-28T00:55:40.816163",
    "created_at": "2026-05-28T00:55:23"
}
```

**Checklist:**
- [ ] HTTP 200
- [ ] `status` is `"completed"`
- [ ] `completed_at` is now set (non-null)

---

## Step 5 — Trigger AI Generation

```bash
GEN_RESP=$(curl -s -X POST $V1/sessions/$SESSION_ID/generate \
  -H "Content-Type: application/json" \
  -d '{"outputs": ["notes", "summary", "quiz", "bloom"]}')
echo $GEN_RESP | python3 -m json.tool
JOB_ID=$(echo $GEN_RESP | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
echo "JOB_ID=$JOB_ID"
```

**Expected response:**
```json
{
    "job_id": "f805fe46-483a-4195-9379-54540d813ffa",
    "status": "queued",
    "estimated_sec": 90
}
```

> Omit the `outputs` body to generate all 8 types (notes, summary, quiz, bloom,
> missing_concepts, experiments, homework, analogies).

**Without `OPENAI_API_KEY`:** generation uses placeholder outputs and completes in < 1s.
**With `OPENAI_API_KEY`:** generation calls GPT-4o/mini and may take 15–60 seconds.

Poll the job until it completes:

```bash
# Poll once per second until status != "queued" / "processing"
for i in $(seq 1 30); do
  STATUS=$(curl -s $V1/jobs/$JOB_ID | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['status'])")
  echo "[$i] job status: $STATUS"
  [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ] && break
  sleep 1
done
curl -s $V1/jobs/$JOB_ID | python3 -m json.tool
```

**Expected job response when done:**
```json
{
    "job_id": "f805fe46-483a-4195-9379-54540d813ffa",
    "type": "ai_generation",
    "status": "completed",
    "progress": 100,
    "result_url": null,
    "error": null,
    "created_at": "2026-05-28T00:55:46",
    "updated_at": "2026-05-28T00:55:46"
}
```

**Checklist:**
- [ ] HTTP 202 on trigger
- [ ] Job reaches `status: "completed"` (not `"failed"`)
- [ ] `progress` is `100`
- [ ] `error` is `null`

---

## Step 6 — View AI Notes and Summary

```bash
curl -s $V1/sessions/$SESSION_ID/outputs | python3 -m json.tool
```

**Expected response (placeholder mode):**
```json
{
    "session_id": "d089aec7-a7b0-4fc5-a304-42b9eeb83f3c",
    "outputs": {
        "notes": {
            "status": "ready",
            "url": null,
            "generated_at": "2026-05-28T00:55:46",
            "data": {
                "markdown": "# Placeholder Notes\n\n## Topic\nBoard content will appear here after OCR + AI processing.\n\n## Key Concepts\n- Concept 1\n- Concept 2\n\n## Formulas\n- Formula = Placeholder\n",
                "metadata": {"placeholder": true}
            }
        },
        "summary": {
            "status": "ready",
            "url": null,
            "generated_at": "2026-05-28T00:55:46",
            "data": {
                "text": "This is a placeholder class summary. After real OCR and AI processing, this will contain a 3–5 sentence recap of what was taught on the board today.",
                "metadata": {"placeholder": true}
            }
        },
        "quiz": {
            "status": "ready",
            "url": null,
            "generated_at": "2026-05-28T00:55:46",
            "data": { "questions": [...], "metadata": {"placeholder": true} }
        },
        "bloom": {
            "status": "ready",
            "url": null,
            "generated_at": "2026-05-28T00:55:46",
            "data": {
                "counts": {
                    "remember": 3, "understand": 2, "apply": 1,
                    "analyze": 0, "evaluate": 0, "create": 0
                },
                "lower_order_dominant": true,
                "suggestions": ["Placeholder higher-order question 1", "Placeholder higher-order question 2"],
                "metadata": {"placeholder": true}
            }
        }
    }
}
```

**Checklist:**
- [ ] All requested output types appear in `outputs` dict
- [ ] Each output's `status` is `"ready"` (not `"pending"` or `"failed"`)
- [ ] `notes.data.markdown` starts with `#` (valid markdown)
- [ ] `summary.data.text` is a non-empty string
- [ ] `bloom.data.counts` has all 6 Bloom levels as keys

**Frontend check:**
- http://localhost:3000/sessions/`$SESSION_ID`/notes — rendered markdown notes
- The page should show the notes text and summary card

---

## Step 7 — View Quiz Questions

```bash
curl -s $V1/sessions/$SESSION_ID/outputs/quiz | python3 -m json.tool
```

**Expected response:**
```json
{
    "session_id": "d089aec7-a7b0-4fc5-a304-42b9eeb83f3c",
    "questions": [
        {
            "id": "cee92f87-b249-4089-97e8-fb2cb8869bda",
            "type": "mcq",
            "text": "Placeholder MCQ — What is the main concept taught today?",
            "options": ["Option A", "Option B", "Option C", "Option D"],
            "correct": 0,
            "bloom_level": "remember",
            "topic": "Placeholder Topic",
            "skill_tag": "recall",
            "teacher_edited": false
        },
        {
            "id": "429ed6ae-ae74-4d3a-b3c6-f39e965da4e8",
            "type": "mcq",
            "text": "Placeholder MCQ — Which formula applies here?",
            "options": ["F = ma", "E = mc²", "V = IR", "P = IV"],
            "correct": 0,
            "bloom_level": "understand",
            "topic": "Placeholder Topic",
            "skill_tag": "identification",
            "teacher_edited": false
        },
        {
            "id": "995f9df9-ffe1-4b71-990f-261f3103a32d",
            "type": "true_false",
            "text": "Placeholder T/F — This is a placeholder question.",
            "options": null,
            "correct": true,
            "bloom_level": "remember",
            "topic": "Placeholder Topic",
            "skill_tag": "recall",
            "teacher_edited": false
        }
    ]
}
```

**Checklist:**
- [ ] At least one question returned (3 in placeholder mode)
- [ ] MCQ questions have `options` (4 strings) and `correct` as an integer (0–3)
- [ ] T/F questions have `options: null` and `correct` as a boolean
- [ ] Every question has `bloom_level` and `topic`

**Frontend check:**
- http://localhost:3000/sessions/`$SESSION_ID`/quiz
- Questions displayed with Bloom taxonomy badges, interactive answer selection

---

## Step 8 — View Dashboard

```bash
curl -s $V1/dashboard/teacher/$TEACHER_ID | python3 -m json.tool
```

**Expected response (after one completed session with 4 AI outputs):**
```json
{
    "teacher_id": "00000000-0000-0000-0000-000000000001",
    "sessions_conducted": 1,
    "topics_covered": 1,
    "ai_outputs_generated": 4,
    "tiqer_sessions": 0,
    "missing_concepts_flagged": 0,
    "pending_sync": 1
}
```

Fetch the full 7-day report:
```bash
curl -s "$V1/dashboard/teacher/$TEACHER_ID/report?period=7" | python3 -m json.tool
```

**Expected report fields (key ones):**
```json
{
    "teacher_id": "00000000-0000-0000-0000-000000000001",
    "period_days": 7,
    "sessions_total": 1,
    "sessions_this_period": 1,
    "ai_outputs_total": 4,
    "quizzes_generated": 1,
    "quizzes_exported_to_tiqer": 0,
    "sessions_over_time": [
        {"date": "2026-05-22", "count": 0},
        {"date": "2026-05-23", "count": 0},
        {"date": "2026-05-24", "count": 0},
        {"date": "2026-05-25", "count": 0},
        {"date": "2026-05-26", "count": 0},
        {"date": "2026-05-27", "count": 0},
        {"date": "2026-05-28", "count": 1}
    ],
    "subject_breakdown": [{"subject": "Physics", "count": 1}],
    "bloom_distribution": [
        {"bloom_level": "remember", "count": 2},
        {"bloom_level": "understand", "count": 1}
    ]
}
```

**Checklist:**
- [ ] `sessions_conducted` ≥ 1
- [ ] `ai_outputs_generated` ≥ 4 (one per requested output type)
- [ ] `sessions_over_time` has exactly 7 entries (one per day)
- [ ] Today's date has `count` ≥ 1 in `sessions_over_time`

**Frontend check:**
- http://localhost:3000/reports
- Summary cards show correct session and output counts
- SparkGrid chart shows activity for today

---

## Step 9 — Export to TiQer

```bash
curl -s -X POST $V1/sessions/$SESSION_ID/outputs/quiz/export-tiqer \
  -H "Content-Type: application/json" \
  -d '{"tiqer_class_id": "SMOKE-CLASS-001"}' | python3 -m json.tool
```

**Expected response:**
```json
{
    "tiqer_session_id": "TQR-SMOKE-CLASS-001-DB059728",
    "status": "exported",
    "question_count": 3,
    "exported_at": "2026-05-28T00:56:06.622250Z",
    "payload": {
        "export_id": "db059728-5a06-4f69-a615-7fe29ca496e2",
        "schema_version": "1.0",
        "tiqer_class_id": "SMOKE-CLASS-001",
        "session_id": "d089aec7-a7b0-4fc5-a304-42b9eeb83f3c",
        "exported_at": "2026-05-28T00:56:06.622250Z",
        "teacher_id": "00000000-0000-0000-0000-000000000001",
        "subject": "Physics",
        "grade": "Grade 10",
        "question_count": 3,
        "questions": [
            {
                "question_id": "cee92f87-b249-4089-97e8-fb2cb8869bda",
                "sequence": 1,
                "type": "mcq",
                "text": "Placeholder MCQ — What is the main concept taught today?",
                "options": [
                    {"key": "A", "text": "Option A"},
                    {"key": "B", "text": "Option B"},
                    {"key": "C", "text": "Option C"},
                    {"key": "D", "text": "Option D"}
                ],
                "correct_answer": "A",
                "bloom_level": "remember",
                "skill_tag": "recall",
                "topic": "Placeholder Topic",
                "grade": "Grade 10",
                "subject": "Physics",
                "difficulty": "easy"
            }
        ],
        "metadata": {
            "generated_by": "ACI – AI Chalkboard Intelligence",
            "aci_version": "1.0.0",
            "bloom_distribution": {
                "remember": 2, "understand": 1, "apply": 0,
                "analyze": 0, "evaluate": 0, "create": 0
            },
            "mcq_count": 2,
            "true_false_count": 1
        }
    }
}
```

Then preview without writing an audit log:
```bash
curl -s "$V1/sessions/$SESSION_ID/outputs/quiz/tiqer-preview?tiqer_class_id=PREVIEW" \
  | python3 -m json.tool | head -12
```

Download the JSON file (browser):
```
http://localhost:8000/v1/sessions/$SESSION_ID/outputs/quiz/tiqer-preview?download=true
```

**Checklist:**
- [ ] HTTP 200 on export
- [ ] `status` is `"exported"`
- [ ] `question_count` matches the number of questions from Step 7
- [ ] `schema_version` is `"1.0"`
- [ ] `tiqer_session_id` starts with `"TQR-"`
- [ ] MCQ questions have `options` array with keys `A`/`B`/`C`/`D`
- [ ] T/F questions have `options: null` and `correct_answer` is `"true"` or `"false"`
- [ ] `difficulty` is `"easy"` / `"medium"` / `"hard"` (derived from Bloom level)
- [ ] Dashboard now shows `tiqer_sessions` > 0:

```bash
curl -s $V1/dashboard/teacher/$TEACHER_ID \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('tiqer_sessions:', d['tiqer_sessions'])"
```

**Frontend check:**
- http://localhost:3000/sessions/`$SESSION_ID`/tiqer
- Export button, class ID input, and download link visible

---

## Full One-Shot Script

Paste this entire block to run all 9 steps automatically.
Requires `backend/` as the working directory.

```bash
#!/usr/bin/env bash
set -euo pipefail

BASE=http://localhost:8000
V1=$BASE/v1
TEACHER_ID=00000000-0000-0000-0000-000000000001
FIXTURE=tests/fixtures/sample_board_physics.jpg

echo "── Step 0: Health ──────────────────────────────"
curl -sf $BASE/health | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['status']=='ok', d"
curl -sf $BASE/health/ready | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['checks']['database']=='ok', d"
echo "OK"

echo "── Step 1: Create Session ──────────────────────"
SESSION_RESP=$(curl -sf -X POST $V1/sessions \
  -H "Content-Type: application/json" \
  -d "{\"teacher_id\":\"$TEACHER_ID\",\"subject\":\"Physics\",\"grade\":\"Grade 10\",\"board_type\":\"chalkboard\",\"local_session_id\":\"smoke-$(date +%s)\"}")
SESSION_ID=$(echo $SESSION_RESP | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")
echo "Session: $SESSION_ID"

echo "── Step 2: Upload Frame ────────────────────────"
FRAME_RESP=$(curl -sf -X POST $V1/sessions/$SESSION_ID/frames \
  -F "image=@$FIXTURE;type=image/jpeg" \
  -F "sequence_no=1" \
  -F "local_frame_id=smoke-frame-001" \
  -F "captured_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)")
FRAME_ID=$(echo $FRAME_RESP | python3 -c "import sys,json; print(json.load(sys.stdin)['frame_id'])")
echo "Frame: $FRAME_ID"

echo "── Step 3: Wait for OCR ────────────────────────"
sleep 2
OCR_STATUS=$(curl -sf $V1/frames/$FRAME_ID/ocr | python3 -c "import sys,json; print(json.load(sys.stdin)['engine_used'])")
echo "OCR engine: $OCR_STATUS"

echo "── Step 4: Complete Session ────────────────────"
curl -sf -X PATCH $V1/sessions/$SESSION_ID \
  -H "Content-Type: application/json" \
  -d '{"status":"completed"}' > /dev/null
echo "Session completed"

echo "── Step 5: Trigger Generation ──────────────────"
GEN_RESP=$(curl -sf -X POST $V1/sessions/$SESSION_ID/generate \
  -H "Content-Type: application/json" \
  -d '{"outputs":["notes","summary","quiz","bloom"]}')
JOB_ID=$(echo $GEN_RESP | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
echo "Job: $JOB_ID"

echo "── Step 5b: Wait for Job ───────────────────────"
for i in $(seq 1 30); do
  JOB_STATUS=$(curl -sf $V1/jobs/$JOB_ID | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
  echo "  [$i] $JOB_STATUS"
  [ "$JOB_STATUS" = "completed" ] && break
  [ "$JOB_STATUS" = "failed" ] && echo "FAIL: job failed" && exit 1
  sleep 1
done

echo "── Step 6: Check Outputs ───────────────────────"
READY=$(curl -sf $V1/sessions/$SESSION_ID/outputs \
  | python3 -c "import sys,json; o=json.load(sys.stdin)['outputs']; print(','.join(k for k,v in o.items() if v['status']=='ready'))")
echo "Ready outputs: $READY"

echo "── Step 7: Check Quiz ──────────────────────────"
Q_COUNT=$(curl -sf $V1/sessions/$SESSION_ID/outputs/quiz \
  | python3 -c "import sys,json; print(len(json.load(sys.stdin)['questions']))")
echo "Quiz questions: $Q_COUNT"

echo "── Step 8: Dashboard ───────────────────────────"
curl -sf $V1/dashboard/teacher/$TEACHER_ID \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"Sessions={d['sessions_conducted']} Outputs={d['ai_outputs_generated']}\")"

echo "── Step 9: TiQer Export ────────────────────────"
TIQER_RESP=$(curl -sf -X POST $V1/sessions/$SESSION_ID/outputs/quiz/export-tiqer \
  -H "Content-Type: application/json" \
  -d '{"tiqer_class_id":"SMOKE-CLASS-001"}')
TIQER_STATUS=$(echo $TIQER_RESP | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
echo "TiQer status: $TIQER_STATUS"

echo ""
echo "SMOKE TEST PASSED"
```

---

## Expected Error Responses

When something goes wrong, the backend returns consistent JSON with `error` (machine code) and
`message` (human-readable) fields.

### Session not found

```bash
curl -s $V1/sessions/00000000-dead-dead-dead-000000000000 | python3 -m json.tool
```
```json
{
    "error": "SESSION_NOT_FOUND",
    "message": "Session 00000000-dead-dead-dead-000000000000 not found",
    "request_id": "d662062e-3e78-47cd-b79e-cd9511eae528"
}
```
HTTP 404.

### Quiz not ready (generation not triggered yet)

```bash
curl -s $V1/sessions/$SESSION_ID/outputs/quiz | python3 -m json.tool
```
```json
{
    "error": "QUIZ_NOT_READY",
    "message": "No quiz questions found — trigger generation first",
    "request_id": "0b91f17f-3f7d-4d42-9b11-84db0c6dcd50"
}
```
HTTP 404. Fix: run Step 5 first.

### Upload to completed session

```bash
curl -s -X POST $V1/sessions/$SESSION_ID/frames \
  -F "image=@backend/tests/fixtures/sample_blank.jpg;type=image/jpeg" \
  -F "sequence_no=2" -F "local_frame_id=late" \
  -F "captured_at=2026-01-01T10:00:00Z" | python3 -m json.tool
```
```json
{
    "error": "SESSION_NOT_ACTIVE",
    "message": "Can only upload frames to an active session",
    "request_id": "..."
}
```
HTTP 400.

### Wrong image type

```bash
curl -s -X POST $V1/sessions/NEW_SESSION_ID/frames \
  -F "image=@README.md;type=application/pdf" \
  -F "sequence_no=1" -F "local_frame_id=bad" \
  -F "captured_at=2026-01-01T10:00:00Z" | python3 -m json.tool
```
```json
{
    "error": "INVALID_IMAGE_TYPE",
    "message": "Only JPEG and PNG images are accepted",
    "request_id": "..."
}
```
HTTP 400.

### Duplicate frame

Re-uploading a frame with the same `local_frame_id`:
```json
{
    "error": "DUPLICATE_FRAME",
    "message": "A frame with this local_frame_id already exists for this session",
    "request_id": "..."
}
```
HTTP 409.

### Validation error (missing field)

```bash
curl -s -X POST $V1/sessions \
  -H "Content-Type: application/json" \
  -d '{"subject": "Physics"}' | python3 -m json.tool
```
```json
{
    "error": "VALIDATION_ERROR",
    "message": "teacher_id: Field required",
    "request_id": "..."
}
```
HTTP 422.

---

## Troubleshooting

### `curl: (7) Failed to connect`

Backend is not running. Check Terminal A:
```bash
# Should show uvicorn PID
lsof -i :8000
# Restart:
cd backend && make dev
```

### `404 Not Found` on `/v1/health`

The health endpoint has no `/v1` prefix (it's mounted at root). Use:
```bash
curl $BASE/health        # correct
curl $BASE/v1/health     # wrong — returns 404
```

### OCR always returns `"engine_used": "placeholder"`

Expected when OCR extras are not installed. To enable real OCR:
```bash
cd backend
pip install -e ".[ocr]"     # downloads ~1 GB models on first run
```
Then restart the backend.

### `400 OPENAI_API_KEY not set` or `AI generation returns placeholder`

AI generation falls back to placeholder when `OPENAI_API_KEY` is absent (by design).
Outputs will have `"metadata": {"placeholder": true}`.  Add your key to `backend/.env`:
```dotenv
OPENAI_API_KEY=sk-...
```
Restart the backend — no DB migration needed.

### Job stays in `"queued"` or `"processing"` forever

With `CELERY_ALWAYS_EAGER=true` (Track A), jobs complete inline before the response returns.
If a job is stuck, a background task error was swallowed silently. Check the backend log in
Terminal A for traceback lines. Common causes:
- `DATABASE_URL` mismatch between the main process and the background task (both must use the same `.env`)
- Import error in `ai_service.py` — run `make test-fast` to surface it

### `422 Unprocessable Entity` on frame upload

All four fields are required: `image` (file), `sequence_no` (integer), `local_frame_id`
(string), `captured_at` (ISO 8601 string).  The `device_fingerprint` field is optional.

### Frontend shows blank page / `TypeError: fetch failed`

1. Confirm `frontend/.env.local` has `NEXT_PUBLIC_API_URL=http://localhost:8000/v1`
2. Confirm the backend is running and CORS is enabled (`ENVIRONMENT=development` in `.env`)
3. Hard-refresh the browser (Cmd+Shift+R) after changing `.env.local`

### `409 DUPLICATE_SESSION`

You ran the smoke test twice with the same `local_session_id`. The timestamp suffix in the
one-shot script (`smoke-$(date +%s)`) prevents this — use the script or generate a fresh ID:
```bash
SESSION_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
```

### TiQer export returns `404 QUIZ_NOT_READY`

Generation was not triggered (Step 5), or it failed (check job status). Re-run from Step 5.

---

## Smoke Test Checklist (printable)

| Step | Action | Expected | Pass |
|---|---|---|---|
| 0a | `GET /health` | `status: ok` | ☐ |
| 0b | `GET /health/ready` | `checks.database: ok` | ☐ |
| 0c | Open http://localhost:3000 | No console errors | ☐ |
| 1 | `POST /sessions` | 201, `status: active` | ☐ |
| 2 | `POST /sessions/{id}/frames` | 202, `status: queued` | ☐ |
| 3 | `GET /frames/{id}/ocr` | 200, `engine_used` set | ☐ |
| 4 | `PATCH /sessions/{id}` → completed | 200, `status: completed` | ☐ |
| 5 | `POST /sessions/{id}/generate` | 202, `job_id` returned | ☐ |
| 5b | `GET /jobs/{id}` poll | `status: completed` | ☐ |
| 6 | `GET /sessions/{id}/outputs` | notes + summary `status: ready` | ☐ |
| 7 | `GET /sessions/{id}/outputs/quiz` | ≥ 1 question returned | ☐ |
| 8a | `GET /dashboard/teacher/{id}` | `sessions_conducted` ≥ 1 | ☐ |
| 8b | `GET /dashboard/teacher/{id}/report?period=7` | `sessions_over_time` has 7 entries | ☐ |
| 9a | `POST /sessions/{id}/outputs/quiz/export-tiqer` | `status: exported` | ☐ |
| 9b | `GET /sessions/{id}/outputs/quiz/tiqer-preview` | `schema_version: "1.0"` | ☐ |
| 9c | Dashboard `tiqer_sessions` | > 0 after export | ☐ |
