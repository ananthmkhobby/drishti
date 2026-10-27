/**
 * Drishti API client
 *
 * BASE URL resolution (in priority order):
 *   1. NEXT_PUBLIC_API_URL env var — explicit override (e.g. ngrok backend URL)
 *   2. /api/backend  — Next.js proxy rewrite (used when NEXT_PUBLIC_USE_PROXY=true)
 *      The proxy in next.config.ts rewrites /api/backend/* → http://localhost:8000/v1/*
 *      This lets an HTTPS ngrok frontend call an HTTP localhost backend safely.
 *   3. http://localhost:8000/v1  — default local dev fallback
 */

import { generateUUID } from "@/lib/uuid";

const BASE =
  process.env.NEXT_PUBLIC_API_URL ??
  (process.env.NEXT_PUBLIC_USE_PROXY === "true" ? "/api/backend" : "http://localhost:8000/v1");

// Dev teacher UUID — matches SKIP_AUTH=true backend default
export const DEV_TEACHER_ID = "00000000-0000-0000-0000-000000000001";

// ─── Generic fetch ──────────────────────────────────────────────────────────

async function request<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init.headers },
    ...init,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new APIError(res.status, err.error ?? "UNKNOWN", err.message ?? res.statusText);
  }
  if (res.status === 204 || res.headers.get("content-length") === "0") {
    return undefined as T;
  }
  return res.json() as Promise<T>;
}

export class APIError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string
  ) {
    super(message);
    this.name = "APIError";
  }
}

// ─── Types ───────────────────────────────────────────────────────────────────

export type SessionStatus = "active" | "completed" | "processing" | "ai_complete" | "failed";
export type SyncStatus = "pending" | "syncing" | "synced" | "failed";

