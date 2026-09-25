import uuid
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel

OutputType = Literal[
    "notes",
    "summary",
    "quiz",
    "bloom",
    "missing_concepts",
    "experiments",
    "visual_cards",
    "homework",
    "analogies",
    "lesson_plan_coverage",
    "combined_analysis",
    "session_report",
    "absorption_map",
]


class GenerateRequest(BaseModel):
    outputs: list[OutputType] = [
        "notes", "summary", "quiz", "bloom",
        "missing_concepts", "experiments", "homework", "analogies",
        "session_report",
    ]


class GenerateResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    estimated_sec: int = 90


class OutputEntry(BaseModel):
    status: str
    url: str | None = None
    generated_at: datetime | None = None
    data: Any = None
    tokens_used: int = 0


class SessionOutputsResponse(BaseModel):
    session_id: uuid.UUID
    outputs: dict[str, OutputEntry]
    total_tokens: int = 0


class QuizQuestionResponse(BaseModel):
    id: uuid.UUID
    type: str
    text: str
    options: list[str] | None = None
    correct: Any
    bloom_level: str | None
    topic: str | None
    skill_tag: str | None
    teacher_edited: bool


class QuizResponse(BaseModel):
    session_id: uuid.UUID
    questions: list[QuizQuestionResponse]


class TiQerExportRequest(BaseModel):
    tiqer_class_id: str
    schedule_at: datetime | None = None


class TiQerExportResponse(BaseModel):
    tiqer_session_id: str
    status: str
    question_count: int = 0
    exported_at: datetime | None = None
    payload: Any = None


class JobResponse(BaseModel):
    job_id: uuid.UUID
    type: str
    status: str
    progress: int
    result_url: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, obj):
        return cls(
            job_id=obj.id,
            type=obj.job_type,
            status=obj.status,
            progress=obj.progress,
            result_url=obj.result_url,
            error=obj.error_message,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )
