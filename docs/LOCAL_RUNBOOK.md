# ACI — Local Development Runbook

Everything you need to run the full stack on your machine, from a clean checkout to a working session.

---

## Prerequisites

| Tool | Minimum version | Check |
|---|---|---|
| Python | 3.11 | `python3 --version` |
| Node.js | 18 (20 LTS recommended — what the Pi deploy installs) | `node --version` |
| npm | 9 | `npm --version` |
| Docker Desktop | any | `docker --version` (optional — Track B only) |

> **No Docker?** Use Track A (SQLite). Everything except Celery background workers runs without Docker.

> **AI models?** Everything above gets you the app running with cloud AI (OpenAI) or placeholder
> outputs. The on-device/offline AI models (local intent parsing, local voice-command transcription,
> wake-word detection) are a separate, entirely optional layer — see
> [AI Models (optional)](#ai-models-optional) below. Skip it unless you're specifically working on
> the voice assistant or testing offline behavior.

---

## Choose a Track

| | Track A — SQLite (fast) | Track B — PostgreSQL + Redis |
|---|---|---|
| Setup time | ~2 min | ~5 min (images must pull) |
| External services | None | Docker Desktop running |
| Celery workers | Inline (`CELERY_ALWAYS_EAGER=true`) | Full async (`CELERY_ALWAYS_EAGER=false`) |
| Production parity | Low | High |
| Best for | Day-to-day dev, all tests | Integration testing, staging parity |

---

## Track A — SQLite (zero external dependencies)

### 1. Clone and enter the repo

```bash
git clone <repo-url> ACI
cd ACI
```

### 2. Set up the Python virtual environment

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

> This installs the main dependencies plus `aiosqlite`, `pytest`, `httpx`, `ruff`, and `pytest-cov`.
> OCR and AI extras are optional — see [Optional Extras](#optional-extras) below.

### 3. Create `.env`

```bash
cp .env.example .env
```

Then open `.env` and make two changes:

```dotenv
# Uncomment the SQLite line
DATABASE_URL=sqlite+aiosqlite:///./dev.db

# Comment out the PostgreSQL line
# DATABASE_URL=postgresql+asyncpg://aci:aci@localhost:5432/aci

# Keep these as-is for local dev
CELERY_ALWAYS_EAGER=true
SKIP_AUTH=true
USE_S3=false
```

### 4. Initialize the database

```bash
make create-sqlite-db
# or directly:
DATABASE_URL=sqlite+aiosqlite:///./dev.db .venv/bin/python scripts/create_db.py
```

Expected output:
```
Target database: sqlite+aiosqlite:///./dev.db
✓ 16 tables created:
    ai_outputs
    classroom_memory
    classrooms
    ...
Done. Database is ready.
```

> **Why not `alembic upgrade head`?** The Alembic migrations use the PostgreSQL-specific `JSONB` type,
> which SQLAlchemy cannot compile for SQLite. `create_db.py` calls `Base.metadata.create_all()` instead,
> which maps those columns to `TEXT` — functionally identical for development.

### 5. Start the backend

```bash
make dev
# or directly:
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Expected output:
```
INFO:     Started server process [...]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### 6. Set up the frontend

```bash
cd ../frontend
cp .env.example .env.local       # already points to http://localhost:8000/v1
npm install
npm run dev
```

Expected output:
```
▲ Next.js 16.x.x
   - Local:        http://localhost:3000
   - Environments: .env.local
Ready in Xs
```

---

## Track B — PostgreSQL + Redis (Docker)

### Steps 1–2 same as Track A.

### 3. Start Docker services

```bash
cd ACI                           # repo root (contains docker-compose.yml)
docker compose up -d postgres redis
```

Wait for healthy status:
```bash
docker compose ps
# Both should show "(healthy)"
```

### 4. Create `.env`

```bash
cd backend
cp .env.example .env
# The default DATABASE_URL is already postgresql+asyncpg://aci:aci@localhost:5432/aci
# Leave CELERY_ALWAYS_EAGER=false to use real async workers
```

### 5. Run migrations

```bash
make migrate
# or: alembic upgrade head
```

### 6. Start backend + worker (two terminals)

```bash
# Terminal 1
make dev

# Terminal 2 (only needed when CELERY_ALWAYS_EAGER=false)
make worker
```

### 7. Frontend — same as Track A Step 6.

---

## Expected URLs

| Service | URL |
|---|---|
| Backend API | http://localhost:8000 |
| Interactive API docs (Swagger) | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
| Frontend | http://localhost:3000 |
| Health check | http://localhost:8000/v1/health |

---

## Run the Test Suite

The test suite always uses SQLite (in-memory, isolated per run) regardless of your `.env`:

```bash
cd backend
make test
```

Fast mode (stops at first failure, no coverage):
```bash
make test-fast
```

Run a single file:
```bash
DATABASE_URL="sqlite+aiosqlite:///./test.db" SKIP_AUTH=true ENVIRONMENT=test \
  .venv/bin/pytest tests/test_dashboard.py -v
```

Expected: **all tests pass, 0 failures** (466 as of 2026-09-25 — this grows over time; the exact
count isn't the point, 0 failures is).

---

## Sample End-to-End Flow (curl)

These commands walk through a complete session — create, upload frame, generate AI, fetch results.

**1. Create a session**

```bash
SESSION=$(curl -s -X POST http://localhost:8000/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "teacher_id": "00000000-0000-0000-0000-000000000001",
    "subject": "Physics",
    "grade": "Grade 10",
    "board_type": "CBSE",
    "classroom_id": null
  }' | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")
echo "Session ID: $SESSION"
```

**2. Upload a frame**

```bash
# Create a minimal test image (requires ImageMagick) or use any real JPEG
convert -size 100x100 xc:white /tmp/test-frame.jpg 2>/dev/null || \
  curl -s https://via.placeholder.com/100 -o /tmp/test-frame.jpg

curl -s -X POST http://localhost:8000/v1/sessions/$SESSION/frames \
  -F "image=@/tmp/test-frame.jpg;type=image/jpeg" \
  -F "sequence_no=1" \
  -F "local_frame_id=local-001" \
  -F 'captured_at=2026-01-01T10:00:00Z' | python3 -m json.tool
```

Expected: `{"frame_id": "...", "status": "queued", ...}`

**3. Mark session complete**

```bash
curl -s -X PATCH http://localhost:8000/v1/sessions/$SESSION \
  -H "Content-Type: application/json" \
  -d '{"status": "completed"}' | python3 -m json.tool
```

**4. Trigger AI generation**

```bash
curl -s -X POST http://localhost:8000/v1/sessions/$SESSION/generate \
  | python3 -m json.tool
```

Without an `OPENAI_API_KEY` this returns synthetic (but structurally correct) outputs immediately.
With a real key, generation runs as a BackgroundTask and completes within ~30s.

**5. Fetch outputs**

```bash
curl -s http://localhost:8000/v1/sessions/$SESSION/outputs | python3 -m json.tool
```

**6. Fetch teacher dashboard**

```bash
curl -s http://localhost:8000/v1/dashboard/teacher/00000000-0000-0000-0000-000000000001 \
  | python3 -m json.tool
```

---

## Optional Extras

### Real OCR (PaddleOCR)

```bash
pip install -e ".[ocr]"
```

This pulls `paddlepaddle`, `paddleocr`, and `Pillow`. First inference downloads ~1 GB of model weights.

To use Tesseract instead:
```bash
# macOS
brew install tesseract
pip install pytesseract

# Ubuntu / Debian
sudo apt-get install tesseract-ocr
pip install pytesseract
```

> Without either, OCR is mocked: frames are accepted and queued but `ocr_text` stays empty.

### Real AI (OpenAI GPT-4o)

Add your key to `.env`:
```dotenv
OPENAI_API_KEY=sk-...
```

Without a key, the AI service returns placeholder JSON that passes all schema validations.

### AWS S3 (frame storage)

```dotenv
USE_S3=true
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=ap-south-1
S3_BUCKET=aci-uploads
```

With `USE_S3=false` (default), frames are saved to `UPLOAD_DIR=./uploads` (created automatically on startup).

### AI Models (optional)

The app runs fully on cloud AI (OpenAI) without any of this — these three are the on-device layer
that gives the voice assistant offline/low-latency behavior. Each is controlled independently by
its own `_ENABLED` flag in `backend/.env`, and each falls back to OpenAI automatically if disabled
or unreachable. The `deploy/*-setup.sh` scripts referenced below are written for the Raspberry Pi
(they use `apt-get`/`systemctl`) — on a Mac, use the Homebrew equivalents shown here instead.

**1. Local intent parsing (Ollama + Qwen)** — turns a transcribed voice command ("start the camera")
into a structured action, instead of round-tripping to OpenAI for every short command.

```bash
brew install ollama          # macOS; see deploy/voice-assistant-setup.sh for the Pi's apt/systemd version
brew services start ollama   # or: ollama serve
ollama pull qwen2.5:3b       # ~2GB download
```

In `backend/.env`: `LOCAL_LLM_ENABLED=true` (default). Set `false` on hardware too slow to prefill the
~2.7k-token system prompt quickly — measure first with `time curl localhost:11434/api/generate ...`
before assuming it's too slow.

**2. Local voice-command transcription (whisper.cpp)** — short command utterances only, not the
long-form lecture recording (which always stays on OpenAI's cloud Whisper). See
[`deploy/whisper-setup.sh`](../deploy/whisper-setup.sh) for the full build-from-source + systemd-service
version used on the Pi; on a Mac, build whisper.cpp directly and run `whisper-server` on port 8080
(same script's commands work outside the `apt`/`systemctl` lines).

In `backend/.env`: `LOCAL_WHISPER_ENABLED=true`, `LOCAL_WHISPER_URL=http://localhost:8080`.

**3. Wake word ("Hey Drishti")** — only meaningful on a machine with a real microphone attached
(normally the Pi, not a dev laptop). Requires the `wake-word` extra:

```bash
brew install portaudio       # macOS; Pi uses: apt-get install libportaudio2 portaudio19-dev
pip install -e ".[wake-word]"
pip install --no-deps openwakeword   # see pyproject.toml's wake-word extra comment for why --no-deps
```

The trained model ships committed at `backend/models/hey_xp.onnx` — nothing to download. In
`backend/.env`: `WAKE_WORD_ENABLED=true` (defaults to `false`; leave off on a dev laptop with no
mic you want always-listening).

---

## Developer Checklist

Before your first run:

- [ ] Python 3.11+ installed
- [ ] Node 18+ installed
- [ ] `cd backend && python3 -m venv .venv && source .venv/bin/activate`
- [ ] `pip install -e ".[dev]"` completes without errors
- [ ] `cp .env.example .env` — uncomment SQLite line OR start Docker
- [ ] `make create-sqlite-db` (Track A) OR `make migrate` (Track B)
- [ ] `make dev` → see "Application startup complete"
- [ ] `curl http://localhost:8000/v1/health` returns `{"status": "ok"}`
- [ ] `cd ../frontend && npm install && npm run dev` → see "Ready in Xs"
- [ ] Open http://localhost:3000 — app loads without console errors
- [ ] `make test` (from backend/) → all tests pass, 0 failures

---

## Common Errors and Fixes

### `ModuleNotFoundError: No module named 'sqlalchemy'`

You're running `python3` instead of the venv python. Always activate the venv first:
```bash
source backend/.venv/bin/activate
```

### `UnsupportedCompilationError: can't render element of type JSONB`

You ran `alembic upgrade head` against a SQLite database. Use `make create-sqlite-db` instead.
Alembic migrations are PostgreSQL-only.

### `Connection refused` on port 5432

PostgreSQL is not running. Either start Docker (`make docker-up`) or switch to the SQLite track.

### `UPLOAD_DIR ./uploads: Permission denied`

The uploads directory could not be created. Check that the `backend/` directory is writable, or set
`UPLOAD_DIR` to an absolute path you own:
```dotenv
UPLOAD_DIR=/tmp/aci-uploads
```

### `422 Unprocessable Entity` on frame upload

Missing required fields. The frame endpoint requires all four: `sequence_no`, `local_frame_id`,
`image` (file), and `captured_at` (ISO 8601 datetime string).

### `400 SESSION_NOT_ACTIVE` on frame upload

The session status is not `active`. Sessions move to `completed` via `PATCH /sessions/{id}`.
Create a new session to upload more frames.

### Frontend shows `Failed to fetch` / API calls 404

`NEXT_PUBLIC_API_URL` in `frontend/.env.local` is not set correctly. Confirm:
```dotenv
NEXT_PUBLIC_API_URL=http://localhost:8000/v1
```
Then restart the Next.js dev server.

### `CORS error` in browser

Confirm `ENVIRONMENT=development` in `backend/.env`. When set, the backend allows all origins
(`Access-Control-Allow-Origin: *`). In non-development environments, origins must be explicitly
whitelisted.

### Tests fail with `sqlalchemy.exc.StatementError: 'str' object has no attribute 'hex'`

A direct ORM query is passing a raw UUID string to a `Uuid` column. Wrap it:
```python
import uuid
rows = await db.execute(select(Model).where(Model.id == uuid.UUID(id_str)))
```

### `celery.exceptions.NotRegistered` on AI generation

Celery workers are not running. For local dev, set `CELERY_ALWAYS_EAGER=true` in `.env` to run
tasks inline without a worker process.

---

## Stopping Everything

```bash
# Backend and frontend: Ctrl-C in their terminals

# Docker services (Track B):
cd ACI
docker compose down

# Remove Docker volumes (full reset):
docker compose down -v
```