export interface Session {
  session_id: string;
  teacher_id: string;
  subject: string | null;
  grade: string | null;
  title: string | null;
  instructor_name: string | null;
  board_type: string;
  capture_mode: string;
  capture_interval_sec: number;
  status: SessionStatus;
  sync_status: SyncStatus;
  // Set only for sessions that originated on an offline device via the
  // bulk sync endpoint — null for sessions created directly in the app.
  // This is what distinguishes a genuine offline-queue backlog from a
  // normal online session that just hasn't been marked "synced" yet.
  local_session_id: string | null;
  frame_count: number;
  started_at: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface CrossSessionSummaryEntry {
  session_id: string;
  subject: string | null;
  grade: string | null;
  title: string | null;
  instructor_name: string | null;
  has_notes: boolean;
}

export interface ConceptConnection {
  concept_a: string;
  concept_b: string;
  shared_principle: string;
  how_to_teach_it: string;
}

export interface CrossSessionLinkResponse {
  sessions: CrossSessionSummaryEntry[];
  unifying_theme: string;
  overall_summary: string;
  connections: ConceptConnection[];
  integrated_activity: string;
}

// ─── Guided Practice (ThinkStep) ────────────────────────────────────────────

export type AnswerDomain = "numeric" | "algebraic" | "conceptual" | "diagram" | "other";
export type PracticeQuestionStatus = "pending_review" | "approved" | "rejected" | "archived";
export type ValidationStatus =
  | "solved"
  | "valid_progress"
  | "alternative_valid_method"
  | "incomplete"
  | "arithmetic_slip"
  | "conceptual_misconception"
  | "ambiguous"
  | "unsupported";
export type StudentState =
  | "solved" | "progressing" | "uncertain" | "stuck" | "misconception" | "ambiguous" | "teacher_required";
export type AttemptStatus = "processing" | "awaiting_review" | "complete" | "failed";

export interface SolutionStep {
  step: string;
  description: string | null;
}
export interface SolutionApproach {
  label: string | null;
  steps: SolutionStep[];
}
export interface KnownMisconception {
  code: string;
  description: string;
  trigger_pattern: string | null;
}

export interface PracticeQuestion {
  question_id: string;
  session_id: string;
  version: number;
  subject: string | null;
  topic: string | null;
  skill_tag: string | null;
  difficulty: string | null;
  text: string;
  answer_domain: AnswerDomain;
  expected_solution_graph: SolutionApproach[] | null;
  final_answer: Record<string, unknown> | null;
  known_misconceptions: KnownMisconception[] | null;
  source: string;
  status: PracticeQuestionStatus;
  teacher_edited: boolean;
  created_at: string;
  updated_at: string;
}

export interface RecognizedStep {
  text: string;
  bbox: number[] | null;
  confidence: number;
}

export type PracticeInputType = "image" | "audio";

// The on-demand post-attempt correction panel — "conceptual error / perfect
// answer / tip" — deliberately separate from hint_text (see PracticeAttempt.review).
export interface AttemptReview {
  conceptual_error: string;
  perfect_answer: string[];
  tip: string;
}

export interface PracticeAttempt {
  attempt_id: string;
  question_id: string;
  // Only populated by endpoints that look it up (currently the station
  // timeline) — a station's history can span multiple questions if it was
  // ever reassigned, so cards need this to show which question a hint
  // actually belongs to.
  question_text?: string | null;
  session_id: string;
  station_id: string | null;
  attempt_no: number;
  student_label: string | null;
  input_type: PracticeInputType;
  image_path: string | null;
  audio_path: string | null;
  captured_at: string | null;
  capture_quality_status: string | null;
  capture_quality_reason: string | null;
  recognized_steps: RecognizedStep[] | null;
  recognition_confidence: number | null;
  normalized_step: Record<string, unknown> | null;
  gate_d_result: Record<string, unknown> | null;
  validation_status: ValidationStatus | null;
  validation_reason_code: string | null;
  // 0-based index into recognized_steps — which specific step the error was
  // first pinpointed at. Null when there's nothing to point at (valid
  // progress, still incomplete, or an ambiguous/unclassifiable capture).
  error_step_index: number | null;
  misconception_code: string | null;
  student_state: StudentState | null;
  // Productive-struggle step, before Gate G's hint — see api.explainAttempt/
  // skipExplanation. counter_question is set on a first genuine mistake;
  // hint_text stays null until student_explanation/explanation_outcome
  // are filled in.
  counter_question: string | null;
  student_explanation: string | null;
  explanation_outcome: "self_corrected" | "confirmed_misconception" | "unclear" | "skipped" | null;
  hint_level: number | null;
  hint_text: string | null;
  post_hint_outcome: string | null;
  latency_ms_breakdown: Record<string, number> | null;
  // Generated on demand via api.getAttemptReview — null until a student/
  // teacher explicitly asks for the full "what was wrong / what a perfect
  // answer looks like" correction, unlike hint_text which is generated
  // automatically as part of grading.
  review: AttemptReview | null;
  teacher_override: Record<string, unknown> | null;
  teacher_feedback: "approve" | "reject" | null;
  status: AttemptStatus;
  error_message: string | null;
  created_at: string;
}

export type StationStatus = "idle" | "capturing";
// "front": normal front/rear-facing camera propped up facing the page, no
// correction needed (default). "desk": an overhead/downward-facing camera
// mounted above the desk (e.g. fixed just below or above a laptop) — comes
// out rotated 90° and mirrored left-right relative to the page, corrected
// server-side before any vision call once set.
export type CameraMount = "front" | "desk";

export interface RadarAlert {
  id: string;
  question_id: string;
  question_text: string | null;
  topic: string | null;
  code: string;
  title: string;
  description: string | null;
  typical_work: string | null;
  desk_count: number;
  attempting_count: number;
  desks: { station_id: string; label: string }[];
  status: "new" | "dismissed" | "false_alarm" | "acted" | "resolved";
  created_at: string;
}

export interface RadarResponse {
  alerts: RadarAlert[];
  /** Desks stuck with no nameable misconception — shown for transparency, never alerted on. */
  unclassified: { question_id: string; question_text: string | null; desk_count: number }[];
}

export interface PracticeStation {
  station_id: string;
  session_id: string;
  label: string;
  active_question_id: string | null;
  capture_interval_sec: number;
  status: StationStatus;
  last_capture_at: string | null;
  teacher_note: string | null;
  camera_mount: CameraMount;
  created_at: string;
  updated_at: string;
  latest_attempt: PracticeAttempt | null;
  active_question_text: string | null;
}

export interface PracticeAttemptSummary {
  id: string;
  question_id: string;
  station_id: string | null;
  attempts_summarized: number;
  first_attempt_at: string;
  last_attempt_at: string;
  solved: boolean;
  revision_required: boolean;
  misconception_codes: Record<string, number> | null;
  hint_levels_seen: Record<string, number> | null;
  created_at: string;
}

export interface CreateSessionPayload {
  teacher_id: string;
  classroom_id?: string | null;
  subject?: string | null;
  grade?: string | null;
  title?: string | null;
  instructor_name?: string | null;
  board_type?: string;
  capture_mode?: string;
  capture_interval_sec?: number;
  client_session_id?: string;
}

export interface Frame {
  frame_id: string;
  session_id: string;
  sequence_no: number;
  local_frame_id: string;
  ocr_status: string;
  captured_at: string;
  image_size_kb: number;
}

export interface OCRRegion {
  type: string;
  bbox: number[] | null;
  content: string | null;
  confidence: number | null;
}

export interface OCRResult {
  frame_id: string;
  ocr_text: string;
  confidence: number;
  regions: OCRRegion[];
  engine_used: string;
  processed_at: string;
  privacy_blurred: number;        // 0 = no people detected, >0 = N regions blurred
  board_type: string;             // auto-detected: whiteboard|greenboard|blackboard|chalkboard
  board_confidence: number;       // 0–1 detection confidence
  board_detection_method: string; // calibrated|vision|yolo|contour|fallback
}

export interface QuizQuestion {
  id: string;
  type: "mcq" | "true_false";
  text: string;
  options: string[] | null;
  correct: number | boolean | null;
  bloom_level: string | null;
  topic: string | null;
  skill_tag: string | null;
  teacher_edited: boolean;
}

// ── TiQer-specific types ──────────────────────────────────────────────────────

export interface TiQerOption {
  key: "A" | "B" | "C" | "D";
  text: string;
}

export interface TiQerQuestion {
  question_id: string;
  sequence: number;
  type: "mcq" | "true_false";
  text: string;
  options: TiQerOption[] | null;
  correct_answer: string;  // "A"-"D" or "true"/"false"
  bloom_level: string;
  skill_tag: string;
  topic: string;
  grade: string;
  subject: string;
  difficulty: "easy" | "medium" | "hard";
}

export interface TiQerExportMetadata {
  generated_by: string;
  aci_version: string;
  bloom_distribution: Record<string, number>;
  mcq_count: number;
  true_false_count: number;
}

export interface TiQerExportPayload {
  export_id: string;
  schema_version: string;
  tiqer_class_id: string;
  session_id: string;
  exported_at: string;
  teacher_id: string;
  subject: string;
  grade: string;
  question_count: number;
  questions: TiQerQuestion[];
  metadata: TiQerExportMetadata;
}

export interface TiQerExportResponse {
  tiqer_session_id: string;
  status: string;
  question_count: number;
  exported_at: string;
  payload: TiQerExportPayload;
}

export interface OutputEntry {
  status: "pending" | "processing" | "ready" | "failed" | "partial";
  generated_at: string | null;
  data: Record<string, unknown> | null;
  url: string | null;
  tokens_used: number;
}

export interface SessionOutputs {
  session_id: string;
  outputs: Record<string, OutputEntry>;
  total_tokens: number;
}

export interface Job {
  job_id: string;
  type: string;
  status: string;
  progress: number;
  result_url: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface SyncStatusResponse {
  device_fingerprint: string;
  device_id: string | null;
  pending: number;
  uploading: number;
  done: number;
  failed: number;
  skipped: number;
  total: number;
  last_sync_at: string | null;
  health: "healthy" | "degraded" | "failing" | "unknown";
}

// ─── Report types ────────────────────────────────────────────────────────────

export interface SessionTimeSeries {
  date: string;   // YYYY-MM-DD
  count: number;
}

export interface SubjectCount {
  subject: string;
  count: number;
}

export interface BloomCount {
  bloom_level: string;
  count: number;
}

export interface SyncBreakdown {
  pending: number;
  syncing: number;
  synced: number;
  failed: number;
}

export interface TopicEntry {
  topic: string;
  frequency: number;
}

export interface MissingConceptItem {
  concept_id: string;
  concept: string;
  concept_type: string;
  description: string | null;
  session_id: string;
  session_subject: string | null;
  resolved: boolean;
  created_at: string;
}

export interface QuizSessionSummary {
  session_id: string;
  subject: string | null;
  grade: string | null;
  question_count: number;
  exported_to_tiqer: number;
  created_at: string;
}

export interface TeacherDashboard {
  teacher_id: string;
  sessions_conducted: number;
  topics_covered: number;
  ai_outputs_generated: number;
  tiqer_sessions: number;
  missing_concepts_flagged: number;
  pending_sync: number;
}

export interface TeacherReport {
  teacher_id: string;
  period_days: number;
  sessions_total: number;
  sessions_this_period: number;
  ai_outputs_total: number;
  ai_outputs_this_period: number;
  quizzes_generated: number;
  quizzes_exported_to_tiqer: number;
  topics_count: number;
  missing_concepts_total: number;
  missing_concepts_resolved: number;
  sync_pending: number;
  sync_failed: number;
  sync_completed: number;
  sessions_over_time: SessionTimeSeries[];
  subject_breakdown: SubjectCount[];
  topics_covered: TopicEntry[];
  bloom_distribution: BloomCount[];
  sync_breakdown: SyncBreakdown;
  recent_missing_concepts: MissingConceptItem[];
  quiz_sessions: QuizSessionSummary[];
}

export interface UnitSummary {
  subject: string;
  grade: string;
  session_count: number;
  first_date: string;
  last_date: string;
}

export interface UnitSessionEntry {
  session_id: string;
  date: string;
  title: string | null;
  topics_covered: string[];
  gaps: string[];
  suggested_next: string[];
}

export interface RecurringGap {
  concept: string;
  count: number;
}

export interface UnitDetail {
  subject: string;
  grade: string;
  sessions: UnitSessionEntry[];
  recurring_gaps: RecurringGap[];
  continue_from_here: string[];
}

export interface SessionReport {
  session_id: string;
  status: string;
  generated_at: string | null;
  headline: string;
  what_was_covered: string;
  how_it_went: string;
  highlights: string[];
  gaps: string[];
  next_class: string;
  sources: { board_frames: number; audio: boolean };
}

export interface TeacherUsageSummary {
  teacher_id: string;
  name: string;
  email: string;
  session_count: number;
  ai_outputs_count: number;
  tiqer_exports: number;
  subject_count: number;
  last_active: string | null;
  sync_health: "healthy" | "degraded" | "offline" | "unknown";
}

export interface AdminReport {
  school_id: string;
  school_name: string;
  period_days: number;
  total_sessions: number;
  sessions_this_period: number;
  total_teachers: number;
  active_teachers: number;
  total_ai_outputs: number;
  total_tiqer_exports: number;
  pending_sync_sessions: number;
  sessions_over_time: SessionTimeSeries[];
  subject_breakdown: SubjectCount[];
  teachers: TeacherUsageSummary[];
}

export interface SchoolSummary {
  school_id: string;
  name: string;
  district: string | null;
  state: string | null;
  total_sessions: number;
  active_teachers: number;
  last_activity: string | null;
  pending_sync: number;
  sync_health: string;
}

// ─── Lesson Plan types ───────────────────────────────────────────────────────

export interface LessonPlan {
  lesson_plan_id: string;
  session_id: string;
  file_type: "pdf" | "image";
  topics: string[];
  topic_count: number;
  raw_text_length: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface LessonPlanUploadResponse extends LessonPlan {}

export interface CoveredTopic {
  topic: string;
  evidence: string;
}

export interface PartialTopic {
  topic: string;
  covered_aspect: string;
  missing_aspect: string;
}

export interface LessonPlanCoverage {
  lesson_plan_topics: string[];
  covered: CoveredTopic[];
  partial: PartialTopic[];
  missing: string[];
  coverage_score: number;
  summary: string;
  suggestions: string;
}

// ─── Textbook types ───────────────────────────────────────────────────────

export type TextbookPedagogy = "standard" | "quest";
export type TextbookContentType = "textbook" | "concept_notes";
export type QuestPhase = "guess" | "investigate" | "observe" | "infer";

export interface TextbookChapterSummary {
  chapter_id: string;
  order_index: number;
  title: string;
  start_page: number;
  end_page: number;
  pedagogy: TextbookPedagogy;
  current_segment_index: number;
  segment_count: number;
  started: boolean;
  last_taught_at: string | null;
}

export interface TextbookDiagramSpec {
  diagram_type: "cycle" | "sequence";
  nodes: string[];
}

export interface TextbookChapterDetail extends TextbookChapterSummary {
  taught_log: string[];
  last_segment_text: string | null;
  is_last_segment: boolean;
  last_segment_figure_id: string | null;
  last_segment_figure_caption: string | null;
  last_segment_diagram_spec: TextbookDiagramSpec | null;
  last_segment_quest_phase: QuestPhase | null;
  // One of the app's supported locales ("en"|"hi"|"kn"|"te"|"mr"|"ta") when
  // the detected language matches, else null (language_name is still set).
  language_code: string | null;
  language_name: string | null;
  // Every segment generated so far, in order — lets the client offer a
  // "previous" control that steps back through what's already been taught,
  // including after a page reload, instead of only ever moving forward.
  segments: TeachSegmentResponse[];
}

export interface Textbook {
  textbook_id: string;
  session_id: string;
  title: string | null;
  status: "pending" | "processing" | "ready" | "failed";
  error_message: string | null;
  page_count: number | null;
  content_type: TextbookContentType;
  language_code: string | null;
  language_name: string | null;
  created_at: string | null;
  chapters?: TextbookChapterSummary[];
}

export interface TeachSegmentResponse {
  segment_index: number;
  segment_text: string;
  is_last_segment: boolean;
  figure_id: string | null;
  figure_caption: string | null;
  diagram_spec: TextbookDiagramSpec | null;
  quest_phase: QuestPhase | null;
}

export interface LocateChapterResponse {
  textbook_id: string;
  chapter_id: string;
  title: string;
}

export interface CheckUnderstandingResponse {
  question: string;
  options: string[];
  correct_index: number;
  explanation: string;
}

export interface RevisionRecapResponse {
  points: string[];
}

export interface AudioRecording {
  audio_id: string;
  recording_number: number;
  source: "audio" | "video";
  file_type: string;
  duration_sec: number | null;
  transcript: string | null;
  segments: { id: number; start: number; end: number; text: string }[];
  language: string | null;
  transcribed: boolean;
  whisper_tokens: number;
  created_at: string | null;
}

// Legacy alias kept for class-analysis page compat
export type AudioTranscript = AudioRecording;

export interface EngagementMetrics {
  total_duration_sec: number;
  silence_ratio: number;
  speech_density_wpm: number;
  question_count: number;
  liveness_score: number;
  engagement_curve: { minute: number; words: number; level: "high" | "medium" | "low" }[];
  high_engagement_minutes: number[];
  low_engagement_minutes: number[];
}

export interface SessionAudioList {
  session_id: string;
  recording_count: number;
  engagement: EngagementMetrics | null;
  recordings: AudioRecording[];
}

export interface AudienceMetricPayload {
  minute_number:  number;
  faces_detected: number;
  attention_pct:  number;
  hand_raises:    number;
  happy_pct?:      number;
  confused_pct?:   number;
  surprised_pct?:  number;
  disengaged_pct?: number;
}

export interface ZoneEmotions {
  happy: number;
  confused: number;
  surprised: number;
  disengaged: number;
  neutral: number;
}

export interface ZoneSummary {
  count: number;
  attention_pct: number;
  dominant_emotion: string;
  emotions: ZoneEmotions;
}

export interface ZoneData {
  front:  ZoneSummary;
  middle: ZoneSummary;
  back:   ZoneSummary;
}

export interface AudienceFaceResult {
  box: { x: number; y: number; w: number; h: number };
  zone: "front" | "middle" | "back";
  emotion: string;
  confidence: number;
  attentive: boolean;
}

export interface AudienceFrameResponse {
  minute_number:     number;
  faces_detected:    number;
  attention_pct:     number;
  dominant_emotion:  string;
  zone_summary:      ZoneData;
  emotion_breakdown: ZoneEmotions;
  faces:             AudienceFaceResult[];
}

export interface AudienceMetricPoint {
  minute_number:  number;
  faces_detected: number;
  attention_pct:  number;
  hand_raises:    number;
  happy_pct:      number;
  confused_pct:   number;
  surprised_pct:  number;
  disengaged_pct: number;
  zone_data:      ZoneData | null;
}

export interface AudienceMetricsList {
  session_id: string;
  minute_count: number;
  avg_attention_pct: number | null;
  metrics: AudienceMetricPoint[];
}

// ─── Absorption Map types ────────────────────────────────────────────────────

export interface AbsorptionFrame {
  frame_id: string;
  sequence_no: number;
  captured_at: string | null;
  minute: number;
  ocr_preview: string | null;
  attention_pct: number | null;
  confused_pct: number | null;
  surprised_pct: number | null;
  absorption_level: "high" | "medium" | "low" | "unknown";
}

export interface AbsorptionMapResponse {
  session_id: string;
  has_audience_data: boolean;
  total_frames: number;
  avg_attention_pct: number | null;
  high_count: number;
  medium_count: number;
  low_count: number;
  frames: AbsorptionFrame[];
}

export interface AbsorptionRevisionItem {
  topic: string;
  summary: string;
  detail?: string;
}

export interface AbsorptionRevisionSection {
  level: "high" | "medium" | "low" | "unknown";
  heading: string;
  items: AbsorptionRevisionItem[];
}

export interface AbsorptionMapAI {
  revision_sections: AbsorptionRevisionSection[];
  insight: string;
  replan_suggestion: string;
}

export interface AudioUploadResponse {
  audio_id: string;
  session_id: string;
  recording_number: number;
  duration_sec: number | null;
  transcript: string | null;
  segment_count: number;
  language: string | null;
  transcribed: boolean;
}

export interface VideoUploadResponse {
  video_id: string;
  duration_sec: number | null;
  frame_count: number;
  transcript: string | null;
  transcribed: boolean;
  language: string | null;
  recording_number: number;
}

export interface VideoRecording {
  audio_id: string;
  recording_number: number;
  source: "video";
  file_type: string;
  duration_sec: number | null;
  transcribed: boolean;
  transcript: string | null;
  language: string | null;
  segment_count: number;
}

export interface VideoAnalysis {
  session_id: string;
  video_recording_count: number;
  total_frames_in_session: number;
  frame_interval_sec: number;
  recordings: VideoRecording[];
  has_transcripts: boolean;
}

export interface ConceptCoverageEntry {
  topic: string;
  session_count: number;
}

export interface CSRReport {
  program_id: string;
  program_name: string;
  period_days: number;
  total_schools: number;
  total_sessions: number;
  sessions_this_period: number;
  total_teachers: number;
  active_teachers: number;
  teacher_adoption_rate: number;
  total_topics_covered: number;
  connectivity_failure_rate: number;
  sessions_over_time: SessionTimeSeries[];
  schools: SchoolSummary[];
  concept_coverage: ConceptCoverageEntry[];
}

// ─── Voice TTS streaming playback ───────────────────────────────────────────
//
// /voice/speak now streams (see backend/app/routers/voice.py) instead of
// sending the whole MP3 at once — measured against the real OpenAI API,
// audio starts arriving noticeably before the clip finishes generating, and
// that gap only grows with longer answers (the textbook chapter reader's
// narration can run to several sentences). Feeding fetch's own progressive
// ReadableStream into a MediaSource lets an <audio> element start playing
// off the first chunk instead of waiting for res.blob() to buffer the
// entire response first — genuinely faster, not just a UI trick.
function appendSourceBufferChunk(sourceBuffer: SourceBuffer, chunk: Uint8Array): Promise<void> {
  return new Promise((resolve, reject) => {
    function onUpdateEnd() {
      sourceBuffer.removeEventListener("updateend", onUpdateEnd);
      resolve();
    }
    sourceBuffer.addEventListener("updateend", onUpdateEnd);
    try {
      sourceBuffer.appendBuffer(chunk as BufferSource);
    } catch (err) {
      sourceBuffer.removeEventListener("updateend", onUpdateEnd);
      reject(err instanceof Error ? err : new Error(String(err)));
    }
  });
}

/**
 * Starts TTS playback as soon as the first audio chunk arrives, rather than
 * waiting for the whole clip. Returns an <audio> element already playing
 * (or about to be, once the browser's own buffering settles) — same
 * disposal contract as the old blob-based helper: revoke `audio.src` via
 * URL.revokeObjectURL once playback ends.
 *
 * Falls back to the old buffer-the-whole-thing approach on any browser
 * without MediaSource/mp3 support — this app's real target (Chromium
 * kiosk) has had both for years, but this keeps a dev-machine Safari tab
 * working too instead of throwing outright.
 */
async function streamSpeechToAudio(text: string, instructions?: string): Promise<HTMLAudioElement> {
  const canStream = typeof MediaSource !== "undefined" && MediaSource.isTypeSupported("audio/mpeg");
  if (!canStream) {
    const blob = await api.voiceSpeak(text, instructions);
    return new Audio(URL.createObjectURL(blob));
  }

  const res = await fetch(`${BASE}/voice/speak`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, instructions }),
  });
  if (!res.ok || !res.body) {
    const err = await res.json().catch(() => ({}));
    throw new APIError(res.status, err.error ?? "TTS_ERROR", err.message ?? res.statusText);
  }

  const mediaSource = new MediaSource();
  const audio = new Audio();
  audio.src = URL.createObjectURL(mediaSource);
  const reader = res.body.getReader();

  await new Promise<void>((resolveFirstChunk, rejectFirstChunk) => {
    mediaSource.addEventListener("sourceopen", () => {
      let sourceBuffer: SourceBuffer;
      try {
        sourceBuffer = mediaSource.addSourceBuffer("audio/mpeg");
      } catch (err) {
        rejectFirstChunk(err instanceof Error ? err : new Error(String(err)));
        return;
      }
      let gotFirstChunk = false;

      async function pump() {
        try {
          const { done, value } = await reader.read();
          if (done) {
            if (mediaSource.readyState === "open") mediaSource.endOfStream();
            return;
          }
          await appendSourceBufferChunk(sourceBuffer, value);
          if (!gotFirstChunk) { gotFirstChunk = true; resolveFirstChunk(); }
          pump();
        } catch (err) {
          if (!gotFirstChunk) rejectFirstChunk(err instanceof Error ? err : new Error(String(err)));
        }
      }
      pump();
    }, { once: true });
  });

  return audio;
}

/**
 * Streams the next teaching segment (NDJSON — see teach-next-stream's own
 * docstring on the backend for the exact line shapes) instead of waiting
 * for the whole ~5-10s generation before showing anything. `onDelta` fires
 * with each new chunk of lesson text as it arrives — call it to update the
 * on-screen text live instead of only once at the end. Resolves with the
 * same shape the non-streaming teachNextSegment returns, once the "done"
 * line arrives (which only happens after the backend has actually
 * committed the segment to the database — the resolved value is never a
 * preview, only the real, saved result).
 */
