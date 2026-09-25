"""
Sync router — all offline sync endpoints.

  POST /devices                        Register / update a device
  POST /sync/sessions                  Bulk register offline sessions
  GET  /sync/status/{fingerprint}      Per-device sync health
  GET  /sync/queue                     Inspect sync queue (teacher-scoped)
  POST /sync/retry                     Reset failed items for retry
  POST /sync/ack                       Acknowledge client-side uploads
  GET  /sync/events                    Poll processing completion events (Phase 2)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.models.sync_event import SyncEvent

from app.dependencies import CurrentTeacher, DB
from app.schemas.sync import (
    DeviceRegisterRequest,
    DeviceRegisterResponse,
    BulkSessionSyncRequest,
    BulkSessionSyncResponse,
    SyncStatusResponse,
    SyncQueueListResponse,
    SyncRetryRequest,
    SyncRetryResponse,
    SyncAckRequest,
    SyncAckResponse,
)
from app.services import sync_service

router = APIRouter(tags=["Sync"])


@router.post("/devices", status_code=201, response_model=DeviceRegisterResponse)
async def register_device(body: DeviceRegisterRequest, db: DB, _: CurrentTeacher):
    """
    Register a new device or update an existing one.

    Call on first app launch and when the FCM push token changes.
    Idempotent: re-submitting the same device_fingerprint updates last_seen,
    platform info, and push_token.
    """
    return await sync_service.register_device(body, db)


@router.post("/sync/sessions", response_model=BulkSessionSyncResponse)
async def bulk_sync_sessions(body: BulkSessionSyncRequest, db: DB, _: CurrentTeacher):
    """
    Register one or more offline sessions with the server in a single call.

    Call this BEFORE uploading any frames so the server knows which
    remote_session_id to associate with each frame.

    Idempotent: local_session_id that already exists returns
    outcome='already_exists' with the original remote_session_id.
    """
    return await sync_service.bulk_sync_sessions(body, db)


@router.get("/sync/status/{device_fingerprint}", response_model=SyncStatusResponse)
async def get_sync_status(device_fingerprint: str, db: DB, _: CurrentTeacher):
    """
    Return server-side sync health for a device.

    Health: healthy | degraded (some failures) | failing (max retries) | unknown
    """
    return await sync_service.get_sync_status(device_fingerprint, db)


@router.get("/sync/queue", response_model=SyncQueueListResponse)
async def list_sync_queue(
    db: DB,
    _: CurrentTeacher,
    device_fingerprint: str | None = Query(None),
    status: list[str] | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List sync queue entries for a device (ops/dashboard use)."""
    if not device_fingerprint:
        return SyncQueueListResponse(items=[], total=0, pending=0, failed=0)
    return await sync_service.list_queue_items(device_fingerprint, db, status, limit, offset)


@router.post("/sync/retry", response_model=SyncRetryResponse)
async def retry_sync(body: SyncRetryRequest, db: DB, _: CurrentTeacher):
    """
    Reset failed/skipped sync queue items to pending.

    Empty item_ids resets ALL failed/skipped for the device.
    The mobile app must independently re-queue uploads in its local SQLite.
    """
    return await sync_service.reset_for_retry(body, db)


@router.post("/sync/ack", response_model=SyncAckResponse)
async def acknowledge_uploads(body: SyncAckRequest, db: DB, _: CurrentTeacher):
    """
    Acknowledge successful uploads to the server-side sync queue.

    Use for direct-to-S3 uploads. POST /sessions/{id}/frames with
    device_fingerprint in the form data auto-acknowledges.

    When all frames for a session are acknowledged, session.sync_status = 'synced'.
    """
    return await sync_service.acknowledge_uploads(body, db)


# ── Phase 2: event polling ────────────────────────────────────────────────────

class SyncEventResponse(BaseModel):
    id: str
    session_id: str | None
    type: str
    payload: dict | None
    created_at: str


class SyncEventsListResponse(BaseModel):
    events: list[SyncEventResponse]
    next_cursor: str | None  # ISO timestamp of the latest event — pass as `since` next time


@router.get("/sync/events", response_model=SyncEventsListResponse)
async def list_sync_events(
    db: DB,
    _: CurrentTeacher,
    session_id: uuid.UUID | None = Query(None, description="Filter to one session"),
    since: str | None = Query(None, description="ISO timestamp cursor — return events after this"),
    limit: int = Query(50, ge=1, le=200),
):
    """
    Return processing completion events for incremental polling.

    Client stores `next_cursor` and passes it as `since` on the next poll.
    Events are immutable and ordered oldest-first so the client can merge them.
    """
    import json as _json

    q = select(SyncEvent).order_by(SyncEvent.created_at.asc()).limit(limit)

    if session_id:
        q = q.where(SyncEvent.session_id == session_id)

    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            q = q.where(SyncEvent.created_at > since_dt)
        except ValueError:
            pass  # ignore malformed cursor; return from beginning

    rows = (await db.execute(q)).scalars().all()

    events = [
        SyncEventResponse(
            id=str(r.id),
            session_id=str(r.session_id) if r.session_id else None,
            type=r.type,
            payload=_json.loads(r.payload_json) if r.payload_json else None,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]

    next_cursor = events[-1].created_at if events else None

    return SyncEventsListResponse(events=events, next_cursor=next_cursor)
