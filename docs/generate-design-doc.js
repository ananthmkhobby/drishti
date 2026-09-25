"use strict";
const fs = require("fs");
const path = require("path");

const DOCX_PATH = "/opt/homebrew/lib/node_modules/docx";
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, VerticalAlign, PageNumber, PageBreak, LevelFormat,
  ExternalHyperlink, TableOfContents,
} = require(DOCX_PATH);

// ─── Colour palette ─────────────────────────────────────────────────────────
const C = {
  indigo:    "4F46E5",
  indigoDk:  "3730A3",
  indigoLt:  "EEF2FF",
  green:     "15803D",
  greenLt:   "F0FDF4",
  amber:     "92400E",
  amberLt:   "FFFBEB",
  rose:      "9F1239",
  roseLt:    "FFF1F2",
  slate:     "475569",
  slateLt:   "F8FAFC",
  slate100:  "F1F5F9",
  slate200:  "E2E8F0",
  slate700:  "334155",
  white:     "FFFFFF",
  black:     "000000",
};

// ─── Shared border ───────────────────────────────────────────────────────────
const noBorder = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const thinBorder = { style: BorderStyle.SINGLE, size: 4, color: C.slate200 };

// ─── Helpers ─────────────────────────────────────────────────────────────────

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 120 },
    children: [new TextRun({ text, bold: true, size: 36, color: C.indigoDk, font: "Calibri" })],
  });
}

function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 280, after: 80 },
    children: [new TextRun({ text, bold: true, size: 28, color: C.indigo, font: "Calibri" })],
  });
}

function h3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 200, after: 60 },
    children: [new TextRun({ text, bold: true, size: 24, color: C.slate700, font: "Calibri" })],
  });
}

function h4(text) {
  return new Paragraph({
    spacing: { before: 160, after: 40 },
    children: [new TextRun({ text, bold: true, size: 22, color: C.slate700, font: "Calibri", underline: {} })],
  });
}

function para(runs, spacing = {}) {
  const children = typeof runs === "string"
    ? [new TextRun({ text: runs, size: 22, color: C.slate, font: "Calibri" })]
    : runs;
  return new Paragraph({ children, spacing: { before: 60, after: 60, ...spacing } });
}

function bold(text, color = C.slate700) {
  return new TextRun({ text, bold: true, size: 22, color, font: "Calibri" });
}

function run(text, opts = {}) {
  return new TextRun({ text, size: 22, color: C.slate, font: "Calibri", ...opts });
}

function code(text) {
  return new TextRun({ text, font: "Courier New", size: 18, color: "1E40AF", highlight: "cyan" });
}

function bullet(text, level = 0, numbering = null) {
  const indent = level === 0 ? { left: 720, hanging: 360 } : { left: 1080, hanging: 360 };
  return new Paragraph({
    numbering: numbering ? { reference: "bullets", level } : { reference: "bullets", level },
    indent,
    spacing: { before: 30, after: 30 },
    children: typeof text === "string"
      ? [new TextRun({ text, size: 22, color: C.slate, font: "Calibri" })]
      : text,
  });
}

function bullet2(text) { return bullet(text, 1); }

function numbered(text, level = 0) {
  return new Paragraph({
    numbering: { reference: "numbers", level },
    indent: { left: 720, hanging: 360 },
    spacing: { before: 30, after: 30 },
    children: typeof text === "string"
      ? [new TextRun({ text, size: 22, color: C.slate, font: "Calibri" })]
      : text,
  });
}

function divider() {
  return new Paragraph({
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: C.slate200, space: 1 } },
    spacing: { before: 160, after: 160 },
    children: [],
  });
}

function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}

function spacer(before = 80) {
  return new Paragraph({ spacing: { before, after: 0 }, children: [] });
}

// Coloured callout box (single-cell table)
function callout(title, text, bg = C.indigoLt, border = C.indigo) {
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [9360],
    rows: [new TableRow({
      children: [new TableCell({
        borders: { top: { style: BorderStyle.SINGLE, size: 12, color: border },
                   bottom: thinBorder, left: thinBorder, right: thinBorder },
        shading: { fill: bg, type: ShadingType.CLEAR },
        margins: { top: 120, bottom: 120, left: 160, right: 160 },
        width: { size: 9360, type: WidthType.DXA },
        children: [
          ...(title ? [new Paragraph({ spacing: { before: 0, after: 40 },
            children: [new TextRun({ text: title, bold: true, size: 22, color: border, font: "Calibri" })] })] : []),
          new Paragraph({ spacing: { before: 0, after: 0 },
            children: typeof text === "string"
              ? [new TextRun({ text, size: 21, color: C.slate700, font: "Calibri" })]
              : text }),
        ],
      })],
    })],
  });
}

// Generic 2-col table
function twoColTable(rows, col1W = 3200, col2W = 6160) {
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [col1W, col2W],
    rows: rows.map(([left, right], i) => new TableRow({
      children: [
        new TableCell({
          borders: { top: thinBorder, bottom: thinBorder, left: thinBorder, right: thinBorder },
          shading: { fill: i === 0 ? C.indigoLt : C.white, type: ShadingType.CLEAR },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          width: { size: col1W, type: WidthType.DXA },
          children: [new Paragraph({ spacing: { before: 0, after: 0 },
            children: [new TextRun({ text: left, bold: i === 0, size: i === 0 ? 20 : 21,
              color: i === 0 ? C.indigoDk : C.slate700, font: "Calibri" })] })],
        }),
        new TableCell({
          borders: { top: thinBorder, bottom: thinBorder, left: thinBorder, right: thinBorder },
          shading: { fill: i === 0 ? C.indigoLt : C.white, type: ShadingType.CLEAR },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          width: { size: col2W, type: WidthType.DXA },
          children: typeof right === "string"
            ? [new Paragraph({ spacing: { before: 0, after: 0 },
                children: [new TextRun({ text: right, bold: i === 0, size: i === 0 ? 20 : 21,
                  color: i === 0 ? C.indigoDk : C.slate700, font: "Calibri" })] })]
            : right,
        }),
      ],
    })),
  });
}

// Full-width header table
function sectionHeader(text, bg = C.indigo) {
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [9360],
    rows: [new TableRow({
      children: [new TableCell({
        borders: { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder },
        shading: { fill: bg, type: ShadingType.CLEAR },
        margins: { top: 100, bottom: 100, left: 180, right: 180 },
        width: { size: 9360, type: WidthType.DXA },
        children: [new Paragraph({ spacing: { before: 0, after: 0 },
          children: [new TextRun({ text, bold: true, size: 26, color: C.white, font: "Calibri" })] })],
      })],
    })],
  });
}

// Scope matrix row
function scopeRow(feature, why, tier, current, effort, tierBg, tierColor) {
  const tierCell = (t, bg, color) => new TableCell({
    borders: { top: thinBorder, bottom: thinBorder, left: thinBorder, right: thinBorder },
    shading: { fill: bg, type: ShadingType.CLEAR },
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    width: { size: 900, type: WidthType.DXA },
    verticalAlign: VerticalAlign.CENTER,
    children: [new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 0, after: 0 },
      children: [new TextRun({ text: t, bold: true, size: 18, color, font: "Calibri" })] })],
  });

  return new TableRow({ children: [
    new TableCell({
      borders: { top: thinBorder, bottom: thinBorder, left: thinBorder, right: thinBorder },
      margins: { top: 60, bottom: 60, left: 100, right: 100 },
      width: { size: 2200, type: WidthType.DXA },
      children: [
        new Paragraph({ spacing: { before: 0, after: 20 },
          children: [new TextRun({ text: feature, bold: true, size: 20, color: C.slate700, font: "Calibri" })] }),
        new Paragraph({ spacing: { before: 0, after: 0 },
          children: [new TextRun({ text: why, size: 18, color: C.slate, font: "Calibri" })] }),
      ],
    }),
    tierCell(tier, tierBg, tierColor),
    new TableCell({
      borders: { top: thinBorder, bottom: thinBorder, left: thinBorder, right: thinBorder },
      margins: { top: 60, bottom: 60, left: 100, right: 100 },
      width: { size: 1100, type: WidthType.DXA },
      children: [new Paragraph({ spacing: { before: 0, after: 0 },
        children: [new TextRun({ text: current, size: 19, color: C.slate, font: "Calibri" })] })],
    }),
    new TableCell({
      borders: { top: thinBorder, bottom: thinBorder, left: thinBorder, right: thinBorder },
      margins: { top: 60, bottom: 60, left: 100, right: 100 },
      width: { size: 1200, type: WidthType.DXA },
      children: [new Paragraph({ spacing: { before: 0, after: 0 },
        children: [new TextRun({ text: effort, bold: true, size: 19, color: C.slate700, font: "Calibri" })] })],
    }),
    new TableCell({
      borders: { top: thinBorder, bottom: thinBorder, left: thinBorder, right: thinBorder },
      shading: { fill: why.length > 0 ? C.white : C.slateLt, type: ShadingType.CLEAR },
      margins: { top: 60, bottom: 60, left: 100, right: 100 },
      width: { size: 3960, type: WidthType.DXA },
      children: [new Paragraph({ spacing: { before: 0, after: 0 },
        children: [new TextRun({ text: why.length > 40 ? why : why, size: 18, color: C.slate, font: "Calibri" })] })],
    }),
  ]});
}

// ─── Document content ────────────────────────────────────────────────────────

const children = [];

// ── COVER PAGE ───────────────────────────────────────────────────────────────
children.push(spacer(2400));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { before: 0, after: 80 },
  children: [new TextRun({ text: "AI CHALKBOARD INTELLIGENCE", bold: true, size: 52, color: C.indigoDk, font: "Calibri" })],
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { before: 0, after: 200 },
  children: [new TextRun({ text: "ACI", bold: true, size: 52, color: C.indigo, font: "Calibri" })],
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { before: 0, after: 60 },
  children: [new TextRun({ text: "Design, Architecture & Offline Strategy", size: 30, color: C.slate, font: "Calibri" })],
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { before: 0, after: 400 },
  children: [new TextRun({ text: "Technical Design Document  ·  v1.0  ·  June 2026", size: 22, color: C.slate, font: "Calibri" })],
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  border: { top: { style: BorderStyle.SINGLE, size: 8, color: C.slate200 } },
  spacing: { before: 200, after: 60 },
  children: [new TextRun({ text: "Covers: Requirements · Current Architecture · Feature Inventory", size: 20, color: C.slate, font: "Calibri" })],
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { before: 0, after: 0 },
  children: [new TextRun({ text: "Offline Scope · Architecture · Data Flows · Design Decisions · Implementation Plan", size: 20, color: C.slate, font: "Calibri" })],
}));
children.push(pageBreak());