async function teachNextSegmentStream(
  textbookId: string,
  chapterId: string,
  onDelta: (text: string) => void,
): Promise<TeachSegmentResponse> {
  const res = await fetch(`${BASE}/textbooks/${textbookId}/chapters/${chapterId}/teach-next-stream`, {
    method: "POST",
  });
  if (!res.ok || !res.body) {
    const err = await res.json().catch(() => ({}));
    throw new APIError(res.status, err.error ?? "SEGMENT_GENERATION_FAILED", err.message ?? res.statusText);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (value) buffer += decoder.decode(value, { stream: true });
    // NDJSON: each complete line (ending in \n) is one JSON object; a line
    // split across two reader chunks stays in `buffer` until it's whole.
    let newlineIdx: number;
    while ((newlineIdx = buffer.indexOf("\n")) !== -1) {
      const line = buffer.slice(0, newlineIdx);
      buffer = buffer.slice(newlineIdx + 1);
      if (!line.trim()) continue;
      const item = JSON.parse(line) as
        | { type: "delta"; text: string }
        | ({ type: "done" } & TeachSegmentResponse)
        | { type: "error"; message: string };
      if (item.type === "delta") {
        onDelta(item.text);
      } else if (item.type === "done") {
        return item;
      } else {
        throw new APIError(502, "SEGMENT_GENERATION_FAILED", item.message);
      }
    }
    if (done) break;
  }
  // Stream ended without ever sending a "done" line — a genuine backend
  // bug (or the connection dropping mid-stream), not something a retry
  // inside this function should paper over; the caller already has
  // retry/error UI for teachNextSegment failures.
  throw new APIError(502, "SEGMENT_GENERATION_FAILED", "The connection ended before the segment finished generating.");
}

// ─── Sessions ────────────────────────────────────────────────────────────────

