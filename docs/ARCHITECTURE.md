# ACI – System Architecture

---

## Layer Overview

```
┌─────────────────────────────────────────────────────────┐
│                     INPUT LAYER                         │
│  Mobile Camera | Webcam | USB Cam | Uploaded Image      │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│               IMAGE PROCESSING LAYER                    │
│  Board Detection → Perspective Correction → Glare       │
│  Removal → Contrast Enhancement → Noise Reduction       │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│                    OCR LAYER                            │
│  PaddleOCR (primary) │ Tesseract OCR (fallback)         │
│  Text Extraction + Diagram Detection + Region Merging   │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│               AI INTELLIGENCE LAYER                     │
│  Topic Extraction │ Summary │ Quiz Generation           │
│  Bloom Mapping │ Missing Concept │ Analogies            │
│  Simplified Explanation │ Experiment Suggestions        │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│                   OUTPUT LAYER                          │
│  Notes PDF │ TiQer JSON │ Visual Cards │ Reports        │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│             LOCAL STORAGE + SYNC LAYER                  │
│  SQLite (metadata) │ Filesystem (images)                │
│  Offline Queue → Auto-Sync → AWS S3 / Backend           │
└─────────────────────────────────────────────────────────┘
```

---

## Component Breakdown

### Mobile App (Android)
- Capture frames at configurable intervals (20–60s time-based for MVP)
- On-device image pre-processing via OpenCV (lightweight pass)
- SQLite for session/frame metadata
- Offline sync queue manager
- Minimal UI: Start/Stop session, sync status, output viewer

### Backend (FastAPI)
- REST API for session management, OCR trigger, AI pipeline, output delivery
- Celery workers for async OCR + AI processing
- Redis as broker and result store
- PostgreSQL for all relational data
- S3 for image and output storage

### OCR Service
- PaddleOCR as primary engine (handles handwritten, low-quality, chalk text)
- Tesseract as fallback or parallel validator
- Output: structured text blocks with bounding box metadata

### AI Service
- Calls OpenAI API (GPT-4o for text, GPT-4o Vision for Phase 3)
- Prompt templates per output type (notes, quiz, bloom, etc.)
- Model routing based on task complexity and cost budget

### Dashboard (React / Next.js)
- Teacher dashboard (session history, AI outputs, sync status)
- Admin dashboard (school-wide analytics)
- CSR/Government dashboard (program-level reporting)

---

## Capture Modes

| Mode | Description | MVP |
|---|---|---|
| Manual Snapshot | Teacher-triggered | Yes |
| Time-Based | Every 20–60s | **Default MVP** |
| Motion-Based | Detect board change | Phase 2 |
| AI Smart Capture | Detect meaningful updates | Phase 3 |

---

## Offline-First Contract

Every component in the capture-to-storage path must work without network:
1. Capture → local image file
2. OCR (on-device lite or queued for server)
3. Metadata → SQLite
4. Upload queue persists across app restarts
5. On reconnect: auto-sync in background, resume interrupted uploads

---

## Phase Expansion

| Phase | New Capability |
|---|---|
| MVP | Mobile camera, time-based capture, PaddleOCR, GPT text AI |
| Phase 2 | Webcam, USB cam, mounted classroom cam, motion capture |
| Phase 3 | GPT-4o Vision, diagram understanding, board replay |
| Future | Edge AI camera, multilingual support, IP camera |

---

## Security Boundaries

- All local storage: encrypted at rest
- All API calls: HTTPS only
- No facial recognition — ever
- No biometric data stored
- RBAC: future (Phase 2+)
- Cloud storage: AWS S3 with private bucket policy