// ── TABLE OF CONTENTS ────────────────────────────────────────────────────────
children.push(h1("Table of Contents"));
children.push(new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-3" }));
children.push(pageBreak());

// ═══════════════════════════════════════════════════════════════════════════
// SECTION 1 — PROJECT OVERVIEW
// ═══════════════════════════════════════════════════════════════════════════
children.push(sectionHeader("1. Project Overview"));
children.push(spacer(120));

children.push(h2("1.1 What is ACI?"));
children.push(para("AI Chalkboard Intelligence (ACI) is a classroom-intelligence platform designed for school teachers. It captures what happens on a physical teaching board during a class — photographs, audio, and video — and uses AI to extract structured insights: board text (via OCR), lesson-plan coverage gaps, student comprehension analysis, quiz generation, and teaching-quality scoring."));
children.push(para("The core insight behind ACI is that the most important information in a classroom lives on the physical board and in the teacher’s voice. ACI makes that information digital, structured, and actionable without requiring the teacher to change how they teach."));

children.push(h2("1.2 Core User Workflow"));
children.push(numbered([bold("Before class: "), run("Upload lesson plan (PDF or photo). ACI extracts planned topics.")]));
children.push(numbered([bold("During class: "), run("Teacher captures board photos, records audio/video using a mobile device. App works even without WiFi.")]));
children.push(numbered([bold("After class: "), run("ACI generates: board-text OCR, lesson-plan coverage report, class analysis, gap analysis, quiz questions, teaching-effectiveness score.")]));
children.push(numbered([bold("Review: "), run("Teacher reviews AI outputs, downloads reports, shares with school administration.")]));

children.push(h2("1.3 Technology Stack"));
children.push(twoColTable([
  ["Layer", "Technology"],
  ["Frontend", "Next.js 16 (App Router, Turbopack) · React 18 · TypeScript · Tailwind CSS"],
  ["State / Data fetching", "SWR (server data) · React Context (i18n) · useState / useRef / useCallback"],
  ["Offline storage", "IndexedDB via idb library · Service Worker (registration only, not full offline yet)"],
  ["Backend", "FastAPI (async) · Python 3.12 · uvicorn with --reload"],
  ["ORM / DB", "SQLAlchemy 2.0 async · aiosqlite · SQLite (dev.db) · Alembic migrations"],
  ["AI services", "OpenAI GPT-4o (OCR, analysis, quiz) · OpenAI Whisper (audio/video transcription)"],
  ["Media processing", "ffmpeg (frame extraction, audio extraction from video) · ffprobe (duration detection)"],
  ["Infrastructure", "Local dev · Docker Compose available · mobile access via LAN IP"],
  ["Internationalisation", "Custom i18n context: English, Hindi, Kannada, Telugu, Marathi, Tamil"],
], 2400, 6960));

children.push(pageBreak());

// ═══════════════════════════════════════════════════════════════════════════
// SECTION 2 — CURRENT APPLICATION ARCHITECTURE
// ═══════════════════════════════════════════════════════════════════════════
children.push(sectionHeader("2. Current Application Architecture"));
children.push(spacer(120));

children.push(h2("2.1 Frontend Architecture"));

children.push(h3("2.1.1 Directory Structure"));
children.push(twoColTable([
  ["Path", "Purpose"],
  ["src/app/(dashboard)/", "Route group: all authenticated pages share session layout"],
  ["src/app/(dashboard)/sessions/", "Session list page"],
  ["src/app/(dashboard)/sessions/[sessionId]/", "Per-session layout with tab navigation"],
  ["src/app/(dashboard)/sessions/[sessionId]/capture/", "Camera · audio · video capture page (most complex)"],
  ["src/app/(dashboard)/sessions/[sessionId]/class-analysis/", "Audio transcript analysis view"],
  ["src/app/(dashboard)/sessions/[sessionId]/lesson-plan/", "Lesson plan upload + coverage analysis"],
  ["src/app/(dashboard)/sessions/[sessionId]/gap-analysis/", "AI gap analysis view"],
  ["src/app/(dashboard)/sessions/[sessionId]/quiz/", "Quiz generation view"],
  ["src/app/(dashboard)/sessions/[sessionId]/notes/", "AI notes / session overview"],
  ["src/lib/api.ts", "Typed API client with all fetch helpers and TypeScript interfaces"],
  ["src/lib/offline-store.ts", "IndexedDB helpers (idb library) for frames"],
  ["src/lib/sync-engine.ts", "Background sync logic: compress, upload, retry"],
  ["src/lib/i18n.ts", "Translation dictionaries for 6 locales"],
  ["src/contexts/LanguageContext.tsx", "React context for locale state + t() helper"],
  ["src/components/capture/CameraCapture.tsx", "Reusable camera component"],
  ["src/components/layout/TopBar.tsx", "Navigation bar with language switcher"],
  ["src/hooks/useSyncQueue.ts", "Hook exposing sync queue state to UI components"],
], 3200, 6160));

children.push(h3("2.1.2 Key Pages and Components"));
children.push(para([bold("Capture page (capture/page.tsx): "), run("The most complex page in the app. Contains three tabs: Camera (live photo capture), Video (full-screen recording), Upload (drag-and-drop image upload). Manages local frame previews, sync queue state, recording state machines (useAudioRecorder, useVideoRecorder hooks), and the video full-screen overlay. Integrates with IndexedDB offline store for frame queuing.")]));
children.push(para([bold("Session layout ([sessionId]/layout.tsx): "), run("Provides the tab bar navigation across all session sub-pages. Tab labels are translated via the i18n context. Tabs: Capture, Class Analysis, Lesson Plan, Gap Analysis, Quiz, Notes.")]));
children.push(para([bold("TopBar (TopBar.tsx): "), run("Breadcrumb navigation + globe icon language switcher. Locale stored in localStorage (key: aci_locale). Supports English, हिन्दी, ಕನ್ನಡ, తెలుగు, मराठी, தமிழ்.")]));
children.push(para([bold("RecordingRow component: "), run("Displays one audio or video recording with: numbered badge, duration, source badge (Audio/Video), transcribed pill, token count, expand/collapse transcript, delete button.")]));

children.push(h3("2.1.3 State Management Patterns"));
children.push(bullet([bold("SWR: "), run("All server data fetched with useSWR. Keys: ['session', id], ['frames', id], ['audio', id], ['outputs', id]. revalidateOnFocus disabled for capture page to avoid disrupting recording.")]));
children.push(bullet([bold("Custom hooks: "), run("useAudioRecorder (recording state machine: idle→recording→uploading→idle), useVideoRecorder (same plus live preview ref), useSyncQueue (exposes queue counts, sync status, trigger).")]));
children.push(bullet([bold("React refs: "), run("MediaRecorder, MediaStream, timer intervals, blob chunks, video preview element — all stored in refs to survive renders without triggering re-renders.")]));
children.push(bullet([bold("Language context: "), run("LanguageProvider wraps the app in layout.tsx. useLanguage() hook returns { locale, setLocale, t } — the t object gives translated strings for the current locale.")]));

children.push(h2("2.2 Backend Architecture"));

children.push(h3("2.2.1 Project Structure"));
children.push(twoColTable([
  ["Path", "Purpose"],
  ["app/main.py", "FastAPI app, router registration, CORS, startup/shutdown"],
  ["app/routers/audio.py", "POST/GET/DELETE /sessions/{id}/audio endpoints"],
  ["app/routers/video.py", "POST /sessions/{id}/video — ffmpeg frames + Whisper"],
  ["app/routers/frames.py", "Frame upload, OCR trigger, frame list"],
  ["app/routers/sessions.py", "Session CRUD"],
  ["app/routers/outputs.py", "AI output fetch + generation trigger"],
  ["app/routers/lesson_plans.py", "Lesson plan upload + topic extraction"],
  ["app/services/ai_service.py", "AI generation orchestrator: prompt selection, GPT-4o call, response parsing"],
  ["app/services/whisper_service.py", "Whisper transcription with hallucination guards"],
  ["app/services/storage_service.py", "File persistence (frames, audio, video, lesson plans)"],
  ["app/ai/prompt_builder.py", "Prompt construction functions for each AI output type"],
  ["app/ai/response_parser.py", "JSON response parsing for each AI output type"],
  ["app/models/", "SQLAlchemy ORM models: Session, Frame, Job, SessionAudio, LessonPlan, AIOutput"],
  ["app/dependencies.py", "FastAPI dependency injection: DB session, current teacher"],
  ["app/config.py", "Pydantic settings (env vars, API keys)"],
  ["alembic/", "Database migration scripts"],
], 2800, 6560));

children.push(h3("2.2.2 Async Architecture"));
children.push(para("The entire backend is async throughout. FastAPI runs on uvicorn with asyncio. SQLAlchemy uses aiosqlite for non-blocking database access. File I/O uses asyncio.create_subprocess_exec for ffmpeg/ffprobe calls. Heavy AI tasks (OCR, Whisper) run as FastAPI BackgroundTasks — the endpoint returns immediately and processing continues in the background."));

children.push(h3("2.2.3 AI Service Design"));
children.push(para("The AI service (ai_service.py) uses a map-driven architecture:"));
children.push(bullet([code("prompt_map"), run(": output_type → prompt builder function")]));
children.push(bullet([code("parser_map"), run(": output_type → response parser function")]));
children.push(bullet([code("TOKEN_LIMITS"), run(": output_type → max_tokens for GPT-4o call")]));
children.push(para("Adding a new AI output type requires: (1) a prompt builder function, (2) a parser function, (3) registering both in the maps. The orchestrator handles GPT-4o API call, JSON extraction, error handling, and AIOutput row persistence automatically."));

children.push(h3("2.2.4 Whisper Hallucination Guards"));
children.push(para("The Whisper service implements three-layer defence against audio hallucination (common with silence/noise recordings):"));
children.push(numbered([bold("Duration guard: "), run("Recordings shorter than 2 seconds are rejected before sending to Whisper.")]));
children.push(numbered([bold("Segment filtering: "), run("Segments with no_speech_prob > 0.60 or avg_logprob < -1.0 are dropped from the transcript.")]));
children.push(numbered([bold("Pattern blocklist: "), run("Regex patterns matching known Whisper hallucination strings (“Thank you for watching”, “Subscribe”, etc.) are stripped.")]));
children.push(para([run("Additionally, "), code("temperature=0"), run(" is passed to the Whisper API to reduce hallucination variance.")]));

children.push(h2("2.3 Database Schema"));

children.push(h3("2.3.1 Core Tables"));
children.push(twoColTable([
  ["Table", "Key columns and purpose"],
  ["sessions", "id (UUID PK), subject, grade, school, teacher_id, frame_count, created_at"],
  ["frames", "id (UUID PK), session_id (FK), local_frame_id (client UUID), sequence_no, image_path, image_size_kb, ocr_status (pending/processing/done/failed), captured_at"],
  ["jobs", "id, job_type (ocr_processing), session_id, frame_id, status (queued/processing/done/failed)"],
  ["session_audios", "id (UUID PK), session_id (FK), recording_number, source (audio|video), file_path, file_type, duration_sec, transcript (text), segments (JSON), whisper_language, whisper_tokens, created_at"],
  ["ai_outputs", "id, session_id, output_type (gap_analysis|class_analysis|quiz_questions|lesson_plan_coverage|teaching_effectiveness), content_json, status, created_at"],
  ["lesson_plans", "id, session_id (unique FK), file_path, file_type, raw_text, topics (JSON array), created_at"],
  ["teachers", "id, email, name, created_at"],
], 2000, 7360));

children.push(h3("2.3.2 Notable Design Choices"));
children.push(bullet([bold("local_frame_id: "), run("Client generates its own UUID for each frame before upload. Server stores this alongside its own UUID. Allows client to match server-side frames to local IndexedDB entries without a round-trip.")]));
children.push(bullet([bold("source column on session_audios: "), run("Distinguishes audio-only recordings from video-extracted audio. Both go through Whisper; both appear in class analysis. Added via ALTER TABLE in dev.db.")]));
children.push(bullet([bold("segments JSON: "), run("Whisper returns per-segment timing + confidence. Stored as JSON for future use (e.g. generating timestamped transcripts, identifying which board section was discussed when).")]));

children.push(h2("2.4 Existing API Contracts"));
children.push(twoColTable([
  ["Endpoint", "Purpose"],
  ["POST /sessions/{id}/audio", "Upload audio blob; triggers Whisper transcription; returns transcript + token count"],
  ["GET /sessions/{id}/audio", "Returns all recordings (audio + video) for a session ordered by recording_number"],
  ["DELETE /sessions/{id}/audio/{audio_id}", "Deletes one recording; returns 204 No Content"],
  ["POST /sessions/{id}/video", "Upload video blob; ffmpeg extracts frames + audio; Whisper transcribes; OCR queued"],
  ["POST /sessions/{id}/frames", "Upload JPEG frame; saves to storage; queues OCR background task"],
  ["GET /sessions/{id}/frames", "Returns all frames with OCR status, local_frame_id, image paths"],
  ["POST /sessions/{id}/lesson-plan", "Upload PDF/image; extracts text; AI extracts topic list; upserts lesson plan"],
  ["GET /sessions/{id}/lesson-plan", "Returns current lesson plan with extracted topics"],
  ["POST /sessions/{id}/generate", "Triggers AI generation for one or more output types"],
  ["GET /sessions/{id}/outputs", "Returns all AI outputs for the session"],
  ["GET /sessions", "Returns session list for current teacher"],
  ["POST /sessions", "Creates a new session"],
], 3200, 6160));

children.push(pageBreak());

// ═══════════════════════════════════════════════════════════════════════════
// SECTION 3 — FEATURE INVENTORY
// ═══════════════════════════════════════════════════════════════════════════
children.push(sectionHeader("3. Feature Inventory (Current State)"));
children.push(spacer(120));

children.push(h2("3.1 Built Features"));
children.push(twoColTable([
  ["Feature", "Status / Notes"],
  ["Multiple audio recordings per session", "Complete — list with transcripts, expand/collapse, delete, token count"],
  ["Video recording with live preview", "Complete — full-screen overlay, back-facing camera, pulsing timer"],
  ["Video frame extraction (ffmpeg)", "Complete — 1 frame per 10s, JPEG, queued for OCR"],
  ["Audio transcription (Whisper)", "Complete — with 3-layer hallucination guards"],
  ["Video audio transcription", "Complete — ffmpeg extracts 16kHz WAV, same Whisper pipeline"],
  ["Board OCR (GPT-4o vision)", "Complete — per-frame, background processed, privacy blur applied"],
  ["Privacy blur (board exterior)", "Complete — background blurred, board area preserved"],
  ["Class analysis (AI)", "Complete — combines all transcripts, analyses teaching patterns"],
  ["Gap analysis (AI)", "Complete — identifies knowledge gaps from board + audio"],
  ["Lesson plan coverage", "Complete — compares planned topics vs board OCR; teaching notes for missing topics"],
  ["Quiz generation (AI)", "Complete — generates quiz questions from session content"],
  ["Teaching effectiveness score (AI)", "Complete — scores teaching patterns"],
  ["Lesson plan upload (PDF/image)", "Complete — text extraction, AI topic parsing"],
  ["Internationalisation (i18n)", "Complete — 6 languages: English, Hindi, Kannada, Telugu, Marathi, Tamil"],
  ["Language switcher", "Complete — globe icon in TopBar, persisted in localStorage"],
  ["Frame capture (camera tab)", "Complete — local preview, sync queue, server upload"],
  ["Offline frame queuing", "Partial — IndexedDB + sync engine exists for frames only"],
  ["Delete recording", "Complete — 204 No Content handled correctly in fetch helper"],
  ["Token usage tracking", "Complete — whisper_tokens stored, displayed per recording"],
  ["Sync status bar", "Complete — shows pending/uploading counts, last sync time, online status"],
], 3200, 6160));

children.push(h2("3.2 Known Gaps / Not Yet Offline"));
children.push(bullet([bold("Audio recording offline: "), run("If network drops during recording, the upload fails silently. No local queue for audio blobs.")]));
children.push(bullet([bold("Video recording offline: "), run("Same as audio — blob is lost if network unavailable during upload.")]));
children.push(bullet([bold("Delete while offline: "), run("Delete button fails if offline. No queue for delete operations.")]));
children.push(bullet([bold("AI output caching: "), run("Outputs are fetched from server on every page visit. No local cache — outputs are lost if network drops while viewing.")]));
children.push(bullet([bold("Session list caching: "), run("Session list requires network. Cannot browse sessions offline.")]));

children.push(pageBreak());

// ═══════════════════════════════════════════════════════════════════════════
// SECTION 4 — OFFLINE STRATEGY: PROBLEM & SCOPE
// ═══════════════════════════════════════════════════════════════════════════
children.push(sectionHeader("4. Offline-First Strategy: Problem & Scope"));
children.push(spacer(120));

children.push(h2("4.1 Problem Statement"));
children.push(para("Teachers use ACI in classrooms where WiFi is frequently unreliable or absent. School networks are often overloaded during class hours, mobile data is not always available, and devices switch between WiFi and mobile data mid-lesson."));
children.push(para("The current failure mode is silent and destructive: if the network drops while a teacher is recording audio or video, the recording is simply lost when they press Stop. There is no local save, no retry, no warning. This is the most critical gap in the current architecture."));
children.push(callout("Core Principle", "Any action the teacher takes during class — capturing, recording, stopping — must succeed locally and sync when network is available. AI generation is inherently online and is explicitly excluded from offline scope.", C.indigoLt, C.indigo));

children.push(h2("4.2 Scope Decision Matrix"));
children.push(spacer(80));

// Scope table header
children.push(new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [2200, 900, 1100, 1200, 3960],
  rows: [
    new TableRow({ children: [
      new TableCell({ shading: { fill: C.indigoDk, type: ShadingType.CLEAR }, borders: { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder }, margins: { top: 80, bottom: 80, left: 100, right: 100 }, width: { size: 2200, type: WidthType.DXA }, children: [new Paragraph({ spacing:{before:0,after:0}, children: [new TextRun({text:"Feature",bold:true,size:20,color:C.white,font:"Calibri"})] })] }),
      new TableCell({ shading: { fill: C.indigoDk, type: ShadingType.CLEAR }, borders: { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder }, margins: { top: 80, bottom: 80, left: 100, right: 100 }, width: { size: 900, type: WidthType.DXA }, children: [new Paragraph({ spacing:{before:0,after:0}, alignment: AlignmentType.CENTER, children: [new TextRun({text:"Tier",bold:true,size:20,color:C.white,font:"Calibri"})] })] }),
      new TableCell({ shading: { fill: C.indigoDk, type: ShadingType.CLEAR }, borders: { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder }, margins: { top: 80, bottom: 80, left: 100, right: 100 }, width: { size: 1100, type: WidthType.DXA }, children: [new Paragraph({ spacing:{before:0,after:0}, children: [new TextRun({text:"Current State",bold:true,size:20,color:C.white,font:"Calibri"})] })] }),
      new TableCell({ shading: { fill: C.indigoDk, type: ShadingType.CLEAR }, borders: { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder }, margins: { top: 80, bottom: 80, left: 100, right: 100 }, width: { size: 1200, type: WidthType.DXA }, children: [new Paragraph({ spacing:{before:0,after:0}, children: [new TextRun({text:"Effort",bold:true,size:20,color:C.white,font:"Calibri"})] })] }),
      new TableCell({ shading: { fill: C.indigoDk, type: ShadingType.CLEAR }, borders: { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder }, margins: { top: 80, bottom: 80, left: 100, right: 100 }, width: { size: 3960, type: WidthType.DXA }, children: [new Paragraph({ spacing:{before:0,after:0}, children: [new TextRun({text:"Rationale",bold:true,size:20,color:C.white,font:"Calibri"})] })] }),
    ]}),
    scopeRow("Frame capture", "Take board photos mid-lesson", "MUST", "80% done", "Finalise 1d", C.greenLt, C.green),
    scopeRow("Audio recording", "Record class discussion", "MUST", "Online only", "3 days", C.greenLt, C.green),
    scopeRow("Video recording", "Record board + audio", "MUST", "Online only", "3 days", C.greenLt, C.green),
    scopeRow("Delete recording", "Remove unwanted clip", "MUST", "Online only", "0.5 days", C.greenLt, C.green),
    scopeRow("Session list", "Browse past sessions", "NICE", "Online only", "1 day", C.amberLt, C.amber),
    scopeRow("View AI outputs (cached)", "Re-read analysis offline", "NICE", "Not cached", "1 day", C.amberLt, C.amber),
    scopeRow("Lesson plan upload", "Upload PDF before class", "NICE", "Online only", "1 day", C.amberLt, C.amber),
    scopeRow("Create new session", "Start a class session", "NICE", "Online only", "2 days", C.amberLt, C.amber),
    scopeRow("AI generation (analysis, quiz)", "Generate insights with GPT-4o", "NEVER", "Online only", "N/A", C.roseLt, C.rose),
    scopeRow("OCR processing", "Extract text from board photos", "NEVER", "Server-side", "N/A", C.roseLt, C.rose),
    scopeRow("Whisper transcription", "Transcribe audio/video", "NEVER", "Server-side", "N/A", C.roseLt, C.rose),
  ],
}));