export const api = {
  // Sessions
  getSessions: (teacherId: string) =>
    request<{ sessions: Session[]; total: number }>(
      `/sessions?teacher_id=${teacherId}&limit=50`
    ),

  getSession: (id: string) =>
    request<Session>(`/sessions/${id}`),

  crossSessionLinks: (sessionIds: string[]) =>
    request<CrossSessionLinkResponse>("/sessions/cross-session-links", {
      method: "POST",
      body: JSON.stringify({ session_ids: sessionIds }),
    }),

  createSession: (payload: CreateSessionPayload) =>
    request<{ session_id: string; status: string; created_at: string }>(
      "/sessions",
      { method: "POST", body: JSON.stringify(payload) }
    ),

  patchSession: (id: string, patch: Partial<Pick<Session, "status" | "subject" | "grade" | "title" | "instructor_name">>) =>
    request<Session>(`/sessions/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  deleteSession: (id: string) =>
    fetch(`${BASE}/sessions/${id}`, { method: "DELETE" }).then(async (res) => {
      // 204 = deleted, 404 = already gone — both are fine, remove from UI
      if (res.status === 204 || res.status === 404) return;
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new APIError(res.status, err.error ?? "DELETE_ERROR", err.message ?? res.statusText);
      }
    }),

  reprocessOCR: (sessionId: string) =>
    request<{ queued: number; session_id: string; message: string }>(
      `/sessions/${sessionId}/reprocess-ocr`,
      { method: "POST" }
    ),

  // Frames
  getFrames: (sessionId: string) =>
    request<{ frames: Frame[]; total: number }>(
      `/sessions/${sessionId}/frames`
    ),

  uploadFrame: (sessionId: string, formData: FormData) =>
    fetch(`${BASE}/sessions/${sessionId}/frames`, {
      method: "POST",
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new APIError(res.status, err.error ?? "UPLOAD_ERROR", err.message ?? res.statusText);
      }
      return res.json() as Promise<{ frame_id: string; status: string }>;
    }),

  getOCR: (frameId: string) =>
    request<OCRResult>(`/frames/${frameId}/ocr`),

  retryOCR: (frameId: string) =>
    request<{ queued: boolean }>(`/frames/${frameId}/ocr/retry`, { method: "POST" }),

  // Wake word — the backend's on-device "Hey XP" detector holds the Pi's
  // only microphone continuously, which fights the browser's own mic
  // recording for the same hardware. These bracket every real recording
  // so the two never contend (see app/services/wake_word_service.py).
  // Best-effort: a failure here shouldn't block the recording itself, so
  // callers should swallow rejections rather than surface them.
  pauseWakeWord: () => request<void>("/wake-word/pause", { method: "POST" }),
  resumeWakeWord: () => request<void>("/wake-word/resume", { method: "POST" }),

  // AI Outputs
  getOutputs: (sessionId: string) =>
    request<SessionOutputs>(`/sessions/${sessionId}/outputs`),

  getQuiz: (sessionId: string) =>
    request<{ session_id: string; questions: QuizQuestion[] }>(
      `/sessions/${sessionId}/outputs/quiz`
    ),

  getSessionReport: (sessionId: string) =>
    request<SessionReport>(`/sessions/${sessionId}/session-report`),

  triggerGeneration: (sessionId: string, outputs?: string[]) =>
    request<{ job_id: string; status: string; estimated_sec: number }>(
      `/sessions/${sessionId}/generate`,
      {
        method: "POST",
        body: JSON.stringify(
          outputs ? { outputs } : {}
        ),
      }
    ),

  exportToTiQer: (sessionId: string, tiQerClassId: string, scheduleAt?: string) =>
    request<TiQerExportResponse>(
      `/sessions/${sessionId}/outputs/quiz/export-tiqer`,
      {
        method: "POST",
        body: JSON.stringify({
          tiqer_class_id: tiQerClassId,
          ...(scheduleAt ? { schedule_at: scheduleAt } : {}),
        }),
      }
    ),

  /** GET the TiQer JSON payload — pass download=true to trigger browser download. */
  getTiQerPreview: (sessionId: string, tiQerClassId = "PREVIEW") =>
    request<TiQerExportPayload>(
      `/sessions/${sessionId}/outputs/quiz/tiqer-preview?tiqer_class_id=${encodeURIComponent(tiQerClassId)}`
    ),

  /**
   * Triggers a browser file download of the TiQer JSON by navigating to the
   * download endpoint.  Uses a direct window.location approach so the browser
   * handles the Content-Disposition header.
   */
  downloadTiQerJson: (sessionId: string, tiQerClassId = "PREVIEW") => {
    const url = `${BASE}/sessions/${sessionId}/outputs/quiz/tiqer-preview`
      + `?tiqer_class_id=${encodeURIComponent(tiQerClassId)}&download=true`;
    const a = document.createElement("a");
    a.href = url;
    a.download = "";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  },

  // Jobs
  getJob: (jobId: string) =>
    request<Job>(`/jobs/${jobId}`),

  // Sync
  getSyncStatus: (fingerprint: string) =>
    request<SyncStatusResponse>(`/sync/status/${fingerprint}`),

  // ── Reports ───────────────────────────────────────────────────────────────

  /** Compact summary widget — sessions, topics, AI outputs, sync, etc. */
  getTeacherDashboard: (teacherId: string) =>
    request<TeacherDashboard>(`/dashboard/teacher/${teacherId}`),

  /**
   * Full teacher report.
   * @param period Look-back window in days: 7 | 30 | 90 | 365
   */
  getTeacherReport: (teacherId: string, period = 30) =>
    request<TeacherReport>(`/dashboard/teacher/${teacherId}/report?period=${period}`),

  getTeacherUnits: (teacherId: string) =>
    request<UnitSummary[]>(`/dashboard/teacher/${teacherId}/units`),

  getTeacherUnitDetail: (teacherId: string, subject: string, grade: string) =>
    request<UnitDetail>(
      `/dashboard/teacher/${teacherId}/units/${encodeURIComponent(subject)}/${encodeURIComponent(grade)}`
    ),

  /** Admin school-level compact summary. */
  getAdminDashboard: (schoolId: string) =>
    request<{ school_id: string; total_sessions: number; active_teachers: number;
              total_ai_outputs: number; total_tiqer_exports: number;
              pending_sync_sessions: number }>(`/dashboard/admin/${schoolId}`),

  /** Full admin report with teacher list and time-series. */
  getAdminReport: (schoolId: string, period = 30) =>
    request<AdminReport>(`/dashboard/admin/${schoolId}/report?period=${period}`),

  /** Per-teacher usage list for admin view. */
  getAdminTeachers: (schoolId: string) =>
    request<TeacherUsageSummary[]>(`/dashboard/admin/${schoolId}/teachers`),

  /** CSR/program compact summary. */
  getCSRDashboard: (programId: string) =>
    request<{ program_id: string; total_schools: number; total_sessions: number;
              active_teachers: number; total_topics_covered: number;
              connectivity_failure_rate: number }>(`/dashboard/csr/${programId}`),

  /** Full CSR report with school list and concept coverage. */
  getCSRReport: (programId: string, period = 30) =>
    request<CSRReport>(`/dashboard/csr/${programId}/report?period=${period}`),

  /** School list for CSR view. */
  getCSRSchools: (programId: string, period = 30) =>
    request<SchoolSummary[]>(`/dashboard/csr/${programId}/schools?period=${period}`),

  // ─── Lesson Plan ───────────────────────────────────────────────────────────

  getLessonPlan: (sessionId: string) =>
    request<LessonPlan>(`/sessions/${sessionId}/lesson-plan`),

  // ─── Textbook ────────────────────────────────────────────────────────────

  listTextbooks: (sessionId: string) =>
    request<{ textbooks: Textbook[] }>(`/sessions/${sessionId}/textbooks`),

  getTextbook: (textbookId: string) =>
    request<Textbook>(`/textbooks/${textbookId}`),

  deleteTextbook: (textbookId: string) =>
    fetch(`${BASE}/textbooks/${textbookId}`, { method: "DELETE" }).then(async (res) => {
      if (res.status === 204 || res.status === 404) return;
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new APIError(res.status, err.error ?? "DELETE_ERROR", err.message ?? res.statusText);
      }
    }),

  getTextbookChapter: (textbookId: string, chapterId: string) =>
    request<TextbookChapterDetail>(`/textbooks/${textbookId}/chapters/${chapterId}`),

  teachNextSegment: (textbookId: string, chapterId: string) =>
    request<TeachSegmentResponse>(`/textbooks/${textbookId}/chapters/${chapterId}/teach-next`, {
      method: "POST",
    }),

  teachNextSegmentStream,

  checkUnderstanding: (textbookId: string, chapterId: string) =>
    request<CheckUnderstandingResponse>(`/textbooks/${textbookId}/chapters/${chapterId}/check-understanding`, {
      method: "POST",
    }),

  reviseChapter: (textbookId: string, chapterId: string) =>
    request<RevisionRecapResponse>(`/textbooks/${textbookId}/chapters/${chapterId}/revise`, {
      method: "POST",
    }),

  locateChapter: (sessionId: string, query: string) =>
    request<LocateChapterResponse>(`/sessions/${sessionId}/textbooks/locate-chapter`, {
      method: "POST",
      body: JSON.stringify({ query }),
    }),

  // ─── Audio ─────────────────────────────────────────────────────────────────

  getAudio: (sessionId: string) =>
    request<SessionAudioList>(`/sessions/${sessionId}/audio`),

  uploadAudio: (sessionId: string, blob: Blob, filename = "recording.webm"): Promise<AudioUploadResponse> => {
    const formData = new FormData();
    formData.append("file", blob, filename);
    return fetch(`${BASE}/sessions/${sessionId}/audio`, {
      method: "POST",
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new APIError(res.status, err.error ?? "UPLOAD_ERROR", err.message ?? res.statusText);
      }
      return res.json() as Promise<AudioUploadResponse>;
    });
  },

  deleteAudio: (sessionId: string, audioId: string) =>
    request<void>(`/sessions/${sessionId}/audio/${audioId}`, { method: "DELETE" }),

  retryTranscription: (sessionId: string, audioId: string) =>
    request<{ transcribed: boolean; transcript: string | null; language: string | null; segment_count: number }>(
      `/sessions/${sessionId}/audio/${audioId}/transcribe`,
      { method: "POST" }
    ),

  // ─── Video ────────────────────────────────────────────────────────────────

  uploadVideo: (sessionId: string, blob: Blob, filename = "recording.webm"): Promise<VideoUploadResponse> => {
    const form = new FormData();
    form.append("file", blob, filename);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3 * 60 * 1000); // 3 min
    return fetch(`${BASE}/sessions/${sessionId}/video`, {
      method: "POST",
      body: form,
      signal: controller.signal,
    }).then(async (res) => {
      clearTimeout(timeout);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new APIError(res.status, err.error ?? "UPLOAD_ERROR", err.message ?? res.statusText);
      }
      return res.json() as Promise<VideoUploadResponse>;
    }).catch((err) => {
      clearTimeout(timeout);
      throw err;
    });
  },

  /**
   * Chunked video upload — splits the blob into CHUNK_SIZE pieces, uploads
   * each sequentially, then calls assemble.  Suitable for large recordings.
   * onProgress receives 0-100 as each chunk completes.
   */
  uploadVideoChunked: async (
    sessionId: string,
    blob: Blob,
    onProgress?: (pct: number) => void,
    filename = "recording.webm",
  ): Promise<VideoUploadResponse> => {
    const CHUNK_SIZE = 5 * 1024 * 1024; // 5 MB per chunk
    const totalChunks = Math.max(1, Math.ceil(blob.size / CHUNK_SIZE));
    const uploadId = generateUUID();
    const contentType = blob.type || "video/webm";

    const headers: Record<string, string> = { "x-teacher-id": DEV_TEACHER_ID };

    for (let i = 0; i < totalChunks; i++) {
      const chunk = blob.slice(i * CHUNK_SIZE, (i + 1) * CHUNK_SIZE);
      const form = new FormData();
      form.append("file", chunk, filename);

      const url =
        `${BASE}/sessions/${sessionId}/video/chunks` +
        `?upload_id=${uploadId}&chunk_index=${i}&total_chunks=${totalChunks}`;

      const res = await fetch(url, { method: "POST", headers, body: form });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new APIError(res.status, err.error ?? "CHUNK_ERROR", `Chunk ${i + 1}/${totalChunks} failed`);
      }
      onProgress?.(Math.round(((i + 1) / totalChunks) * 85));
    }

    // Assemble
    const assembleUrl =
      `${BASE}/sessions/${sessionId}/video/chunks/${uploadId}/assemble` +
      `?total_chunks=${totalChunks}&content_type=${encodeURIComponent(contentType)}`;
    const assembleRes = await fetch(assembleUrl, { method: "POST", headers });
    if (!assembleRes.ok) {
      const err = await assembleRes.json().catch(() => ({}));
      throw new APIError(assembleRes.status, err.error ?? "ASSEMBLE_ERROR", err.message ?? assembleRes.statusText);
    }
    onProgress?.(100);
    return assembleRes.json() as Promise<VideoUploadResponse>;
  },

  getVideoAnalysis: (sessionId: string) =>
    request<VideoAnalysis>(`/sessions/${sessionId}/video-analysis`),

  // ─── Audience metrics ─────────────────────────────────────────────────────

  postAudienceMetric: (sessionId: string, payload: AudienceMetricPayload) =>
    request<{ metric_id: string; minute_number: number; attention_pct: number }>(
      `/sessions/${sessionId}/audience-metrics`,
      { method: "POST", body: JSON.stringify(payload) }
    ),

  /**
   * POST a JPEG/PNG canvas snapshot to the backend for RetinaFace + DeepFace analysis.
   * Returns per-face zone breakdown + emotion data. The backend also upserts the
   * AudienceMetric row, so no separate postAudienceMetric call is needed.
   */
  postAudienceFrame: (sessionId: string, blob: Blob, minuteNumber: number): Promise<AudienceFrameResponse> => {
    const form = new FormData();
    form.append("file", blob, "frame.jpg");
    form.append("minute_number", String(minuteNumber));
    return fetch(`${BASE}/sessions/${sessionId}/audience-frame`, {
      method: "POST",
      headers: { "x-teacher-id": DEV_TEACHER_ID },
      body: form,
    }).then(async (res) => {
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new APIError(res.status, err.error ?? "FRAME_ERROR", err.message ?? res.statusText);
      }
      return res.json() as Promise<AudienceFrameResponse>;
    });
  },

  getAudienceMetrics: (sessionId: string) =>
    request<AudienceMetricsList>(`/sessions/${sessionId}/audience-metrics`),

  // ─── Translation ──────────────────────────────────────────────────────────

  translateTexts: (texts: string[], target_language: string): Promise<{ translations: string[]; target_language: string }> =>
    request("/translate", {
      method: "POST",
      body: JSON.stringify({ texts, target_language }),
    }),

  // ─── Absorption Map ───────────────────────────────────────────────────────

  getAbsorptionMap: (sessionId: string) =>
    request<AbsorptionMapResponse>(`/sessions/${sessionId}/absorption-map`),

  // ─── Lesson Plan ───────────────────────────────────────────────────────────

  uploadLessonPlan: (sessionId: string, file: File): Promise<LessonPlanUploadResponse> => {
    const formData = new FormData();
    formData.append("file", file);
    return fetch(`${BASE}/sessions/${sessionId}/lesson-plan`, {
      method: "POST",
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new APIError(res.status, err.error ?? "UPLOAD_ERROR", err.message ?? res.statusText);
      }
      return res.json() as Promise<LessonPlanUploadResponse>;
    });
  },

  uploadTextbook: (
    sessionId: string, file: File, title?: string, contentType: TextbookContentType = "textbook",
  ): Promise<Textbook> => {
    const formData = new FormData();
    formData.append("file", file);
    if (title) formData.append("title", title);
    formData.append("content_type", contentType);
    return fetch(`${BASE}/sessions/${sessionId}/textbooks`, {
      method: "POST",
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new APIError(res.status, err.error ?? "UPLOAD_ERROR", err.message ?? res.statusText);
      }
      return res.json() as Promise<Textbook>;
    });
  },

  // ─── Voice Assistant / Classroom Brain ─────────────────────────────────────

  voiceTranscribe: (blob: Blob, filename = "command.webm"): Promise<{ transcript: string }> => {
    const formData = new FormData();
    formData.append("audio", blob, filename);
    // The backend now bounds its own OpenAI/local-whisper calls, but a
    // client-side ceiling too means a genuinely dead connection (not a
    // slow response, no response at all) still reliably recovers instead
    // of leaving "Thinking…" up indefinitely with nothing to abort it.
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 45 * 1000);
    return fetch(`${BASE}/voice/transcribe`, {
      method: "POST",
      body: formData,
      signal: controller.signal,
    }).then(async (res) => {
      clearTimeout(timeout);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new APIError(res.status, err.error ?? "VOICE_ERROR", err.message ?? res.statusText);
      }
      return res.json() as Promise<{ transcript: string }>;
    }).catch((err) => {
      clearTimeout(timeout);
      throw err;
    });
  },

  /** Returns an MP3 Blob, or throws if TTS is unavailable (caller should fall back to browser speechSynthesis). */
  voiceSpeak: (text: string, instructions?: string): Promise<Blob> =>
    fetch(`${BASE}/voice/speak`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, instructions }),
    }).then((res) => {
      if (!res.ok) throw new APIError(res.status, "TTS_ERROR", res.statusText);
      return res.blob();
    }),

  /**
   * Preferred over voiceSpeak for anything actually played back — starts
   * audio on the first streamed chunk instead of waiting for the whole
   * clip. See streamSpeechToAudio above for why this matters.
   */
  streamSpeechToAudio,

  voiceCommand: (blob: Blob, filename = "command.webm", transcriptHint?: string): Promise<VoiceCommandResponse> => {
    const formData = new FormData();
    formData.append("audio", blob, filename);
    if (transcriptHint !== undefined) formData.append("transcript_hint", transcriptHint);
    // Chains transcription + intent classification + (for a question) a
    // brain-answer call, each individually bounded server-side but adding
    // up — 90s covers that legitimate worst case while still giving a
    // dead connection a reliable way to recover. See voiceTranscribe above.
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 90 * 1000);
    return fetch(`${BASE}/voice/command`, {
      method: "POST",
      body: formData,
      signal: controller.signal,
    }).then(async (res) => {
      clearTimeout(timeout);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new APIError(res.status, err.error ?? "VOICE_ERROR", err.message ?? res.statusText);
      }
      return res.json() as Promise<VoiceCommandResponse>;
    }).catch((err) => {
      clearTimeout(timeout);
      throw err;
    });
  },

  // Guided Practice (ThinkStep)
  generatePracticeQuestions: (sessionId: string, count: number = 3) =>
    request<{ questions: PracticeQuestion[]; total: number }>(
      `/sessions/${sessionId}/practice-questions/generate`,
      { method: "POST", body: JSON.stringify({ count }) }
    ),

  generatePracticeQuestionsFromTopic: (sessionId: string, subject: string, topic: string, count: number = 3) =>
    request<{ questions: PracticeQuestion[]; total: number }>(
      `/sessions/${sessionId}/practice-questions/generate-from-topic`,
      { method: "POST", body: JSON.stringify({ subject, topic, count }) }
    ),

  getPracticeQuestions: (sessionId: string, status?: PracticeQuestionStatus) =>
    request<{ questions: PracticeQuestion[]; total: number }>(
      `/sessions/${sessionId}/practice-questions${status ? `?status=${status}` : ""}`
    ),

  updatePracticeQuestion: (
    questionId: string,
    patch: Partial<{
      text: string;
      subject: string;
      topic: string;
      difficulty: string;
      answer_domain: AnswerDomain;
      expected_solution_graph: SolutionApproach[];
      known_misconceptions: KnownMisconception[];
      status: PracticeQuestionStatus;
    }>
  ) =>
    request<PracticeQuestion>(`/practice-questions/${questionId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  createPracticeAttempt: (questionId: string, formData: FormData) =>
    fetch(`${BASE}/practice-questions/${questionId}/attempts`, {
      method: "POST",
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new APIError(res.status, err.error ?? "UPLOAD_ERROR", err.message ?? res.statusText);
      }
      return res.json() as Promise<PracticeAttempt>;
    }),

  getPracticeAttempt: (attemptId: string) =>
    request<PracticeAttempt>(`/practice-attempts/${attemptId}`),

  getQuestionAttempts: (questionId: string) =>
    request<{ attempts: PracticeAttempt[]; total: number }>(
      `/practice-questions/${questionId}/attempts`
    ),

  getSessionPracticeAttempts: (sessionId: string) =>
    request<{ attempts: PracticeAttempt[]; total: number }>(
      `/sessions/${sessionId}/practice-attempts`
    ),

  submitAttemptFeedback: (attemptId: string, feedback: "approve" | "reject", note?: string) =>
    request<PracticeAttempt>(`/practice-attempts/${attemptId}/feedback`, {
      method: "PATCH",
      body: JSON.stringify({
        teacher_feedback: feedback,
        ...(note ? { teacher_override: { action: feedback, note } } : {}),
      }),
    }),

  /** Permanently deletes one attempt (and its stored image/audio) — unlike
   * a local "Clear" view filter, this is real and has no undo. */
  deleteAttempt: (attemptId: string) =>
    fetch(`${BASE}/practice-attempts/${attemptId}`, { method: "DELETE" }).then(async (res) => {
      if (res.status === 204 || res.status === 404) return;
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new APIError(res.status, err.error ?? "DELETE_ERROR", err.message ?? res.statusText);
      }
    }),

  // Guided Practice — stations (per-student/notebook periodic capture)
  createStation: (sessionId: string, label: string, activeQuestionId?: string, captureIntervalSec = 20) =>
    request<PracticeStation>(`/sessions/${sessionId}/practice-stations`, {
      method: "POST",
      body: JSON.stringify({
        label,
        active_question_id: activeQuestionId ?? null,
        capture_interval_sec: captureIntervalSec,
      }),
    }),

  getStations: (sessionId: string) =>
    request<{ stations: PracticeStation[]; total: number }>(`/sessions/${sessionId}/practice-stations`),

  getStation: (stationId: string) =>
    request<PracticeStation>(`/practice-stations/${stationId}`),

  updateStation: (
    stationId: string,
    patch: Partial<{
      label: string;
      active_question_id: string;
      capture_interval_sec: number;
      status: StationStatus;
      teacher_note: string;
      camera_mount: CameraMount;
    }>
  ) =>
    request<PracticeStation>(`/practice-stations/${stationId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  deleteStation: (stationId: string) =>
    fetch(`${BASE}/practice-stations/${stationId}`, { method: "DELETE" }).then(async (res) => {
      if (res.status === 204 || res.status === 404) return;
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new APIError(res.status, err.error ?? "DELETE_ERROR", err.message ?? res.statusText);
      }
    }),

  createStationAttempt: (stationId: string, formData: FormData) =>
    fetch(`${BASE}/practice-stations/${stationId}/attempts`, {
      method: "POST",
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new APIError(res.status, err.error ?? "UPLOAD_ERROR", err.message ?? res.statusText);
      }
      return res.json() as Promise<PracticeAttempt>;
    }),

  getStationAttempts: (stationId: string) =>
    request<{ attempts: PracticeAttempt[]; total: number }>(`/practice-stations/${stationId}/attempts`),

  // Consolidated record of whatever's been pruned from the raw attempt
  // history (see backend practice_service.prune_old_attempts_with_summary
  // — only the most recent 10 attempts per question are kept as full
  // rows/images; older ones are folded into one of these first). The
  // "what happened before the last 10" view.
  getStationAttemptSummaries: (stationId: string) =>
    request<{ summaries: PracticeAttemptSummary[]; total: number }>(`/practice-stations/${stationId}/attempt-summaries`),

  /**
   * Generates (or returns the already-cached) full correction panel for one
   * finished attempt — see PracticeAttempt.review. Unlike hint_text, this
   * is never called automatically; only when a student/teacher explicitly
   * expands the "Details" view on a pinpointed mistake.
   */
  getAttemptReview: (attemptId: string) =>
    request<PracticeAttempt>(`/practice-attempts/${attemptId}/review`, { method: "POST" }),

  /**
   * The "productive struggle" step's response half — a student explaining
   * their own reasoning after a first mistake, before any hint (see
   * PracticeAttempt.counter_question). Server transcribes, probes whether
   * the explanation shows self-correction, and returns the updated
   * attempt (hint_text is now either encouragement or a real hint).
   */
  explainAttempt: (attemptId: string, audioBlob: Blob) => {
    const formData = new FormData();
    formData.append("audio", audioBlob, "explanation.webm");
    return fetch(`${BASE}/practice-attempts/${attemptId}/explain`, {
      method: "POST",
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new APIError(res.status, err.error ?? "EXPLAIN_ERROR", err.message ?? res.statusText);
      }
      return res.json() as Promise<PracticeAttempt>;
    });
  },

  /** A student who doesn't want to (or can't) respond to the counter-question. */
  skipExplanation: (attemptId: string) =>
    request<PracticeAttempt>(`/practice-attempts/${attemptId}/skip-explanation`, { method: "POST" }),

  /** Cross-desk misconception alerts for a session (teacher screen only). */
  getSessionRadar: (sessionId: string) =>
    request<RadarResponse>(`/sessions/${sessionId}/practice/radar`),

  updateRadarAlert: (alertId: string, status: "dismissed" | "false_alarm" | "acted") =>
    request<RadarAlert>(`/radar-alerts/${alertId}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),

  /**
   * Station-scoped analogs of a session's generate_notes/generate_quiz —
   * "generate notes"/"generate quiz" said at a student's own station
   * (see ClassroomBrain.tsx's onPracticeStationPage branch) means a recap
   * of THIS station's attempt history, not the whole class's lecture.
   * Synchronous, unlike the session-wide job-queue version — one
   * station's digest is small enough not to need it.
   */
  generateStationNotes: (stationId: string) =>
    request<{ notes: string }>(`/practice-stations/${stationId}/generate-notes`, { method: "POST" }),

  generateStationQuiz: (stationId: string) =>
    request<{ questions: string[] }>(`/practice-stations/${stationId}/generate-quiz`, { method: "POST" }),

  /**
   * A student asking the Classroom Brain about their station's active
   * question. Scoped server-side to that one question — `declined: true`
   * means the message wasn't related to it and `reply` is a polite
   * redirect, not real help.
   */
  askBrain: (stationId: string, message: string) =>
    request<{ reply: string; declined: boolean }>(`/practice-stations/${stationId}/ask`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),

  /**
   * One turn of Learning mode's AI Tutor — a live voice+vision conversation
   * (see backend/app/services/practice_service.py::tutor_turn). Stateless
   * server-side: `history` is the conversation so far, resent every call —
   * the caller (practice-station page) is what accumulates it.
   */
  tutorTurn: (stationId: string, audioBlob: Blob, imageBlob: Blob | null, history: { role: "student" | "tutor"; text: string }[]) => {
    const formData = new FormData();
    formData.append("audio", audioBlob, "tutor-turn.webm");
    if (imageBlob) formData.append("image", imageBlob, "frame.jpg");
    formData.append("history", JSON.stringify(history));
    return fetch(`${BASE}/practice-stations/${stationId}/tutor-turn`, {
      method: "POST",
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new APIError(res.status, err.error ?? "TUTOR_ERROR", err.message ?? res.statusText);
      }
      return res.json() as Promise<{ transcript: string; reply: string }>;
    });
  },

  /**
   * One wide photo covering several students (names handwritten above/
   * beside their own work) — detects each name, crops their work out, and
   * creates (or reuses) one Station + one attempt per student, all graded
   * through the normal background pipeline. See BatchScanResponse.
   */
  batchScanStudents: (sessionId: string, questionId: string, blob: Blob, filename = "batch-scan.jpg") => {
    const formData = new FormData();
    formData.append("image", blob, filename);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 60 * 1000);
    return fetch(`${BASE}/sessions/${sessionId}/practice-questions/${questionId}/batch-scan`, {
      method: "POST",
      body: formData,
      signal: controller.signal,
    }).then(async (res) => {
      clearTimeout(timeout);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new APIError(res.status, err.error ?? "BATCH_SCAN_ERROR", err.message ?? res.statusText);
      }
      return res.json() as Promise<BatchScanResponse>;
    }).catch((err) => {
      clearTimeout(timeout);
      throw err;
    });
  },
};

