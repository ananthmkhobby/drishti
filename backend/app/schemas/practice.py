import uuid
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, field_serializer

AnswerDomain = Literal["numeric", "algebraic", "conceptual", "diagram", "other"]
QuestionStatus = Literal["pending_review", "approved", "rejected", "archived"]
ValidationStatus = Literal[
    "valid_progress",
    "alternative_valid_method",
    "incomplete",
    "arithmetic_slip",
    "conceptual_misconception",
    "ambiguous",
    "unsupported",
]
StudentState = Literal[
    "progressing", "uncertain", "stuck", "misconception", "ambiguous", "teacher_required"
]
AttemptStatus = Literal["processing", "awaiting_review", "complete", "failed"]
PostHintOutcome = Literal["resolved", "still_stuck", "escalated_to_teacher"]


def _ser_dt(v: datetime | None) -> str | None:
    if v is None:
        return None
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.isoformat().replace("+00:00", "Z")


# ─── Practice questions ─────────────────────────────────────────────────────


class SolutionStep(BaseModel):
    step: str
    description: str | None = None


class SolutionApproach(BaseModel):
    label: str | None = None
    steps: list[SolutionStep]


class KnownMisconception(BaseModel):
    code: str
    description: str
    trigger_pattern: str | None = None


class PracticeQuestionGenerateRequest(BaseModel):
    # How many questions to draft from this session's board OCR content.
    count: int = Field(default=3, ge=1, le=10)


class PracticeQuestionGenerateFromTopicRequest(BaseModel):
    # Generate without any prior board capture — teacher just names the
    # subject and chapter/topic directly.
    subject: str = Field(min_length=1, max_length=100)
    topic: str = Field(min_length=1, max_length=255)
    count: int = Field(default=3, ge=1, le=10)


class PracticeQuestionUpdate(BaseModel):
    text: str | None = None
    subject: str | None = None
    topic: str | None = None
    skill_tag: str | None = None
    difficulty: str | None = None
    answer_domain: AnswerDomain | None = None
    expected_solution_graph: list[SolutionApproach] | None = None
    final_answer: dict | None = None
    known_misconceptions: list[KnownMisconception] | None = None
    status: QuestionStatus | None = None