children.push(spacer(80));
children.push(callout("Recommendation", "Implement Phase 1 (Tier 1 Must features) only. This covers 100% of the classroom capture workflow. Tier 2 Nice features are comfort improvements — implement based on teacher feedback after Phase 1 ships.", C.greenLt, C.green));

children.push(pageBreak());

// ═══════════════════════════════════════════════════════════════════════════
// SECTION 5 — OFFLINE ARCHITECTURE
// ═══════════════════════════════════════════════════════════════════════════
children.push(sectionHeader("5. Offline Architecture Design"));
children.push(spacer(120));

children.push(h2("5.1 Architecture Overview"));
children.push(para("The offline architecture follows the Outbox Pattern: every mutating action writes to a local queue (the outbox) before attempting a network request. The sync engine drains the queue when network is available. The server provides an idempotency layer to make all retries safe."));
children.push(para("The architecture has three logical layers:"));
children.push(numbered([bold("Client persistence layer: "), run("IndexedDB stores entity data, raw blobs, the sync queue, and the sync cursor.")]));
children.push(numbered([bold("Sync transport layer: "), run("The sync engine drains the queue. Uploads go directly to existing endpoints with an idempotency key header.")]));
children.push(numbered([bold("Server processing layer: "), run("Existing endpoints accept idempotency keys and deduplicate retried requests. Heavy background processing (OCR, Whisper) continues unchanged.")]));

children.push(h2("5.2 Client-Side Architecture"));

children.push(h3("5.2.1 IndexedDB Schema (Expanded)"));
children.push(twoColTable([
  ["Store name", "Contents and purpose"],
  ["entities.frames", "Existing — local frame records: id, blobUrl, sequenceNo, capturedAt, syncStatus"],
  ["entities.recordings", "NEW — audio/video recording metadata: id, sessionId, source, duration, transcript, syncStatus, createdAt"],
  ["entities.sessions", "NEW (Phase 2) — cached session list for offline browsing"],
  ["entities.outputs", "NEW (Phase 2) — cached AI outputs for offline reading"],
  ["syncQueue", "NEW — outbox entries (see shape below). One row per pending operation."],
  ["syncCursor", "NEW — stores the ISO timestamp of the last sync_events row received from server. Used for incremental polling."],
  ["blobs", "NEW — raw audio/video binary data. Stored separately from metadata to avoid holding large buffers in queue entries."],
], 2800, 6560));

children.push(h3("5.2.2 Sync Queue Entry Shape"));
children.push(twoColTable([
  ["Field", "Type / Description"],
  ["id", "string — client-generated UUID for this queue entry"],
  ["idempotencyKey", "string — UUID sent to server as Idempotency-Key header. Generated once, never changes on retry."],
  ["type", "enum — UPLOAD_FRAME | UPLOAD_AUDIO | UPLOAD_VIDEO | DELETE_RECORDING | CREATE_SESSION"],
  ["sessionId", "string — which session this operation belongs to"],
  ["payload", "JSON object — operation-specific metadata (recording number, file type, duration, etc.)"],
  ["blobKey", "string | null — IDB key in blobs store for the raw binary (null for deletes/metadata ops)"],
  ["priority", "number — 1=delete (cheapest) · 2=audio/video · 3=frame upload"],
  ["status", "enum — pending | sending | sent | failed | skipped"],
  ["retries", "number — count of failed attempts"],
  ["nextRetryAt", "number — epoch ms, when to next attempt after backoff"],
  ["createdAt", "number — epoch ms"],
  ["sentAt", "number | null — epoch ms when successfully sent"],
  ["error", "string | null — last error message for UI display"],
], 2200, 7160));

children.push(h3("5.2.3 Sync Engine"));
children.push(para("The sync engine (sync-engine.ts) runs in the main thread. It is event-driven: it wakes on network online events, visibilitychange (tab comes to foreground), and a periodic 30-second heartbeat tick."));
children.push(para([bold("Concurrency model: "), run("The engine picks up to 2 pending queue entries concurrently. This respects mobile upload bandwidth. Delete operations do not count against this limit (they are tiny JSON requests).")]));
children.push(para([bold("Priority ordering: "), run("Entries are sorted by (priority ASC, createdAt ASC). Deletes (priority 1) always go before uploads. Within uploads, audio/video (priority 2) go before frames (priority 3).")]));
children.push(para([bold("Backoff strategy: "), run("On failure, nextRetryAt is set to now + backoff(retries). Backoff sequence: 2s, 4s, 8s, 30s, 60s (capped). Each delay is jittered ±20% to avoid thundering herd when multiple devices reconnect simultaneously (e.g. school WiFi resumes). After 5 retries, status is set to failed and the UI shows an error with a manual retry option.")]));
children.push(para([bold("Blob handling: "), run("For audio and video uploads, the engine reads the blob from the blobs IDB store, constructs a FormData object, and POSTs to the existing /audio or /video endpoint. The blob is deleted from IDB only after a successful server response.")]));
children.push(para([bold("Idempotency: "), run("Every request includes an Idempotency-Key HTTP header with the queue entry’s idempotencyKey. If the server returns 409 (duplicate key), the engine treats this as a success and marks the entry as sent.")]));

children.push(h3("5.2.4 Optimistic UI Strategy"));
children.push(para("When a teacher stops a recording while offline:"));
children.push(numbered([bold("Immediate: "), run("The recording appears in the UI instantly with a ⧖ “Pending sync” badge. Duration and metadata are shown from local state.")]));
children.push(numbered([bold("On sync start: "), run("Badge changes to a spinner with “Uploading…”")]));
children.push(numbered([bold("On sync success: "), run("Badge clears. Transcript appears (fetched from server via SWR revalidation).")]));
children.push(numbered([bold("On sync failure (after retries): "), run("Badge shows ⚠️ with error message and a “Retry” button.")]));
children.push(para("The key principle: the teacher never loses data. Even if the sync fails repeatedly, the recording blob remains in IDB until it either succeeds or the teacher explicitly discards it."));

children.push(h3("5.2.5 Storage Quota Management"));
children.push(para([run("IndexedDB quota on mobile browsers is typically 60% of available device storage. A 30-minute video can reach 500MB. The app should: (a) warn when unsynced local data exceeds 500MB, (b) prompt teacher to connect to WiFi and sync, (c) never silently discard data. Quota exceeded errors from IDB are caught explicitly — silent failure here would be worse than any other error in the app.")]));

children.push(h2("5.3 Server-Side Architecture"));

children.push(h3("5.3.1 Idempotency Middleware"));
children.push(para("The central server-side addition is idempotency key deduplication. All POST and DELETE endpoints that accept a client idempotency key must:"));
children.push(numbered([run("Check if the key exists in the idempotency_keys table.")]));
children.push(numbered([run("If it exists: return the cached result_json with the original status code. Do not re-process.")]));
children.push(numbered([run("If it does not exist: process the request normally, then insert the key + result into idempotency_keys.")]));
children.push(para([run("Keys have a 7-day TTL. A nightly cleanup job removes expired rows. This design means "), bold("all client retries are unconditionally safe"), run(" — the same audio file can be POSTed 10 times and Whisper runs exactly once.")]));

children.push(h3("5.3.2 New Database Tables"));
children.push(twoColTable([
  ["Table", "Schema and purpose"],
  ["idempotency_keys", "key VARCHAR(36) PK, type VARCHAR(50), session_id UUID, result_json TEXT, created_at TIMESTAMP, expires_at TIMESTAMP. Deduplication store for all mutating operations."],
  ["sync_events (Phase 2)", "id UUID PK, session_id UUID, type VARCHAR(50), payload_json TEXT, created_at TIMESTAMP. Immutable log of processing results. Client polls with cursor. Types: FRAME_PROCESSED, AUDIO_TRANSCRIBED, OCR_DONE, VIDEO_PROCESSED."],
  ["inbox_items (Phase 3)", "id UUID PK, idempotency_key VARCHAR(36), type VARCHAR(50), payload_json TEXT, status VARCHAR(20), priority INT, created_at TIMESTAMP, claimed_at TIMESTAMP, done_at TIMESTAMP, error TEXT. Fast-ACK inbox for lightweight ops and async processing."],
], 2400, 6960));

children.push(h3("5.3.3 Optimistic Versioning"));
children.push(para("Add version INTEGER column to sessions and session_audios tables. Version is incremented on every UPDATE. Clients send an If-Match: version=N header on PATCH requests. If the version does not match the current row, the server returns 409 Conflict with the current version. The client must re-fetch and re-apply the change."));
children.push(callout("Scope note", "Frames and recordings (session_audios) are append-only: once uploaded they are never edited. Versioning is not needed on these rows. Only session metadata (subject, grade, school) is mutable — that is where conflicts can occur.", C.amberLt, C.amber));

children.push(h3("5.3.4 Blob Upload Strategy (Critical Constraint)"));
children.push(para("Audio and video blobs range from 1MB to 200MB. They cannot be routed through a JSON inbox body. The blob upload strategy is therefore:"));
children.push(bullet([bold("Blobs go directly to existing endpoints: "), code("POST /sessions/{id}/audio"), run(" and "), code("POST /sessions/{id}/video"), run(". No new upload endpoints needed.")]));
children.push(bullet([bold("Idempotency is applied via header: "), run("The sync engine adds "), code("Idempotency-Key: {uuid}"), run(" to the multipart POST. The server checks this before running Whisper or ffmpeg.")]));
children.push(bullet([bold("Metadata ops use inbox (Phase 3 only): "), run("Deletes, session creates, lesson plan uploads — lightweight JSON — can route through the inbox endpoint if a full inbox architecture is built.")]));

children.push(pageBreak());

// ═══════════════════════════════════════════════════════════════════════════
// SECTION 6 — DATA FLOWS
// ═══════════════════════════════════════════════════════════════════════════
children.push(sectionHeader("6. Data Flows"));
children.push(spacer(120));

children.push(h2("6.1 Flow A: Record Audio Offline, Sync Later"));
children.push(twoColTable([
  ["Step", "What happens"],
  ["1. Teacher presses Record (offline)", "MediaRecorder starts. Audio chunks accumulate in memory (chunksRef). Timer counts up. UI shows recording state normally."],
  ["2. Teacher presses Stop", "Blob assembled from chunks. Written to IDB blobs store under a UUID key. Metadata written to entities.recordings with syncStatus=pending. Recording row appears in UI immediately with ⧖ badge."],
  ["3. Sync queue entry created", "Entry: { type: UPLOAD_AUDIO, blobKey: <uuid>, idempotencyKey: <new-uuid>, priority: 2, status: pending }. Sync engine is notified."],
  ["4. Network returns (seconds or hours later)", "Sync engine wakes on online event. Reads pending entry. Reads blob from IDB. Constructs FormData. POSTs to /sessions/{id}/audio with Idempotency-Key header."],
  ["5. Server processes", "Checks idempotency key — not seen, proceeds. Saves audio file. Runs Whisper. Stores transcript. Returns 201 with full recording data."],
  ["6. Client receives 201", "Marks queue entry as sent. Deletes blob from IDB blobs store (free space). Triggers SWR revalidation of audio list. UI badge clears, transcript appears."],
  ["7. Retry scenario", "If upload drops mid-stream (step 4), server may or may not have received it. Client retries with same idempotencyKey after backoff. If server already processed → returns 200 with cached result. Safe."],
], 2800, 6560));

children.push(h2("6.2 Flow B: Delete a Recording While Offline"));
children.push(twoColTable([
  ["Step", "What happens"],
  ["1. Teacher taps Delete", "Check: has this recording been uploaded to server?"],
  ["2a. If not yet uploaded (pending sync)", "Remove entity from IDB entities.recordings. Remove sync queue entry for the UPLOAD op. Remove blob from IDB blobs store. Done — no server call needed at all."],
  ["2b. If already on server", "Soft-delete in IDB (set syncStatus=deleted-pending). Recording disappears from UI immediately. Add DELETE_RECORDING entry to sync queue with priority=1."],
  ["3. On reconnect", "Delete op goes first (priority 1). POSTs DELETE /sessions/{id}/audio/{audio_id} with Idempotency-Key. Server deletes row, returns 204."],
  ["4. Conflict: delete + upload in queue", "If an UPLOAD for the same recording is also in the queue (race condition): sync engine cancels the UPLOAD entry when it sees the DELETE was sent. Prevents zombie uploads."],
], 2800, 6560));

children.push(h2("6.3 Flow C: Version Conflict (Two Devices, One Session)"));
children.push(twoColTable([
  ["Step", "What happens"],
  ["1. Both devices edit session metadata offline", "Device A changes subject to “Maths” (session at version=3). Device B changes subject to “Science” (also version=3)."],
  ["2. Device A syncs first", "PATCH /sessions/{id} with If-Match: version=3. Server accepts, updates subject=Maths, bumps to version=4."],
  ["3. Device B syncs — 409 Conflict", "PATCH /sessions/{id} with If-Match: version=3. Server returns 409 with body: { currentVersion: 4, currentValue: “Maths” }."],
  ["4. Client resolves", "Sync engine surfaces conflict toast: “Session updated on another device. Their change: Maths. Your change: Science. Keep yours?” Teacher taps Keep Mine → re-sends with version=4. Or taps Discard to accept server value."],
  ["5. Practical note", "This scenario is extremely rare for a solo teacher. The versioning infrastructure is worth building correctly but the conflict UI can be a simple toast, not a complex merge UI."],
], 2800, 6560));

children.push(h2("6.4 Flow D: Full-Screen Video Recording (Current)"));
children.push(para("This flow is already implemented and documents how the existing full-screen recording overlay works:"));
children.push(twoColTable([
  ["Step", "Implementation detail"],
  ["1. Teacher taps Start Recording on Video tab", "handleStartVideoFullScreen() sets videoFullScreen=true. startVideo() calls getUserMedia with facingMode: environment."],
  ["2. Full-screen overlay appears", "CSS toggle (hidden → flex) on always-mounted div with position:fixed; inset:0; z-index:50; background:black."],
  ["3. Live preview fills screen", "<video ref={videoPreviewRef}> with absolute inset-0 h-full w-full object-cover. Stream attached to srcObject."],
  ["4. Teacher taps Stop", "stopAndUpload() called. MediaRecorder stopped. Blob assembled. Currently: direct upload (no offline queue yet)."],
  ["5. Uploading state", "Overlay shows spinner. POST /sessions/{id}/video with FormData. ffmpeg extracts frames + audio. Whisper transcribes."],
  ["6. Upload complete", "videoState returns to idle. useEffect detects this and sets videoFullScreen=false. Overlay hides."],
], 2800, 6560));

