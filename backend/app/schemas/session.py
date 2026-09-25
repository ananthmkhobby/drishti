import uuid
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, field_serializer


BoardType = Literal["chalkboard", "whiteboard", "smartboard", "notebook"]
CaptureMode = Literal["time_based", "manual", "motion", "ai_smart"]
SessionStatus = Literal["active", "completed", "processing", "failed"]
SyncStatus = Literal["pending", "syncing", "synced", "failed"]


class SessionCreate(BaseModel):
    teacher_id: uuid.UUID
    classroom_id: uuid.UUID | None = None
    subject: str | None = None
    grade: str | None = None
    title: str | None = None
    instructor_name: str | None = None
    board_type: BoardType = "chalkboard"
    capture_mode: CaptureMode = "time_based"
    capture_interval_sec: int = Field(default=30, ge=10, le=300)
    local_session_id: str | None = None
    # Client-generated UUID — used as the server-side session id.
    # Allows offline create: client navigates to /sessions/{id}/capture
    # immediately; sync engine POSTs this payload later.
    client_session_id: uuid.UUID | None = None


class SessionUpdate(BaseModel):
    status: SessionStatus | None = None
    sync_status: SyncStatus | None = None
    title: str | None = None
    subject: str | None = None
    instructor_name: str | None = None


class SessionResponse(BaseModel):
    session_id: uuid.UUID
    teacher_id: uuid.UUID
    classroom_id: uuid.UUID | None
    subject: str | None
    grade: str | None
    title: str | None
    instructor_name: str | None
    board_type: str
    capture_mode: str
    capture_interval_sec: int
    status: str
    frame_count: int
    sync_status: str
    local_session_id: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("created_at", mode="plain", when_used="json")
    def _ser_created_at(self, v: datetime) -> str:
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.isoformat().replace("+00:00", "Z")

    @field_serializer("started_at", "completed_at", mode="plain", when_used="json")
    def _ser_optional_dt(self, v: datetime | None) -> str | None:
        if v is None:
            return None
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.isoformat().replace("+00:00", "Z")

    @classmethod
    def from_orm(cls, obj):
        return cls(
            session_id=obj.id,
            teacher_id=obj.teacher_id,
            classroom_id=obj.classroom_id,
            subject=obj.subject,
            grade=obj.grade,
            title=obj.title,
            instructor_name=obj.instructor_name,
            board_type=obj.board_type,
            capture_mode=obj.capture_mode,
            capture_interval_sec=obj.capture_interval_sec,
            status=obj.status,
            frame_count=obj.frame_count,
            sync_status=obj.sync_status,
            local_session_id=obj.local_session_id,
            started_at=obj.started_at,
            completed_at=obj.completed_at,
            created_at=obj.created_at,
        )


class SessionCreateResponse(BaseModel):
    session_id: uuid.UUID
    status: str
    created_at: datetime

    @field_serializer("created_at", mode="plain", when_used="json")
    def _ser_created_at(self, v: datetime) -> str:
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.isoformat().replace("+00:00", "Z")


class SessionListResponse(BaseModel):
    sessions: list[SessionResponse]
    total: int
    limit: int
    offset: int
