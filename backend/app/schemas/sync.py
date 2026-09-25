"""
Pydantic schemas for offline sync endpoints.

Covers device registration, bulk session sync, sync status,
queue inspection, retry, and acknowledgement.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared literals
# ---------------------------------------------------------------------------

SyncItemStatus = Literal["pending", "uploading", "done", "failed", "skipped"]
EntityType = Literal["session_meta", "frame"]
SyncHealth = Literal["healthy", "degraded", "failing", "unknown"]


# ---------------------------------------------------------------------------
# Device registration  (POST /devices)
# ---------------------------------------------------------------------------

class DeviceRegisterRequest(BaseModel):
    device_fingerprint: str = Field(..., max_length=255)
    teacher_id: uuid.UUID
    platform: Literal["android", "ios", "web"] = "android"
    os_version: str | None = Field(None, max_length=50)
    model_name: str | None = Field(None, max_length=100)
    app_version: str | None = Field(None, max_length=20)
    push_token: str | None = Field(None, max_length=500)


class DeviceRegisterResponse(BaseModel):
    device_id: uuid.UUID
    device_fingerprint: str
    teacher_id: uuid.UUID
    registered: bool = Field(..., description="True=new device, False=updated existing")
    last_seen: datetime | None


# ---------------------------------------------------------------------------
# Bulk session sync  (POST /sync/sessions)
# ---------------------------------------------------------------------------

class SessionSyncItem(BaseModel):
    local_session_id: str = Field(..., max_length=100)
    subject: str | None = Field(None, max_length=100)
    grade: str | None = Field(None, max_length=50)
    board_type: str = Field("chalkboard", max_length=50)
    capture_mode: str = Field("time_based", max_length=50)
    capture_interval_sec: int = Field(30, ge=10, le=300)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    frame_count: int = Field(0, ge=0)
    classroom_id: uuid.UUID | None = None


class BulkSessionSyncRequest(BaseModel):
    device_fingerprint: str = Field(..., max_length=255)
    teacher_id: uuid.UUID
    sessions: list[SessionSyncItem] = Field(..., min_length=1, max_length=50)


class SessionSyncResult(BaseModel):
    local_session_id: str
    remote_session_id: uuid.UUID
    outcome: Literal["created", "already_exists", "rejected"]
    reason: str | None = None


class BulkSessionSyncResponse(BaseModel):
    device_id: uuid.UUID | None = None
    accepted: list[SessionSyncResult]
    rejected: list[SessionSyncResult]
    accepted_count: int
    rejected_count: int


# ---------------------------------------------------------------------------
# Sync status  (GET /sync/status/{device_fingerprint})
# ---------------------------------------------------------------------------

class SyncStatusResponse(BaseModel):
    device_fingerprint: str
    device_id: uuid.UUID | None
    pending: int
    uploading: int
    done: int
    failed: int
    skipped: int
    total: int
    last_sync_at: datetime | None
    health: SyncHealth


# ---------------------------------------------------------------------------
# Sync queue inspection  (GET /sync/queue)
# ---------------------------------------------------------------------------

class SyncQueueItem(BaseModel):
    id: uuid.UUID
    entity_type: str
    local_entity_id: str | None
    remote_entity_id: uuid.UUID | None
    session_id: uuid.UUID | None
    status: str
    retry_count: int
    last_attempt: datetime | None
    error_message: str | None
    created_at: datetime


class SyncQueueListResponse(BaseModel):
    items: list[SyncQueueItem]
    total: int
    pending: int
    failed: int


# ---------------------------------------------------------------------------
# Retry failed items  (POST /sync/retry)
# ---------------------------------------------------------------------------

class SyncRetryRequest(BaseModel):
    device_fingerprint: str = Field(..., max_length=255)
    item_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Specific UUIDs to retry. Empty = reset all failed/skipped for this device.",
    )


class SyncRetryResponse(BaseModel):
    reset_count: int
    items: list[dict]


# ---------------------------------------------------------------------------
# Acknowledge completed uploads  (POST /sync/ack)
# ---------------------------------------------------------------------------

class SyncAckItem(BaseModel):
    local_entity_id: str = Field(..., max_length=100)
    entity_type: EntityType
    remote_entity_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None


class SyncAckRequest(BaseModel):
    device_fingerprint: str = Field(..., max_length=255)
    teacher_id: uuid.UUID
    acknowledgements: list[SyncAckItem] = Field(..., min_length=1, max_length=200)


class SyncAckResponse(BaseModel):
    acknowledged: int
    created: int
    not_found: int


# ---------------------------------------------------------------------------
# Kept for internal backward compat — deprecated
# ---------------------------------------------------------------------------

class BulkSyncRequest(BaseModel):
    """Deprecated — use BulkSessionSyncRequest."""
    device_id: str
    sessions: list[dict]


class BulkSyncResponse(BaseModel):
    """Deprecated."""
    accepted: list[str]
    rejected: list[str]
    upload_tokens: dict[str, str]