children.push(pageBreak());

// ═══════════════════════════════════════════════════════════════════════════
// SECTION 7 — DESIGN DECISIONS
// ═══════════════════════════════════════════════════════════════════════════
children.push(sectionHeader("7. Design Decisions"));
children.push(spacer(120));

const decisions = [
  ["Is sync idempotent?", "YES — mandatory", "Mobile connections drop mid-request constantly. Client must retry blindly. Every operation gets a client-generated UUID as an idempotency key sent in the Idempotency-Key HTTP header. Server stores processed keys for 7 days with the cached response. Same request arriving twice returns the same response without re-processing. This makes all retries unconditionally safe."],
  ["Which tables need versioning?", "Sessions and session_audios only", "Frames and recordings are append-only blobs. Once uploaded they never change — no conflict is possible. Only session metadata (subject, grade) is mutable and can be edited on multiple devices. Adding a version column only where conflicts can actually occur keeps the schema simple and avoids unnecessary overhead on frame/recording writes."],
  ["Sync inbox or direct upload?", "Direct upload for blobs; inbox for metadata ops (Phase 3)", "Audio and video blobs are 10–200MB. Routing them through a JSON inbox body is impractical. They go directly to existing POST /audio and /video endpoints with an idempotency key header. Lightweight operations (deletes, metadata updates) can route through an inbox in a future phase. This keeps Phase 1 scope minimal: no new server endpoints or tables needed beyond idempotency_keys."],
  ["WebSocket or polling for results?", "Polling (GET /sync/events)", "Mobile apps sleep and wake frequently, breaking persistent WebSocket connections. A cursor-based poll (every 10s when page is visible) is simpler, survives sleep/wake, requires no server-side connection state, and works with HTTP/1.1. Sync events are immutable so safe to re-poll. This is the correct choice for a teacher tool used on a mobile browser."],
  ["Client upload concurrency limit?", "2 parallel uploads", "Mobile upload bandwidth is the bottleneck. 2 parallel uploads saturates a typical 4G uplink efficiently without overwhelming it or causing timeouts. Delete operations do not count against this limit as they are tiny JSON requests."],
  ["Backoff strategy?", "Exponential with ±20% jitter; 5 retries max", "Exponential backoff (2s → 4s → 8s → 30s → 60s) avoids hammering a recovering server. Jitter (randomise delay by ±20%) prevents thundering herd when many devices reconnect simultaneously — critical for a school setting where the entire building may reconnect to WiFi at once. Five retries covers virtually all transient network issues. Beyond that, the teacher should be notified so they can take action."],
  ["Service Worker or main thread sync?", "Main thread first; SW background sync as future enhancement", "The Background Sync API (Service Worker) is unreliable on iOS Safari and requires HTTPS. Main thread sync triggered on online and visibilitychange events covers 95% of real-world cases. A teacher who returns to the app after the network resumes will get synced immediately. SW background sync can be layered on later without any architectural changes."],
  ["Full offline vs partial?", "Partial — Tier 1 only in Phase 1", "Full offline (session create, AI output caching, conflict resolution UI) adds approximately 5 additional development days for features teachers rarely need offline. Tier 1 (recording offline) is the only thing that breaks the classroom workflow today. Ship Phase 1 first, measure demand for Phase 2."],
  ["IDB blob storage size risk?", "Accept risk; warn at 500MB, fail loudly", "IDB quota varies by device: typically 60% of available storage on mobile. A 30-minute video at moderate quality is ~500MB. The app should check navigator.storage.estimate() and warn proactively when unsynced data exceeds 500MB. IDB write failures must be caught explicitly and surfaced to the teacher — silent quota errors would be worse than any other failure mode in the app."],
  ["Conflict resolution UX?", "Simple toast with Keep Mine / Discard options", "Full merge UIs are complex to build and confusing to use. For a solo teacher, metadata conflicts are extremely rare (they would need to edit the same session on two devices simultaneously without network). A simple toast notification with two options is sufficient. More sophisticated conflict handling can be added if collaborative use cases emerge."],
];

children.push(new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [2200, 1800, 5360],
  rows: [
    new TableRow({ children: [
      ...[["Question", 2200], ["Decision", 1800], ["Reasoning", 5360]].map(([t, w]) =>
        new TableCell({ shading:{fill:C.indigoDk,type:ShadingType.CLEAR}, borders:{top:noBorder,bottom:noBorder,left:noBorder,right:noBorder}, margins:{top:80,bottom:80,left:100,right:100}, width:{size:w,type:WidthType.DXA}, children:[new Paragraph({spacing:{before:0,after:0},children:[new TextRun({text:t,bold:true,size:20,color:C.white,font:"Calibri"})]})] }))
    ]}),
    ...decisions.map(([q, d, r]) => new TableRow({ children: [
      new TableCell({ borders:{top:thinBorder,bottom:thinBorder,left:thinBorder,right:thinBorder}, margins:{top:80,bottom:80,left:100,right:100}, width:{size:2200,type:WidthType.DXA}, children:[new Paragraph({spacing:{before:0,after:0},children:[new TextRun({text:q,bold:true,size:20,color:C.slate700,font:"Calibri"})]})] }),
      new TableCell({ borders:{top:thinBorder,bottom:thinBorder,left:thinBorder,right:thinBorder}, shading:{fill:C.greenLt,type:ShadingType.CLEAR}, margins:{top:80,bottom:80,left:100,right:100}, width:{size:1800,type:WidthType.DXA}, children:[new Paragraph({spacing:{before:0,after:0},children:[new TextRun({text:d,bold:true,size:20,color:C.green,font:"Calibri"})]})] }),
      new TableCell({ borders:{top:thinBorder,bottom:thinBorder,left:thinBorder,right:thinBorder}, margins:{top:80,bottom:80,left:100,right:100}, width:{size:5360,type:WidthType.DXA}, children:[new Paragraph({spacing:{before:0,after:0},children:[new TextRun({text:r,size:20,color:C.slate,font:"Calibri"})]})] }),
    ]})),
  ],
}));

children.push(pageBreak());

// ═══════════════════════════════════════════════════════════════════════════
// SECTION 8 — IMPLEMENTATION PLAN
// ═══════════════════════════════════════════════════════════════════════════
children.push(sectionHeader("8. Implementation Plan"));
children.push(spacer(120));

children.push(h2("8.1 Effort Summary"));
children.push(twoColTable([
  ["Phase", "Scope", "Effort", "Value"],
  ["Phase 1", "Tier 1 must-haves: audio + video + delete offline", "8 days", "Eliminates recording data loss in classrooms"],
  ["Phase 2", "Tier 2 nice-to-haves: session + output caching, event polling", "5 days", "Smoother offline reading experience"],
  ["Phase 3", "Full offline: session create, inbox architecture, conflict UI", "5 days", "Edge cases only — assess demand after Phase 1/2"],
  ["Total (all phases)", "", "18 days (~3.5 weeks, 1 developer)", ""],
], 1600, 7760));

children.push(h2("8.2 Phase 1 — Record Offline (8 days)"));
children.push(callout("Goal", "Teacher can record audio and video during class with no network. Recordings queue locally and sync automatically when connected. Delete also works offline.", C.greenLt, C.green));
children.push(spacer(60));
children.push(new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [4560, 1600, 1800, 1400],
  rows: [
    new TableRow({ children: [
      ...[["Task",4560],["Layer",1600],["Who",1800],["Days",1400]].map(([t,w])=>
        new TableCell({shading:{fill:C.indigoDk,type:ShadingType.CLEAR},borders:{top:noBorder,bottom:noBorder,left:noBorder,right:noBorder},margins:{top:80,bottom:80,left:100,right:100},width:{size:w,type:WidthType.DXA},children:[new Paragraph({spacing:{before:0,after:0},children:[new TextRun({text:t,bold:true,size:20,color:C.white,font:"Calibri"})]})]})
      )
    ]}),
    ...[
      ["Expand IDB schema: add recordings, blobs, syncQueue, syncCursor stores", "Frontend", "Frontend dev", "0.5"],
      ["On Stop: save audio blob to IDB blobs store; write pending entity row; show pending badge in UI", "Frontend", "Frontend dev", "1.5"],
      ["Same as above for video: save blob, entity row, pending badge", "Frontend", "Frontend dev", "1.0"],
      ["Generalise sync engine: handle UPLOAD_AUDIO and UPLOAD_VIDEO ops; read blob from IDB; send with idempotency key header", "Frontend", "Frontend dev", "1.5"],
      ["Offline delete: soft-delete entity in IDB; add DELETE_RECORDING to queue; cancel paired UPLOAD if pending", "Frontend", "Frontend dev", "0.5"],
      ["Add Idempotency-Key header to all upload and delete requests in api.ts", "Frontend + Backend", "Both", "0.5"],
      ["Server: idempotency_keys table migration + middleware to check/store keys on POST /audio, POST /video, DELETE /audio/{id}", "Backend", "Backend dev", "1.0"],
      ["UI sync status indicators: pending (⧖), uploading (spinner), synced (✔), failed (⚠️ + retry button) on RecordingRow", "Frontend", "Frontend dev", "1.0"],
      ["IDB storage quota check: warn at 500MB unsynced; catch write errors explicitly", "Frontend", "Frontend dev", "0.5"],
    ].map(([task, layer, who, days]) => new TableRow({ children: [
      new TableCell({borders:{top:thinBorder,bottom:thinBorder,left:thinBorder,right:thinBorder},margins:{top:70,bottom:70,left:100,right:100},width:{size:4560,type:WidthType.DXA},children:[new Paragraph({spacing:{before:0,after:0},children:[new TextRun({text:task,size:20,color:C.slate,font:"Calibri"})]})] }),
      new TableCell({borders:{top:thinBorder,bottom:thinBorder,left:thinBorder,right:thinBorder},shading:{fill:C.indigoLt,type:ShadingType.CLEAR},margins:{top:70,bottom:70,left:100,right:100},width:{size:1600,type:WidthType.DXA},children:[new Paragraph({spacing:{before:0,after:0},children:[new TextRun({text:layer,size:19,color:C.indigoDk,font:"Calibri"})]})] }),
      new TableCell({borders:{top:thinBorder,bottom:thinBorder,left:thinBorder,right:thinBorder},margins:{top:70,bottom:70,left:100,right:100},width:{size:1800,type:WidthType.DXA},children:[new Paragraph({spacing:{before:0,after:0},children:[new TextRun({text:who,size:19,color:C.slate,font:"Calibri"})]})] }),
      new TableCell({borders:{top:thinBorder,bottom:thinBorder,left:thinBorder,right:thinBorder},shading:{fill:C.greenLt,type:ShadingType.CLEAR},margins:{top:70,bottom:70,left:100,right:100},width:{size:1400,type:WidthType.DXA},children:[new Paragraph({alignment:AlignmentType.CENTER,spacing:{before:0,after:0},children:[new TextRun({text:days+" d",bold:true,size:20,color:C.green,font:"Calibri"})]})] }),
    ]})),
  ],
}));

children.push(h2("8.3 Phase 2 — Read Caching (5 days)"));
children.push(callout("Goal", "Teacher can browse previously loaded sessions and re-read AI outputs without network. Processing results (OCR, Whisper) are delivered via event polling instead of only on page reload.", C.amberLt, C.amber));
children.push(twoColTable([
  ["Task", "Days"],
  ["Cache session list in IDB entities.sessions. Show stale data with “Last updated X ago” note when offline.", "1.0"],
  ["Cache AI outputs in IDB entities.outputs when first loaded. Serve from cache when offline.", "1.0"],
  ["Backend: sync_events table migration + GET /sync/events?session_id=&since= endpoint", "1.0"],
  ["Frontend: event poller service (10s interval when visible) — merge events into IDB, update syncCursor", "1.0"],
  ["Backend: session versioning — add version column to sessions; check If-Match on PATCH; return 409 on mismatch", "1.0"],
], 7560, 1800));

children.push(h2("8.4 Phase 3 — Full Offline Create (5 days, optional)"));
children.push(callout("Gate", "Only build Phase 3 if teachers actively request the ability to create sessions without any network connection. This is an edge case — teachers typically set up sessions before arriving in the classroom.", C.roseLt, C.rose));
children.push(twoColTable([
  ["Task", "Days"],
  ["Client-side session create: generate UUID locally, store in IDB, queue CREATE_SESSION op. Sync engine sends to POST /sessions on reconnect.", "2.0"],
  ["Backend: inbox_items table + POST /sync/inbox endpoint. Background worker picks up queued ops and dispatches them. Writes results to sync_events.", "2.0"],
  ["Frontend: conflict resolution UI — toast with Keep Mine / Discard on 409 responses. Apply user’s choice and re-sync.", "1.0"],
], 7560, 1800));

children.push(pageBreak());

// ═══════════════════════════════════════════════════════════════════════════
// SECTION 9 — TECHNICAL IMPLEMENTATION DETAILS
// ═══════════════════════════════════════════════════════════════════════════
children.push(sectionHeader("9. Technical Implementation Details"));
children.push(spacer(120));

children.push(h2("9.1 Frontend: IDB Schema Changes"));
children.push(para([run("The existing "), code("offline-store.ts"), run(" manages a single "), code("pendingFrames"), run(" store. The expanded schema adds six stores. The IDB database version is bumped (e.g. from 1 to 2) to trigger the upgrade handler.")]));
children.push(para([bold("New stores in the upgrade handler:")]));
children.push(bullet([code("blobs"), run(" — keyPath: id. Stores raw audio/video Blob objects under a UUID key.")]));
children.push(bullet([code("entities.recordings"), run(" — keyPath: id. Indexes: sessionId, syncStatus. Stores recording metadata with local state.")]));
children.push(bullet([code("entities.sessions"), run(" — keyPath: id. Stores session list for offline browsing.")]));
children.push(bullet([code("entities.outputs"), run(" — keyPath: id, index: sessionId. Stores AI output JSON for offline reading.")]));
children.push(bullet([code("syncQueue"), run(" — keyPath: id. Indexes: status+nextRetryAt (compound), sessionId. The outbox.")]));
children.push(bullet([code("syncCursor"), run(" — keyPath: key. Single-row store. Key: ‘default’, value: ISO timestamp string of last received event.")]));

children.push(h2("9.2 Frontend: Sync Engine Changes"));
children.push(para([run("The existing "), code("sync-engine.ts"), run(" handles only frame uploads. It needs to be generalised to a dispatcher that handles all operation types.")]));
children.push(para([bold("Dispatcher pattern:")]));
children.push(twoColTable([
  ["Operation type", "Handler"],
  ["UPLOAD_FRAME", "Existing: read blob from pendingFrames, compress, POST /sessions/{id}/frames"],
  ["UPLOAD_AUDIO", "New: read blob from blobs store, POST /sessions/{id}/audio with FormData + Idempotency-Key header"],
  ["UPLOAD_VIDEO", "New: read blob from blobs store, POST /sessions/{id}/video with FormData + Idempotency-Key header"],
  ["DELETE_RECORDING", "New: DELETE /sessions/{id}/audio/{audio_id} with Idempotency-Key header"],
  ["CREATE_SESSION (Phase 3)", "New: POST /sessions with JSON body + Idempotency-Key header"],
], 2800, 6560));
children.push(para([run("The concurrency manager: maintain an array of "), code("inFlight"), run(" IDs (max 2). When an entry starts sending, add to inFlight. On complete (success or final failure), remove from inFlight. Pick next from queue only if inFlight.length < 2.")]));

children.push(h2("9.3 Frontend: api.ts Changes"));
children.push(para([run("The "), code("api.ts"), run(" fetch helper "), code("request<T>"), run(" must be extended to accept an optional "), code("idempotencyKey: string"), run(" parameter. When provided, it adds "), code("Idempotency-Key: {key}"), run(" to the request headers. The sync engine passes this key from the queue entry.")]));
children.push(para([run("The helper already correctly handles 204 No Content (returns undefined without calling res.json()). The 409 response from idempotency conflict must return the cached response body — the engine checks for 409 and treats it as success.")]));

children.push(h2("9.4 Backend: Idempotency Middleware"));
children.push(para([run("A FastAPI middleware (or dependency) checks the "), code("Idempotency-Key"), run(" header on incoming POST and DELETE requests. Implementation:")]));
children.push(numbered([run("Extract key from header. If absent, proceed normally (no idempotency enforcement).")]));
children.push(numbered([run("Query idempotency_keys WHERE key = ? and expires_at > now().")]));
children.push(numbered([run("If found: return Response(content=row.result_json, status_code=original_status_code). Request processing ends here.")]));
children.push(numbered([run("If not found: let route handler run. After response is generated, insert (key, type, session_id, result_json, created_at, expires_at=now()+7days) into idempotency_keys.")]));
children.push(para([run("The middleware stores the "), bold("full response body"), run(" in result_json. For audio uploads this includes the transcript, language, recording_number, etc. The client gets an identical response on retry.")]));

children.push(h2("9.5 Backend: New Database Migration"));
children.push(para("A single Alembic migration adds all Phase 1 server-side changes:"));
children.push(bullet([code("CREATE TABLE idempotency_keys (key VARCHAR(36) PRIMARY KEY, type VARCHAR(50), session_id UUID, result_json TEXT, created_at TIMESTAMP NOT NULL, expires_at TIMESTAMP NOT NULL)")]));
children.push(bullet([code("CREATE INDEX ix_idempotency_keys_expires_at ON idempotency_keys (expires_at)"), run(" — for the nightly cleanup job")]));
children.push(bullet([code("ALTER TABLE sessions ADD COLUMN version INTEGER NOT NULL DEFAULT 1"), run(" (Phase 2)")]));
children.push(bullet([code("ALTER TABLE session_audios ADD COLUMN version INTEGER NOT NULL DEFAULT 1"), run(" (Phase 2)")]));

children.push(h2("9.6 Existing Code Reuse"));
children.push(para("Phase 1 deliberately avoids introducing new server endpoints or infrastructure. Everything reuses what already exists:"));
children.push(twoColTable([
  ["Existing component", "How it is reused"],
  ["POST /sessions/{id}/audio", "Audio sync engine target. Add idempotency key check only. Whisper pipeline unchanged."],
  ["POST /sessions/{id}/video", "Video sync engine target. Add idempotency key check only. ffmpeg + Whisper pipeline unchanged."],
  ["DELETE /sessions/{id}/audio/{id}", "Delete sync engine target. Add idempotency key check only."],
  ["useSyncQueue hook", "Extended to expose per-recording sync status (not just frame counts)."],
  ["sync-engine.ts", "Dispatcher pattern added on top of existing frame upload logic."],
  ["RecordingRow component", "Extend to show syncStatus badge based on IDB entity state."],
  ["api.ts request<T> helper", "Add optional idempotencyKey parameter. Already handles 204. Add 409 pass-through."],
], 3000, 6360));

children.push(pageBreak());

// ═══════════════════════════════════════════════════════════════════════════
// SECTION 10 — RISK REGISTER
// ═══════════════════════════════════════════════════════════════════════════
children.push(sectionHeader("10. Risk Register"));
children.push(spacer(120));
children.push(new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [2800, 900, 1660, 4000],
  rows: [
    new TableRow({ children: [
      ...[["Risk",2800],["Likelihood",900],["Impact",1660],["Mitigation",4000]].map(([t,w])=>
        new TableCell({shading:{fill:C.indigoDk,type:ShadingType.CLEAR},borders:{top:noBorder,bottom:noBorder,left:noBorder,right:noBorder},margins:{top:80,bottom:80,left:100,right:100},width:{size:w,type:WidthType.DXA},children:[new Paragraph({spacing:{before:0,after:0},children:[new TextRun({text:t,bold:true,size:20,color:C.white,font:"Calibri"})]})]})
      )
    ]}),
    ...[
      ["IDB storage quota exceeded mid-recording", "Low", "Critical — data loss", "Check navigator.storage.estimate() before saving blob. Warn at 500MB. Surface quota errors immediately. Never silently discard."],
      ["Blob too large for IDB on low-end device", "Medium", "High — recording fails", "Implement chunked blob writes. Test on low-memory Android devices. Consider compressing audio before storing."],
      ["Same recording uploaded twice (no idempotency key)", "Low", "Medium — duplicate data", "Idempotency key is mandatory in the sync engine. Always generated before first upload attempt."],
      ["iOS Safari IDB reliability issues", "Medium", "High — queue data lost", "Test on Safari 16+. IDB is reliable on iOS 16+. Avoid IDB transactions that span multiple microtask checkpoints."],
      ["Network drops during blob upload — partial write on server", "Medium", "Medium — retry creates duplicate", "Server idempotency key prevents duplicate Whisper calls. File write is atomic (temp file rename). Safe."],
      ["Teacher clears browser data, deleting unsynced queue", "Low", "Critical — data loss", "Warn when unsynced data exists. Prompt to sync before clearing. Cannot prevent deliberate browser data clear."],
      ["Whisper transcription failure on queued audio", "Low", "Low — transcript missing, audio intact", "Audio file is saved by server even if Whisper fails. Teacher can see recording without transcript. Whisper can be retried server-side."],
    ].map(([risk, l, i, m]) => new TableRow({ children: [
      new TableCell({borders:{top:thinBorder,bottom:thinBorder,left:thinBorder,right:thinBorder},margins:{top:70,bottom:70,left:100,right:100},width:{size:2800,type:WidthType.DXA},children:[new Paragraph({spacing:{before:0,after:0},children:[new TextRun({text:risk,size:20,color:C.slate700,font:"Calibri"})]})] }),
      new TableCell({borders:{top:thinBorder,bottom:thinBorder,left:thinBorder,right:thinBorder},shading:{fill:l==="Low"?C.greenLt:l==="Medium"?C.amberLt:C.roseLt,type:ShadingType.CLEAR},margins:{top:70,bottom:70,left:100,right:100},width:{size:900,type:WidthType.DXA},children:[new Paragraph({alignment:AlignmentType.CENTER,spacing:{before:0,after:0},children:[new TextRun({text:l,bold:true,size:19,color:l==="Low"?C.green:l==="Medium"?C.amber:C.rose,font:"Calibri"})]})] }),
      new TableCell({borders:{top:thinBorder,bottom:thinBorder,left:thinBorder,right:thinBorder},margins:{top:70,bottom:70,left:100,right:100},width:{size:1660,type:WidthType.DXA},children:[new Paragraph({spacing:{before:0,after:0},children:[new TextRun({text:i,size:19,color:C.slate,font:"Calibri"})]})] }),
      new TableCell({borders:{top:thinBorder,bottom:thinBorder,left:thinBorder,right:thinBorder},margins:{top:70,bottom:70,left:100,right:100},width:{size:4000,type:WidthType.DXA},children:[new Paragraph({spacing:{before:0,after:0},children:[new TextRun({text:m,size:19,color:C.slate,font:"Calibri"})]})] }),
    ]})),
  ],
}));

children.push(pageBreak());

