# ACI – Data Model

Database: PostgreSQL (server) + SQLite (mobile/local)

---

## Entity Relationship Overview

```
Teacher ──< Session ──< Frame ──< OCRResult
                │
                └──< AIOutput
                │
                └──< QuizQuestion

School ──< Classroom ──< Session

Device ──< SyncQueue

Teacher ──< ClassroomMemory
```

---

## Tables

### teachers
```sql
id              UUID PRIMARY KEY
name            VARCHAR(255) NOT NULL
email           VARCHAR(255) UNIQUE NOT NULL
school_id       UUID REFERENCES schools(id)
role            VARCHAR(50) DEFAULT 'teacher'  -- teacher | admin | superadmin
created_at      TIMESTAMPTZ DEFAULT NOW()
updated_at      TIMESTAMPTZ
```

---

### schools
```sql
id              UUID PRIMARY KEY
name            VARCHAR(255) NOT NULL
district        VARCHAR(255)
state           VARCHAR(100)
program_id      UUID REFERENCES programs(id)  -- CSR/NGO/Govt program
created_at      TIMESTAMPTZ DEFAULT NOW()
```

---

### programs
```sql
id              UUID PRIMARY KEY
name            VARCHAR(255) NOT NULL
type            VARCHAR(50)  -- csr | ngo | government
org_name        VARCHAR(255)
created_at      TIMESTAMPTZ DEFAULT NOW()
```

---

### classrooms
```sql
id              UUID PRIMARY KEY
school_id       UUID REFERENCES schools(id)
name            VARCHAR(100)
grade           VARCHAR(50)
section         VARCHAR(20)
board_type      VARCHAR(50)  -- chalkboard | whiteboard | smartboard
created_at      TIMESTAMPTZ DEFAULT NOW()
```

---

### sessions
```sql
id              UUID PRIMARY KEY
local_session_id VARCHAR(100)          -- client-generated, for dedup
teacher_id      UUID REFERENCES teachers(id)
classroom_id    UUID REFERENCES classrooms(id)
subject         VARCHAR(100)
grade           VARCHAR(50)
board_type      VARCHAR(50)
capture_mode    VARCHAR(50)            -- time_based | manual | motion
capture_interval_sec INT DEFAULT 30
status          VARCHAR(30) DEFAULT 'active'  -- active | completed | processing | failed
frame_count     INT DEFAULT 0
sync_status     VARCHAR(30) DEFAULT 'pending' -- pending | syncing | synced | failed
started_at      TIMESTAMPTZ
completed_at    TIMESTAMPTZ
created_at      TIMESTAMPTZ DEFAULT NOW()
```

---

### frames
```sql
id              UUID PRIMARY KEY
local_frame_id  VARCHAR(100)           -- client UUID, for dedup
session_id      UUID REFERENCES sessions(id)
sequence_no     INT NOT NULL
image_path      VARCHAR(500)           -- S3 key or local path
image_size_kb   INT
captured_at     TIMESTAMPTZ
ocr_status      VARCHAR(30) DEFAULT 'pending'  -- pending | processing | done | failed
ai_status       VARCHAR(30) DEFAULT 'pending'
created_at      TIMESTAMPTZ DEFAULT NOW()

UNIQUE(session_id, local_frame_id)
UNIQUE(session_id, sequence_no)
```

---

### ocr_results
```sql
id              UUID PRIMARY KEY
frame_id        UUID REFERENCES frames(id) UNIQUE
raw_text        TEXT
structured_json JSONB   -- regions with bboxes, types, confidence
confidence      FLOAT
engine_used     VARCHAR(50)  -- paddleocr | tesseract
processing_ms   INT
created_at      TIMESTAMPTZ DEFAULT NOW()
```

`structured_json` shape:
```json
{
  "regions": [
    { "type": "text", "bbox": [x, y, w, h], "content": "...", "confidence": 0.91 },
    { "type": "diagram", "bbox": [x, y, w, h] }
  ]
}
```