export interface BatchScanResult {
  name: string;
  station_id: string;
  attempt_id: string;
  is_new_station: boolean;
}

export interface BatchScanResponse {
  detected: BatchScanResult[];
  skipped: string[];
}

export interface BrainAnswer {
  answer: string;
  topics_covered: string[];
  pending_concepts: string[];
  suggested_next: string;
  source: "local" | "cloud" | "none";
  needs_clarification: boolean;
}

export interface VoiceCommandResponse {
  transcript: string;
  intent: string;
  params: Record<string, unknown>;
  source: "local" | "cloud" | "none";
  brain_answer: BrainAnswer | null;
}

/**
 * Returns the URL for the stored frame image (potentially blurred if people were detected).
 * Use as `<img src={getFrameImageUrl(sessionId, frameId)}>` — no fetch needed.
 */
export function getFrameImageUrl(sessionId: string, frameId: string): string {
  return `${BASE}/sessions/${sessionId}/frames/${frameId}/image`;
}

/**
 * Returns the URL for a cropped board-diagram image (extracted during OCR).
 * Use as `<img src={getDiagramImageUrl(sessionId, frameId, index)}>`.
 */
export function getDiagramImageUrl(sessionId: string, frameId: string, index: number): string {
  return `${BASE}/sessions/${sessionId}/frames/${frameId}/diagrams/${index}/image`;
}

/**
 * Returns the URL for a stored ThinkStep guided-practice attempt capture.
 * Use as `<img src={getPracticeAttemptImageUrl(attemptId)}>`.
 */
export function getPracticeAttemptImageUrl(attemptId: string): string {
  return `${BASE}/practice-attempts/${attemptId}/image`;
}

/**
 * Returns the URL for a textbook diagram — cropped from the uploaded PDF
 * and content-safety-approved server-side (see backend textbook_service).
 * Use as `<img src={getTextbookFigureUrl(textbookId, figureId)}>`.
 */
export function getTextbookFigureUrl(textbookId: string, figureId: string): string {
  return `${BASE}/textbooks/${textbookId}/figures/${figureId}/image`;
}

/** For an attempt with input_type "audio" — use as `<audio src={...} controls>`. */
export function getPracticeAttemptAudioUrl(attemptId: string): string {
  return `${BASE}/practice-attempts/${attemptId}/audio`;
}

// ─── SWR fetcher ─────────────────────────────────────────────────────────────

export const swrFetcher = (url: string) =>
  fetch(url).then((r) => {
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  });