// ═══════════════════════════════════════════════════════════════════════════
// SECTION 11 — CLOUD HOSTING & DEPLOYMENT STRATEGY
// ═══════════════════════════════════════════════════════════════════════════
children.push(sectionHeader("11. Cloud Hosting & Deployment Strategy"));
children.push(spacer(120));

children.push(h2("11.1 Architecture Constraints"));
children.push(para("The ACI backend has one hard infrastructure constraint that drives all hosting decisions: ffmpeg is a native binary that must run in a persistent process. This eliminates serverless functions (Vercel Functions, Supabase Edge Functions, AWS Lambda) as candidates for the backend, because:"));
children.push(bullet([bold("ffmpeg is not installable in serverless runtimes"), run(" — they have read-only filesystems and no package manager at runtime.")]));
children.push(bullet([bold("Video processing is long-running"), run(" — Whisper transcription of a 30-minute class recording can take 30–60 seconds, exceeding the 30s function timeout on most serverless platforms.")]));
children.push(bullet([bold("PaddleOCR and Tesseract"), run(" — the OCR engines carry native compiled libraries that cannot be bundled into a serverless deployment ZIP.")]));
children.push(callout("Key constraint", "Backend must run in a container or VM with ffmpeg, Tesseract, and Python 3.11 installed. The frontend (Next.js) has no such constraint and deploys perfectly to Vercel with zero configuration.", C.amberLt, C.amber));

children.push(h2("11.2 Platform Comparison"));
children.push(spacer(80));
children.push(new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [2000, 2600, 2400, 2360],
  rows: [
    new TableRow({ children: [
      ...[["Component",2000],["Option A: Vercel + Fly.io",2600],["Option B: AWS EC2 + RDS",2400],["Option C: Railway (Full Stack)",2360]].map(([t,w]) =>
        new TableCell({shading:{fill:C.indigoDk,type:ShadingType.CLEAR},borders:{top:noBorder,bottom:noBorder,left:noBorder,right:noBorder},margins:{top:80,bottom:80,left:100,right:100},width:{size:w,type:WidthType.DXA},children:[new Paragraph({spacing:{before:0,after:0},children:[new TextRun({text:t,bold:true,size:19,color:C.white,font:"Calibri"})]})]}))
    ]}),
    ...[
      ["Frontend","Vercel (native Next.js)\n0.5 days","Vercel or CloudFront\n0.5 days","Vercel (free tier)\n0.5 days"],
      ["Backend","Fly.io container\n$5–10/mo · 1 day","EC2 t3.small + nginx\n~$20/mo · 1.5 days","Railway container\n$5/mo · 0.5 days"],
      ["Database","Supabase PostgreSQL\nFree tier · 0.5 days","AWS RDS PostgreSQL\n~$15/mo · 0.5 days","Railway PostgreSQL\nIncluded · 0.5 days"],
      ["File Storage","Supabase Storage or S3\n1 day","AWS S3 (pre-wired)\n0.5 days","S3 or Cloudflare R2\n1 day"],
      ["Redis / Queue","Upstash Redis (free)\n0.5 days","CELERY_ALWAYS_EAGER=true\n0.5 days","Railway Redis addon\n0.5 days"],
      ["CORS + health","Env var + /health done\n0.5 days","Same\n0.5 days","Same\n0.5 days"],
      ["Total effort","~4.5 days","~5 days","~4 days"],
      ["Monthly cost","~$10–15/mo","~$40–60/mo","~$15–25/mo"],
    ].map(([comp,...cols], ri) => new TableRow({ children: [
      new TableCell({borders:{top:thinBorder,bottom:thinBorder,left:thinBorder,right:thinBorder},shading:{fill:C.indigoLt,type:ShadingType.CLEAR},margins:{top:70,bottom:70,left:100,right:100},width:{size:2000,type:WidthType.DXA},children:[new Paragraph({spacing:{before:0,after:0},children:[new TextRun({text:comp,bold:true,size:19,color:C.indigoDk,font:"Calibri"})]})]}),
      ...cols.map((txt, ci) => new TableCell({borders:{top:thinBorder,bottom:thinBorder,left:thinBorder,right:thinBorder},shading:{fill:ri===6?C.greenLt:ri===7?C.amberLt:C.white,type:ShadingType.CLEAR},margins:{top:70,bottom:70,left:100,right:100},width:{size:[2600,2400,2360][ci],type:WidthType.DXA},children:[new Paragraph({spacing:{before:0,after:0},children:[new TextRun({text:txt.replace(/\n/g," · "),size:ri>=6?20:19,bold:ri>=6,color:ri===6?C.green:ri===7?C.amber:C.slate,font:"Calibri"})]})]})),
    ]})),
  ],
}));

children.push(h2("11.3 Recommended Architecture"));
children.push(para("The recommended starting point is Option A (Vercel + Fly.io + Supabase). It has the lowest monthly cost, the simplest developer experience, and the fastest time-to-production. The key advantage is that all three services have generous free tiers, making it viable for a pilot or early-stage deployment with zero infrastructure cost."));
children.push(twoColTable([
  ["Service", "Role and notes"],
  ["Vercel (frontend)", "Detects Next.js 16 automatically. Set NEXT_PUBLIC_API_URL=https://api.yourapp.fly.dev. Zero config required."],
  ["Fly.io (backend)", "fly launch in /backend — Fly reads the Dockerfile and fly.toml already added to the repo. Set secrets with fly secrets set DATABASE_URL=... OPENAI_API_KEY=... etc."],
  ["Supabase (database)", "Create a project → copy the postgres:// connection string → set as DATABASE_URL. The database_url validator in config.py auto-rewrites postgres:// to postgresql+asyncpg:// — no manual editing needed."],
  ["AWS S3 or Supabase Storage (files)", "Set USE_S3=true. Supabase Storage is S3-compatible: use its endpoint URL, region, and credentials in the same S3 settings. All audio, video, frame, and lesson plan uploads now go to the bucket."],
  ["Upstash Redis (optional)", "Only needed if Celery workers are active. Currently all background work uses FastAPI BackgroundTasks. Set CELERY_ALWAYS_EAGER=true and no Redis is required until Phase 2 of the offline work."],
], 2600, 6760));

children.push(h2("11.4 Code Changes Made (Portability Layer)"));
children.push(para("The following changes were made to the codebase in this session to enable zero-friction deployment to any of the three target platforms. All changes are backward-compatible — local development is unaffected."));
children.push(twoColTable([
  ["File changed", "What changed and why"],
  ["backend/Dockerfile (NEW)", "Multi-stage Python 3.11 image. Stage 1: pip install into builder. Stage 2: runtime with ffmpeg + Tesseract installed via apt-get. Non-root user (uid 1001). Entrypoint: alembic upgrade head && uvicorn. This is the prerequisite for all container deployments."],
  ["backend/fly.toml (NEW)", "Fly.io deployment configuration. References Dockerfile. Configures /health healthcheck, HTTPS redirect, and auto-stop for idle machines (saves cost on low-traffic deployments). Documents all required secrets."],
  ["backend/railway.toml (NEW)", "Railway deployment configuration. Reads PORT env var from Railway's runtime. Documents the DATABASE_URL auto-provision from Railway's PostgreSQL addon."],
  ["backend/.dockerignore (NEW)", "Excludes .venv, __pycache__, uploads/, dev.db, .env from the Docker build context. Keeps image size minimal and prevents secrets from being baked into the image."],
  ["backend/app/config.py", "Two additions: (1) _normalise_db_url() validator that rewrites postgres:// and postgresql:// to postgresql+asyncpg:// automatically — Supabase, Railway, Render, Neon all emit this format. (2) ALLOWED_ORIGINS env var + cors_origins property — comma-separated list of production origins."],
  ["backend/app/main.py", "CORSMiddleware now uses settings.cors_origins instead of hardcoded [\"*\"]. In production with ALLOWED_ORIGINS set, CORS is correctly restricted to known frontends."],
  ["backend/app/services/storage_service.py", "save_audio(), save_video(), and save_lesson_plan() now respect USE_S3=true. Previously they always wrote to local disk even when S3 was configured — this meant audio and video files were silently lost on container restarts in production. Now all file types route through S3 when USE_S3=true."],
], 3000, 6360));

children.push(h2("11.5 Deployment Step-by-Step"));
children.push(h3("Option A: Vercel (frontend) + Fly.io (backend) + Supabase (DB)"));
children.push(numbered([bold("Supabase: "), run("Create a new project at supabase.com. Go to Settings → Database → Connection string → URI. Copy the postgres:// string.")]));
children.push(numbered([bold("AWS S3 (or Supabase Storage): "), run("Create a bucket. Note the bucket name, region, access key, secret key.")]));
children.push(numbered([bold("Fly.io backend: "), run("cd backend && fly launch (first time) or fly deploy. Then: fly secrets set DATABASE_URL=postgres://... JWT_SECRET_KEY=... OPENAI_API_KEY=... USE_S3=true AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... S3_BUCKET=... ALLOWED_ORIGINS=https://yourapp.vercel.app ENVIRONMENT=production SKIP_AUTH=false")]));
children.push(numbered([bold("Vercel frontend: "), run("Import the repo in vercel.com. Set root directory = frontend. Add env var: NEXT_PUBLIC_API_URL = https://<your-fly-app>.fly.dev/v1. Deploy.")]));
children.push(numbered([bold("Alembic: "), run("Migrations run automatically on container start (alembic upgrade head is in the Dockerfile CMD). Verify with fly logs after deploy.")]));

children.push(h3("Option B: AWS EC2 + RDS"));
children.push(numbered([bold("RDS: "), run("Create a PostgreSQL 16 RDS instance. Note the endpoint. Connection string format: postgresql+asyncpg://aci:pass@<endpoint>:5432/aci")]));
children.push(numbered([bold("EC2: "), run("Launch a t3.small with Amazon Linux 2023. Install Docker: sudo yum install -y docker && sudo systemctl start docker.")]));
children.push(numbered([bold("Deploy: "), run("docker build -t aci-backend . && docker run -d --restart=unless-stopped -p 8000:8000 -e DATABASE_URL=... -e USE_S3=true ... aci-backend")]));
children.push(numbered([bold("nginx: "), run("Install nginx. Proxy /api → localhost:8000. Terminate SSL with Certbot (Let's Encrypt).")]));
children.push(numbered([bold("Vercel frontend: "), run("Same as Option A step 4. Point NEXT_PUBLIC_API_URL to the EC2 nginx endpoint.")]));

children.push(h2("11.6 Environment Variables Reference"));
children.push(twoColTable([
  ["Variable", "Required for production / Notes"],
  ["DATABASE_URL", "YES — postgres:// or postgresql:// format accepted; asyncpg prefix added automatically"],
  ["JWT_SECRET_KEY", "YES — long random string (openssl rand -hex 32)"],
  ["SKIP_AUTH", "NO — must be false in production (true = any request accepted)"],
  ["OPENAI_API_KEY", "YES (for AI features) — without this, placeholder outputs are returned"],
  ["USE_S3", "YES — set to true; containers lose local files on restart"],
  ["AWS_ACCESS_KEY_ID / SECRET", "YES when USE_S3=true — or use IAM instance role on EC2"],
  ["S3_BUCKET", "YES when USE_S3=true"],
  ["AWS_REGION", "YES when USE_S3=true — e.g. ap-south-1"],
  ["ALLOWED_ORIGINS", "YES — comma-separated list of your Vercel app URL(s)"],
  ["ENVIRONMENT", "YES — set to production"],
  ["REDIS_URL", "Optional — only needed if Celery workers are used; otherwise set CELERY_ALWAYS_EAGER=true"],
  ["CELERY_ALWAYS_EAGER", "Set to true in production if not running Celery workers (runs tasks inline)"],
], 3000, 6360));

children.push(pageBreak());