class PracticeQuestionResponse(BaseModel):
    question_id: uuid.UUID
    session_id: uuid.UUID
    version: int
    subject: str | None
    topic: str | None
    skill_tag: str | None
    difficulty: str | None
    text: str
    answer_domain: str
    expected_solution_graph: list | None
    final_answer: dict | None
    known_misconceptions: list | None
    source: str
    status: str
    teacher_edited: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("created_at", "updated_at", mode="plain", when_used="json")
    def _ser(self, v: datetime) -> str:
        return _ser_dt(v)

    @classmethod
    def from_orm(cls, obj):
        return cls(
            question_id=obj.id,
            session_id=obj.session_id,
            version=obj.version,
            subject=obj.subject,
            topic=obj.topic,
            skill_tag=obj.skill_tag,
            difficulty=obj.difficulty,
            text=obj.text,
            answer_domain=obj.answer_domain,
            expected_solution_graph=obj.expected_solution_graph,
            final_answer=obj.final_answer,
            known_misconceptions=obj.known_misconceptions,
            source=obj.source,
            status=obj.status,
            teacher_edited=obj.teacher_edited,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


class PracticeQuestionListResponse(BaseModel):
    questions: list[PracticeQuestionResponse]
    total: int


# ─── Practice attempts ──────────────────────────────────────────────────────


class RecognizedStep(BaseModel):
    text: str
    bbox: list[float] | None = None  # [x0, y0, x1, y1] normalized 0-1
    confidence: float


class PracticeAttemptCreate(BaseModel):
    question_id: uuid.UUID
    student_label: str | None = None


class TeacherOverride(BaseModel):
    action: str
    note: str | None = None


class PracticeAttemptFeedback(BaseModel):
    teacher_feedback: Literal["approve", "reject"]
    teacher_override: TeacherOverride | None = None


class PracticeAttemptResponse(BaseModel):
    attempt_id: uuid.UUID
    question_id: uuid.UUID
    # Denormalized at response-build time (see from_orm's question_text
    # param) — a station's timeline can span multiple questions if its
    # assignment was ever changed, and a hint/result shown with no
    # indication of which question it's actually about reads as "mixed up"
    # even when each one is computed correctly (reported 2026-09-19).
    # Optional/None for callers that don't look it up (e.g. immediately
    # after creating an attempt, before it's even processed).
    question_text: str | None = None
    session_id: uuid.UUID
    station_id: uuid.UUID | None
    attempt_no: int
    student_label: str | None
    input_type: str
    image_path: str | None
    audio_path: str | None
    captured_at: datetime | None
    capture_quality_status: str | None
    capture_quality_reason: str | None
    recognized_steps: list | None
    recognition_confidence: float | None
    normalized_step: dict | None
    gate_d_result: dict | None
    validation_status: str | None
    validation_reason_code: str | None
    error_step_index: int | None
    misconception_code: str | None
    student_state: str | None
    hint_level: int | None
    hint_text: str | None
    post_hint_outcome: str | None
    latency_ms_breakdown: dict | None
    teacher_override: dict | None
    teacher_feedback: str | None
    status: str
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("captured_at", "created_at", mode="plain", when_used="json")
    def _ser(self, v: datetime | None) -> str | None:
        return _ser_dt(v)

    @classmethod
    def from_orm(cls, obj, question_text: str | None = None):
        return cls(
            attempt_id=obj.id,
            question_id=obj.question_id,
            question_text=question_text,
            session_id=obj.session_id,
            station_id=obj.station_id,
            attempt_no=obj.attempt_no,
            student_label=obj.student_label,
            # Defensive: existing rows from before this column existed may
            # have it NULL at the raw data level (the ORM's default="image"
            # only applies to new inserts, not backfilled on old rows by
            # whatever process added the column) — never let that 500 the
            # whole list/refresh endpoint over an old capture.
            input_type=obj.input_type or "image",
            image_path=obj.image_path,
            audio_path=obj.audio_path,
            captured_at=obj.captured_at,
            capture_quality_status=obj.capture_quality_status,
            capture_quality_reason=obj.capture_quality_reason,
            recognized_steps=obj.recognized_steps,
            recognition_confidence=obj.recognition_confidence,
            normalized_step=obj.normalized_step,
            gate_d_result=obj.gate_d_result,
            validation_status=obj.validation_status,
            validation_reason_code=obj.validation_reason_code,
            error_step_index=obj.error_step_index,
            misconception_code=obj.misconception_code,
            student_state=obj.student_state,
            hint_level=obj.hint_level,
            hint_text=obj.hint_text,
            post_hint_outcome=obj.post_hint_outcome,
            latency_ms_breakdown=obj.latency_ms_breakdown,
            teacher_override=obj.teacher_override,
            teacher_feedback=obj.teacher_feedback,
            status=obj.status,
            error_message=obj.error_message,
            created_at=obj.created_at,
        )


class PracticeAttemptListResponse(BaseModel):
    attempts: list[PracticeAttemptResponse]
    total: int


class PracticeAttemptSummaryResponse(BaseModel):
    id: uuid.UUID
    question_id: uuid.UUID
    station_id: uuid.UUID | None
    attempts_summarized: int
    first_attempt_at: datetime
    last_attempt_at: datetime
    solved: bool
    revision_required: bool
    misconception_codes: dict | None
    hint_levels_seen: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("first_attempt_at", "last_attempt_at", "created_at", mode="plain", when_used="json")
    def _ser(self, v: datetime | None) -> str | None:
        return _ser_dt(v)


class PracticeAttemptSummaryListResponse(BaseModel):
    summaries: list[PracticeAttemptSummaryResponse]
    total: int


# ─── Practice stations (per-student/notebook capture channel) ──────────────

StationStatus = Literal["idle", "capturing"]
# "front": normal front/rear-facing camera, no correction needed (default).
# "desk": overhead/downward-facing camera mounted above the desk — comes
# out rotated 90° + mirrored left-right relative to the page, corrected
# server-side before any vision call (see practice_engine.apply_mount_correction).
CameraMount = Literal["front", "desk"]


class PracticeStationCreate(BaseModel):
    label: str
    active_question_id: uuid.UUID | None = None
    capture_interval_sec: int = Field(default=10, ge=5, le=120)
    camera_mount: CameraMount = "front"


class PracticeStationUpdate(BaseModel):
    label: str | None = None
    active_question_id: uuid.UUID | None = None
    capture_interval_sec: int | None = Field(default=None, ge=5, le=120)
    status: StationStatus | None = None
    teacher_note: str | None = None
    camera_mount: CameraMount | None = None


class PracticeStationResponse(BaseModel):
    station_id: uuid.UUID
    session_id: uuid.UUID
    label: str
    active_question_id: uuid.UUID | None
    capture_interval_sec: int
    status: StationStatus
    last_capture_at: datetime | None
    teacher_note: str | None
    camera_mount: CameraMount
    created_at: datetime
    updated_at: datetime

    # Denormalized snapshot of the latest attempt for this station — lets the
    # teacher's folder-grid dashboard render current state/thumbnail without
    # a second round-trip per station.
    latest_attempt: PracticeAttemptResponse | None = None
    active_question_text: str | None = None

    model_config = {"from_attributes": True}

    @field_serializer("last_capture_at", "created_at", "updated_at", mode="plain", when_used="json")
    def _ser(self, v: datetime | None) -> str | None:
        return _ser_dt(v)

    @classmethod
    def from_orm(cls, obj, latest_attempt=None, active_question_text: str | None = None):
        return cls(
            station_id=obj.id,
            session_id=obj.session_id,
            label=obj.label,
            active_question_id=obj.active_question_id,
            capture_interval_sec=obj.capture_interval_sec,
            status=obj.status,
            last_capture_at=obj.last_capture_at,
            teacher_note=obj.teacher_note,
            camera_mount=obj.camera_mount,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
            latest_attempt=PracticeAttemptResponse.from_orm(latest_attempt) if latest_attempt else None,
            active_question_text=active_question_text,
        )


class PracticeStationListResponse(BaseModel):
    stations: list[PracticeStationResponse]
    total: int


class BatchScanResult(BaseModel):
    name: str
    station_id: uuid.UUID
    attempt_id: uuid.UUID
    is_new_station: bool


class BatchScanResponse(BaseModel):
    detected: list[BatchScanResult]
    # Names the vision model reported but whose crop failed decode/was too
    # small to be usable — surfaced so the teacher knows to re-photograph
    # that one student rather than silently losing them.
    skipped: list[str]


# ─── Classroom Brain chat — a student asking about their current question ──


class PracticeChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)


class PracticeChatResponse(BaseModel):
    reply: str
    # True when the student's message wasn't about the active question and
    # the reply is a polite decline rather than actual help — lets the
    # frontend style that turn differently (e.g. a softer/amber tone).
    declined: bool


# ─── Station-scoped notes/quiz — voice-command analogs of a session's
# generate_notes/generate_quiz, scoped to one station's attempt history ────


class StationNotesResponse(BaseModel):
    notes: str


class StationQuizResponse(BaseModel):
    questions: list[str]


# ─── AI Tutor (Learning mode) — a live voice+vision conversation ───────────
# Stateless server-side: the client resends the running turn history each
# call (same shape as a normal chat API) rather than the server tracking a
# session id — see practice_service.tutor_turn().


class TutorHistoryTurn(BaseModel):
    role: str = Field(pattern="^(student|tutor)$")
    text: str


class PracticeTutorTurnResponse(BaseModel):
    transcript: str  # what the student's audio was heard as, for the UI to show
    reply: str