---

### ai_outputs
```sql
id              UUID PRIMARY KEY
session_id      UUID REFERENCES sessions(id)
output_type     VARCHAR(50)  -- notes | summary | bloom | missing_concepts | experiments | visual_cards
content_json    JSONB
content_url     VARCHAR(500)  -- S3 key for PDF/image outputs
model_used      VARCHAR(100)
tokens_used     INT
generation_ms   INT
status          VARCHAR(30) DEFAULT 'pending'  -- pending | processing | ready | failed
created_at      TIMESTAMPTZ DEFAULT NOW()

UNIQUE(session_id, output_type)
```

---

### quiz_questions
```sql
id              UUID PRIMARY KEY
session_id      UUID REFERENCES sessions(id)
ai_output_id    UUID REFERENCES ai_outputs(id)
question_type   VARCHAR(20)   -- mcq | true_false | poll
text            TEXT NOT NULL
options         JSONB          -- array of strings (for MCQ)
correct_answer  JSONB          -- index (MCQ) or boolean (T/F)
bloom_level     VARCHAR(30)   -- remember | understand | apply | analyze | evaluate | create
topic           VARCHAR(255)
teacher_edited  BOOLEAN DEFAULT FALSE
tiqer_exported  BOOLEAN DEFAULT FALSE
created_at      TIMESTAMPTZ DEFAULT NOW()
```

---

### classroom_memory
```sql
id              UUID PRIMARY KEY
teacher_id      UUID REFERENCES teachers(id) UNIQUE
last_session_id UUID REFERENCES sessions(id)
topics_covered  JSONB   -- cumulative list of covered topics
pending_concepts JSONB  -- concepts flagged as incomplete
suggested_next  TEXT
last_updated    TIMESTAMPTZ DEFAULT NOW()
```

---

### sync_queue (local SQLite on device)
```sql
id              INTEGER PRIMARY KEY AUTOINCREMENT
entity_type     TEXT   -- session | frame
local_id        TEXT
remote_id       TEXT   -- null until server confirms
status          TEXT DEFAULT 'pending'  -- pending | uploading | done | failed
retry_count     INTEGER DEFAULT 0
last_attempt    TIMESTAMP
created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
payload         TEXT   -- JSON blob for metadata sync
```

---

### devices
```sql
id              UUID PRIMARY KEY
teacher_id      UUID REFERENCES teachers(id)
device_fingerprint VARCHAR(255) UNIQUE
platform        VARCHAR(30)   -- android | ios | web
last_seen       TIMESTAMPTZ
app_version     VARCHAR(20)
created_at      TIMESTAMPTZ DEFAULT NOW()
```

---

## Indexes

```sql
-- Hot query paths
CREATE INDEX idx_sessions_teacher ON sessions(teacher_id);
CREATE INDEX idx_sessions_classroom ON sessions(classroom_id);
CREATE INDEX idx_frames_session ON frames(session_id);
CREATE INDEX idx_ai_outputs_session ON ai_outputs(session_id);
CREATE INDEX idx_quiz_session ON quiz_questions(session_id);
CREATE INDEX idx_sessions_sync_status ON sessions(sync_status) WHERE sync_status != 'synced';
```

---

## Enums / Allowed Values

| Field | Values |
|---|---|
| `session.status` | active, completed, processing, failed |
| `session.sync_status` | pending, syncing, synced, failed |
| `frame.ocr_status` | pending, processing, done, failed |
| `ai_output.output_type` | notes, summary, bloom, missing_concepts, experiments, visual_cards |
| `quiz_question.question_type` | mcq, true_false, poll |
| `bloom_level` | remember, understand, apply, analyze, evaluate, create |
| `board_type` | chalkboard, whiteboard, smartboard |
| `capture_mode` | time_based, manual, motion, ai_smart |