// ═══════════════════════════════════════════════════════════════════════════
// SECTION 12 — OFFLINE-FIRST: PRODUCT VALUE & BUSINESS JUSTIFICATION
// ═══════════════════════════════════════════════════════════════════════════
children.push(sectionHeader("12. Offline-First: Product Value & Business Justification"));
children.push(spacer(120));

children.push(h2("12.1 The Problem: Classroom Reality"));
children.push(para("ACI is designed for teachers in Indian schools — government schools, private schools, coaching centres — where WiFi reliability is not a given. The classroom environment has several structural networking problems:"));
children.push(twoColTable([
  ["Problem", "Real-world impact on ACI"],
  ["Shared school WiFi overloaded during class hours (100+ devices)", "Upload requests time out mid-recording. Teacher loses the recording."],
  ["Mobile data drops inside concrete school buildings", "4G/5G signal is intermittent, especially on lower floors or interior classrooms."],
  ["Network switches between WiFi and mobile mid-session", "TCP connection drops. MediaRecorder blob upload fails. Error shown to teacher at the worst possible moment — mid-class."],
  ["Government schools often have no WiFi at all", "Currently: ACI cannot be used. After offline: ACI captures everything, syncs later."],
  ["Rural/semi-urban school connectivity", "BSNL broadband: 2–10 Mbps shared across school. Video upload (50MB+) fails under load."],
], 3000, 6360));

children.push(h2("12.2 Value Add: What Offline Unlocks"));
children.push(callout("Core value statement", "Offline-first is not a technical feature. It is the difference between ACI being usable in 30% of Indian schools vs. 90% of Indian schools. The addressable market doubles when the app works without WiFi.", C.indigoLt, C.indigo));
children.push(spacer(80));

children.push(h3("12.2.1 Teacher Experience Before vs. After Offline"));
children.push(new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [4680, 4680],
  rows: [
    new TableRow({ children: [
      new TableCell({shading:{fill:C.roseLt,type:ShadingType.CLEAR},borders:{top:thinBorder,bottom:thinBorder,left:thinBorder,right:thinBorder},margins:{top:80,bottom:80,left:120,right:120},width:{size:4680,type:WidthType.DXA},children:[new Paragraph({spacing:{before:0,after:0},children:[new TextRun({text:"Before offline (today)",bold:true,size:21,color:C.rose,font:"Calibri"})]})]}),
      new TableCell({shading:{fill:C.greenLt,type:ShadingType.CLEAR},borders:{top:thinBorder,bottom:thinBorder,left:thinBorder,right:thinBorder},margins:{top:80,bottom:80,left:120,right:120},width:{size:4680,type:WidthType.DXA},children:[new Paragraph({spacing:{before:0,after:0},children:[new TextRun({text:"After offline (Phase 1)",bold:true,size:21,color:C.green,font:"Calibri"})]})]}),
    ]}),
    ...[
      ["Network drops mid-recording → recording is silently lost", "Network drops mid-recording → recording saved locally, syncs when back online"],
      ["Teacher must check if upload succeeded before ending class", "Teacher records, stops, sees sync badge — no mental overhead"],
      ["WiFi congestion during class = no captures at all", "Entire class captures locally regardless of network state"],
      ["School without WiFi = ACI cannot be used", "School without WiFi = ACI works fully; syncs at end of day on mobile data"],
      ["Upload failure error shown to teacher mid-explanation", "Teacher never sees upload errors during class — they happen silently later"],
      ["Students distracted while teacher retries uploads", "Class continues uninterrupted; sync happens in background"],
    ].map(([before, after]) => new TableRow({ children: [
      new TableCell({borders:{top:thinBorder,bottom:thinBorder,left:thinBorder,right:thinBorder},margins:{top:60,bottom:60,left:120,right:120},width:{size:4680,type:WidthType.DXA},children:[new Paragraph({spacing:{before:0,after:0},children:[new TextRun({text:before,size:20,color:C.slate,font:"Calibri"})]})] }),
      new TableCell({borders:{top:thinBorder,bottom:thinBorder,left:thinBorder,right:thinBorder},margins:{top:60,bottom:60,left:120,right:120},width:{size:4680,type:WidthType.DXA},children:[new Paragraph({spacing:{before:0,after:0},children:[new TextRun({text:after,size:20,color:C.slate,font:"Calibri"})]})] }),
    ]})),
  ],
}));

children.push(h3("12.2.2 Quantified Impact Estimate"));
children.push(twoColTable([
  ["Metric", "Estimate and basis"],
  ["Recording loss rate (today)", "Estimated 15–30% of recordings in poor-network schools fail to upload. Teacher is unaware. AI analysis quality degrades silently."],
  ["Recording loss rate (after offline)", "Target: 0%. All recordings captured locally. Sync failure is retried automatically. Teacher is never in data-loss mode."],
  ["Session completion rate", "Schools with no WiFi: currently 0% of sessions generate AI output (nothing uploads). After offline: 100% of sessions complete — sync happens after class on mobile data."],
  ["New addressable schools", "India has ~1.5M schools. Approximately 30% have reliable internet. Offline extends ACI to the remaining 70% — an ~2.3x expansion of the addressable market."],
  ["Teacher retention", "Losing a recording mid-class is a severe trust-breaking event. A teacher who loses data once typically stops using the tool. Offline eliminates this churn driver."],
  ["Admin confidence in AI outputs", "AI gap analysis quality depends directly on completeness of captured recordings. More recordings captured = better AI output = more school administrator trust."],
], 2600, 6760));

children.push(h2("12.3 Competitive Differentiation"));
children.push(para("Most EdTech tools assume reliable connectivity. This is a reasonable assumption for urban premium schools in the US or Europe. For the Indian mass market — where ACI is positioned — it is a product-breaking assumption."));
children.push(twoColTable([
  ["Competitor assumption", "ACI offline advantage"],
  ["Google Classroom / Microsoft Teams: require constant connectivity", "ACI captures data in any network condition. Teachers in rural schools can use ACI where Google Classroom fails."],
  ["Other classroom AI tools: cloud-first, fail silently offline", "ACI's offline mode is visible to the teacher: sync badges, pending counts, last-sync time. Teachers trust a tool that is honest about network state."],
  ["Manual tools (pen/notebook): work offline but produce no AI output", "ACI matches the reliability of pen and paper for capture, then adds AI analysis when network returns. This is the key proposition: zero capture friction, AI value added asynchronously."],
  ["Recording tools (voice memos): work offline but no structured output", "ACI offline capture feeds directly into the AI pipeline. The teacher does not need to take any extra step — sync happens automatically."],
], 3000, 6360));

children.push(h2("12.4 Business Value by Stakeholder"));
children.push(twoColTable([
  ["Stakeholder", "Value delivered by offline-first"],
  ["Classroom teacher", "Zero data loss. No anxiety about network during class. App works the same way in any school."],
  ["School administration", "More complete AI analysis (more captures → better gap analysis, quiz quality). Can deploy ACI in schools without WiFi infrastructure investment."],
  ["School district / government", "Can mandate ACI use across all schools including rural — not just WiFi-equipped schools. Uniform tool across the district."],
  ["ACI product team", "Offline removes the #1 support complaint (upload failures). Reduces churn. Unlocks growth in tier-2/tier-3 cities. Increases LTV of each school deployment."],
  ["Investors", "2.3x expansion of addressable market. Structural moat: competitors who don't invest in offline cannot serve the same schools. Network effects: more schools → more data → better AI models."],
], 2600, 6760));

children.push(h2("12.5 Offline as a Quality Signal"));
children.push(para("Offline-first architecture enforces disciplines that improve overall product quality, not just network resilience:"));
children.push(bullet([bold("Idempotency by default: "), run("Every API call must be safe to retry. This eliminates a class of data corruption bugs that are common in online-only apps (duplicate uploads, partial writes).")]));
children.push(bullet([bold("Explicit state management: "), run("The sync queue forces the app to model 'pending', 'sending', 'synced', 'failed' states explicitly. UI becomes clearer because these states are visible to the teacher — not hidden.")]));
children.push(bullet([bold("Resilient data model: "), run("Local-first IDs (client-generated UUIDs) mean the server is never the single source of truth for entity identity. This opens the door to multi-device collaboration later.")]));
children.push(bullet([bold("Better error UX: "), run("Online apps fail at the worst moment (mid-action). Offline apps fail at the best moment (during sync, in the background, when the teacher is not in the middle of teaching).")]));

children.push(h2("12.6 Phase 1 Offline: ROI Summary"));
children.push(twoColTable([
  ["Investment", "Return"],
  ["8 development days (Phase 1)", "Eliminates 100% of recording data loss in poor-network schools"],
  ["~$0 infrastructure cost added (IDB is free, same server endpoints)", "Unlocks deployment in ~70% of Indian schools currently blocked by network requirement"],
  ["2 additional backend changes (idempotency table, one migration)", "All API calls become retry-safe — improves reliability across the entire app, not just offline scenarios"],
  ["Sync status UI additions (badges, indicators)", "Increases teacher trust and transparency — visible network state reduces support tickets"],
  ["5 days (Phase 2) — session + output caching", "Teacher can review previous AI analysis between classes without network — reduces time-to-insight for lesson planning"],
], 3200, 6160));
children.push(callout("Bottom line", "8 days of development doubles the addressable school market, eliminates the #1 churn driver (recording data loss), and improves overall app reliability as a side effect. No other 8-day investment in the roadmap has comparable impact.", C.indigoLt, C.indigo));

// ── FOOTER note ──────────────────────────────────────────────────────────────
children.push(spacer(240));
children.push(divider());
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { before: 80, after: 0 },
  children: [new TextRun({ text: "AI Chalkboard Intelligence (ACI) · Design & Architecture Document · v1.1 · June 2026", size: 18, color: C.slate, font: "Calibri", italics: true })],
}));

// ─── Build document ──────────────────────────────────────────────────────────
const doc = new Document({
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [
          { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
          { level: 1, format: LevelFormat.BULLET, text: "◦", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 1080, hanging: 360 } } } },
        ],
      },
      {
        reference: "numbers",
        levels: [
          { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
        ],
      },
    ],
  },
  styles: {
    default: {
      document: { run: { font: "Calibri", size: 22 } },
    },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Calibri", color: C.indigoDk },
        paragraph: { spacing: { before: 360, after: 120 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Calibri", color: C.indigo },
        paragraph: { spacing: { before: 280, after: 80 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Calibri", color: C.slate700 },
        paragraph: { spacing: { before: 200, after: 60 }, outlineLevel: 2 } },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
      },
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: C.slate200, space: 1 } },
          spacing: { before: 0, after: 80 },
          children: [
            new TextRun({ text: "AI Chalkboard Intelligence (ACI) · Design & Architecture Document", size: 18, color: C.slate, font: "Calibri", italics: true }),
          ],
        })],
      }),
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.RIGHT,
          border: { top: { style: BorderStyle.SINGLE, size: 6, color: C.slate200, space: 1 } },
          spacing: { before: 80, after: 0 },
          children: [
            new TextRun({ text: "Page ", size: 18, color: C.slate, font: "Calibri" }),
            new TextRun({ children: [PageNumber.CURRENT], size: 18, color: C.slate, font: "Calibri" }),
            new TextRun({ text: " of ", size: 18, color: C.slate, font: "Calibri" }),
            new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 18, color: C.slate, font: "Calibri" }),
          ],
        })],
      }),
    },
    children,
  }],
});

const outPath = path.join(__dirname, "ACI_Design_Architecture.docx");
Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(outPath, buf);
  console.log("Written:", outPath, `(${(buf.length / 1024).toFixed(0)} KB)`);
}).catch(console.error);
