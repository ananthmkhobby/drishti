"""
Sync service — business logic for all offline sync operations.

Handles:
  - Device registration / last-seen update
  - Bulk session creation (idempotent)
  - Server-side SyncQueue management
  - Sync status aggregation
  - Retry reset
  - Acknowledgement of client-side uploads

The server-side SyncQueue is an *ops mirror* of the mobile's local queue.
It lets operations staff see per-device sync health without querying the device.

Key invariants:
  1. Session creation via bulk sync is idempotent: the same local_session_id
     always returns the same remote_session_id.
  2. SyncQueue entries for "done" items are never reset by the normal flow;
     only POST /sync/retry can reset "failed"/"skipped" items.
  3. Frame uploads via POST /sessions/{id}/frames with device_fingerprint
     automatically create/update the SyncQueue entry.
"""

from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.models.session import Session
from app.models.sync_queue import SyncQueue
from app.schemas.sync import (
    DeviceRegisterRequest,
    DeviceRegisterResponse,
    BulkSessionSyncRequest,
    BulkSessionSyncResponse,
    SessionSyncResult,
    SyncStatusResponse,
    SyncQueueListResponse,
    SyncQueueItem,
    SyncRetryRequest,
    SyncRetryResponse,
    SyncAckRequest,
    SyncAckResponse,
    SyncHealth,
)

logger = logging.getLogger(__name__)

_MAX_RETRIES = 5


# ---------------------------------------------------------------------------
# Device registration
# ---------------------------------------------------------------------------

async def register_device(
    req: DeviceRegisterRequest,
    db: AsyncSession,
) -> DeviceRegisterResponse:
    """Register a new device or refresh an existing one."""
    existing = (
        await db.execute(
            select(Device).where(Device.device_fingerprint == req.device_fingerprint)
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if existing:
        # Update mutable fields
        existing.teacher_id = req.teacher_id
        existing.platform = req.platform
        if req.os_version is not None:
            existing.os_version = req.os_version
        if req.model_name is not None:
            existing.model_name = req.model_name
        if req.app_version is not None:
            existing.app_version = req.app_version
        if req.push_token is not None:
            existing.push_token = req.push_token
        existing.last_seen = now
        await db.commit()
        await db.refresh(existing)
        return DeviceRegisterResponse(
            device_id=existing.id,
            device_fingerprint=existing.device_fingerprint,
            teacher_id=existing.teacher_id,
            registered=False,
            last_seen=existing.last_seen,
        )

    device = Device(
        id=uuid.uuid4(),
        teacher_id=req.teacher_id,
        device_fingerprint=req.device_fingerprint,
        platform=req.platform,
        os_version=req.os_version,
        model_name=req.model_name,
        app_version=req.app_version,
        push_token=req.push_token,
        last_seen=now,
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)
    logger.info("Device registered: %s (%s)", req.device_fingerprint, req.platform)
    return DeviceRegisterResponse(
        device_id=device.id,
        device_fingerprint=device.device_fingerprint,
        teacher_id=device.teacher_id,
        registered=True,
        last_seen=device.last_seen,
    )


# ---------------------------------------------------------------------------
# Bulk session sync
# ---------------------------------------------------------------------------

async def bulk_sync_sessions(
    req: BulkSessionSyncRequest,
    db: AsyncSession,
) -> BulkSessionSyncResponse:
    """
    Register offline sessions with the server.

    - Idempotent: re-submitting the same local_session_id returns the existing
      remote_session_id with outcome="already_exists".
    - Sessions are created in "completed" state (they were captured offline).
    - A SyncQueue row (entity_type="session_meta", status="done") is created
      for each accepted session so the ops dashboard can see what was synced.
    """
    # Resolve (or lazily create) the device record
    device_id: uuid.UUID | None = await _resolve_device_id(
        req.device_fingerprint, req.teacher_id, db
    )

    accepted: list[SessionSyncResult] = []
    rejected: list[SessionSyncResult] = []

    for item in req.sessions:
        result = await _sync_one_session(item, req.teacher_id, device_id, db)
        if result.outcome == "rejected":
            rejected.append(result)
        else:
            accepted.append(result)

    return BulkSessionSyncResponse(
        device_id=device_id,
        accepted=accepted,
        rejected=rejected,
        accepted_count=len(accepted),
        rejected_count=len(rejected),
    )


async def _sync_one_session(
    item: Any,
    teacher_id: uuid.UUID,
    device_id: uuid.UUID | None,
    db: AsyncSession,
) -> SessionSyncResult:
    """Process a single session sync item; returns its result."""
    # Idempotency check: look for existing session with this local_session_id
    existing = (
        await db.execute(
            select(Session).where(Session.local_session_id == item.local_session_id)
        )
    ).scalar_one_or_none()

    if existing:
        logger.debug("Session already exists: local=%s remote=%s", item.local_session_id, existing.id)
        return SessionSyncResult(
            local_session_id=item.local_session_id,
            remote_session_id=existing.id,
            outcome="already_exists",
        )

    try:
        session = Session(
            id=uuid.uuid4(),
            teacher_id=teacher_id,
            classroom_id=item.classroom_id,
            local_session_id=item.local_session_id,
            subject=item.subject,
            grade=item.grade,
            board_type=item.board_type,
            capture_mode=item.capture_mode,
            capture_interval_sec=item.capture_interval_sec,
            status="completed",          # offline sessions are already finished
            frame_count=item.frame_count,
            sync_status="syncing",       # frames still need uploading
            started_at=item.started_at,
            completed_at=item.completed_at,
        )
        db.add(session)
        await db.flush()  # get session.id without committing

        # Create server-side SyncQueue entry for the session metadata
        sq = SyncQueue(
            id=uuid.uuid4(),
            device_id=device_id,
            device_fingerprint=None,      # device_id is enough
            teacher_id=teacher_id,
            session_id=session.id,
            entity_type="session_meta",
            local_entity_id=item.local_session_id,
            remote_entity_id=session.id,
            status="done",               # session metadata upload is complete
            retry_count=0,
        )
        db.add(sq)
        await db.commit()

        logger.info(
            "Session synced: local=%s remote=%s teacher=%s",
            item.local_session_id, session.id, teacher_id,
        )
        return SessionSyncResult(
            local_session_id=item.local_session_id,
            remote_session_id=session.id,
            outcome="created",
        )

    except Exception as exc:
        await db.rollback()
        logger.warning("Failed to sync session %s: %s", item.local_session_id, exc)
        return SessionSyncResult(
            local_session_id=item.local_session_id,
            remote_session_id=uuid.UUID(int=0),  # placeholder — not usable
            outcome="rejected",
            reason=str(exc),
        )


# ---------------------------------------------------------------------------
# Sync status aggregation
# ---------------------------------------------------------------------------

async def get_sync_status(
    device_fingerprint: str,
    db: AsyncSession,
) -> SyncStatusResponse:
    """
    Aggregate SyncQueue counts for a device.
    Looks up the device by fingerprint; returns unknown health if not registered.
    """
    device = (
        await db.execute(
            select(Device).where(Device.device_fingerprint == device_fingerprint)
        )
    ).scalar_one_or_none()

    device_id = device.id if device else None

    if device_id is None:
        # Device not yet registered — return zeroed status
        return SyncStatusResponse(
            device_fingerprint=device_fingerprint,
            device_id=None,
            pending=0,
            uploading=0,
            done=0,
            failed=0,
            skipped=0,
            total=0,
            last_sync_at=None,
            health="unknown",
        )

    # Count by status
    rows = (
        await db.execute(
            select(SyncQueue.status, func.count(SyncQueue.id).label("cnt"))
            .where(SyncQueue.device_id == device_id)
            .group_by(SyncQueue.status)
        )
    ).all()

    counts: dict[str, int] = {r.status: r.cnt for r in rows}
    pending   = counts.get("pending", 0)
    uploading = counts.get("uploading", 0)
    done      = counts.get("done", 0)
    failed    = counts.get("failed", 0)
    skipped   = counts.get("skipped", 0)
    total     = pending + uploading + done + failed + skipped

    # Last successful sync time
    last_sync = (
        await db.execute(
            select(func.max(SyncQueue.created_at))
            .where(SyncQueue.device_id == device_id)
            .where(SyncQueue.status == "done")
        )
    ).scalar_one_or_none()

    # Update device last_seen
    if device:
        device.last_seen = datetime.now(timezone.utc)
        await db.commit()

    health = _compute_health(pending, failed, skipped, total)

    return SyncStatusResponse(
        device_fingerprint=device_fingerprint,
        device_id=device_id,
        pending=pending,
        uploading=uploading,
        done=done,
        failed=failed,
        skipped=skipped,
        total=total,
        last_sync_at=last_sync,
        health=health,
    )


def _compute_health(
    pending: int, failed: int, skipped: int, total: int
) -> SyncHealth:
    if total == 0:
        return "healthy"
    if skipped > 0:
        return "failing"
    if failed > 0:
        return "degraded"
    if pending == 0:
        return "healthy"
    return "healthy"   # pending items are normal — not a health issue


# ---------------------------------------------------------------------------
# Queue inspection
# ---------------------------------------------------------------------------

async def list_queue_items(
    device_fingerprint: str,
    db: AsyncSession,
    status_filter: list[str] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> SyncQueueListResponse:
    """List SyncQueue entries for a device with optional status filter."""
    device = (
        await db.execute(
            select(Device).where(Device.device_fingerprint == device_fingerprint)
        )
    ).scalar_one_or_none()

    if not device:
        return SyncQueueListResponse(items=[], total=0, pending=0, failed=0)

    q = select(SyncQueue).where(SyncQueue.device_id == device.id)
    if status_filter:
        q = q.where(SyncQueue.status.in_(status_filter))

    total = (
        await db.execute(select(func.count()).select_from(q.subquery()))
    ).scalar_one()

    rows = (
        await db.execute(q.order_by(SyncQueue.created_at.asc()).limit(limit).offset(offset))
    ).scalars().all()

    # Pending / failed counts for the whole device (not just the filtered page)
    status_counts = (
        await db.execute(
            select(SyncQueue.status, func.count(SyncQueue.id))
            .where(SyncQueue.device_id == device.id)
            .group_by(SyncQueue.status)
        )
    ).all()
    sc = {r[0]: r[1] for r in status_counts}

    items = [
        SyncQueueItem(
            id=r.id,
            entity_type=r.entity_type,
            local_entity_id=r.local_entity_id,
            remote_entity_id=r.remote_entity_id,
            session_id=r.session_id,
            status=r.status,
            retry_count=r.retry_count,
            last_attempt=r.last_attempt,
            error_message=r.error_message,
            created_at=r.created_at,
        )
        for r in rows
    ]

    return SyncQueueListResponse(
        items=items,
        total=total,
        pending=sc.get("pending", 0),
        failed=sc.get("failed", 0),
    )


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------

async def reset_for_retry(
    req: SyncRetryRequest,
    db: AsyncSession,
) -> SyncRetryResponse:
    """
    Reset failed/skipped SyncQueue items back to "pending".

    If item_ids is empty, resets ALL failed/skipped items for the device.
    Skips items that are already pending/uploading/done.
    """
    device = (
        await db.execute(
            select(Device).where(Device.device_fingerprint == req.device_fingerprint)
        )
    ).scalar_one_or_none()

    if not device:
        return SyncRetryResponse(reset_count=0, items=[])

    q = (
        select(SyncQueue)
        .where(SyncQueue.device_id == device.id)
        .where(SyncQueue.status.in_(["failed", "skipped"]))
    )
    if req.item_ids:
        q = q.where(SyncQueue.id.in_(req.item_ids))

    rows = (await db.execute(q)).scalars().all()

    reset_items: list[dict] = []
    for row in rows:
        row.status = "pending"
        row.retry_count = 0
        row.error_message = None
        row.last_attempt = None
        reset_items.append({"id": str(row.id), "status": "pending"})

    await db.commit()
    logger.info("Reset %d sync items for device %s", len(reset_items), req.device_fingerprint)
    return SyncRetryResponse(reset_count=len(reset_items), items=reset_items)


# ---------------------------------------------------------------------------
# Acknowledgement
# ---------------------------------------------------------------------------

async def acknowledge_uploads(
    req: SyncAckRequest,
    db: AsyncSession,
) -> SyncAckResponse:
    """
    Mark uploaded items as done in the server-side SyncQueue.

    Called by the mobile app after successfully uploading a frame or session
    metadata (especially useful for direct-S3 uploads that bypass the normal
    /sessions/{id}/frames endpoint).

    Creates new SyncQueue entries if none exist yet for the ack'd items.
    """
    device = (
        await db.execute(
            select(Device).where(Device.device_fingerprint == req.device_fingerprint)
        )
    ).scalar_one_or_none()

    device_id: uuid.UUID | None = device.id if device else None

    acknowledged = 0
    created = 0
    not_found_count = 0

    for ack in req.acknowledgements:
        # Try to find existing SyncQueue entry
        existing = (
            await db.execute(
                select(SyncQueue)
                .where(SyncQueue.teacher_id == req.teacher_id)
                .where(SyncQueue.local_entity_id == ack.local_entity_id)
                .where(SyncQueue.entity_type == ack.entity_type)
            )
        ).scalar_one_or_none()

        if existing:
            existing.status = "done"
            existing.remote_entity_id = ack.remote_entity_id
            if device_id and existing.device_id is None:
                existing.device_id = device_id
            acknowledged += 1
        else:
            # First ack for this item — create a new SyncQueue entry
            sq = SyncQueue(
                id=uuid.uuid4(),
                device_id=device_id,
                device_fingerprint=req.device_fingerprint,
                teacher_id=req.teacher_id,
                session_id=ack.session_id,
                entity_type=ack.entity_type,
                local_entity_id=ack.local_entity_id,
                remote_entity_id=ack.remote_entity_id,
                status="done",
                retry_count=0,
            )
            db.add(sq)
            created += 1

    await db.commit()

    # Update session sync_status if all its frames are now done
    session_ids = {ack.session_id for ack in req.acknowledgements if ack.session_id}
    for sid in session_ids:
        await _maybe_mark_session_synced(sid, db)

    return SyncAckResponse(
        acknowledged=acknowledged,
        created=created,
        not_found=not_found_count,
    )


# ---------------------------------------------------------------------------
# Frame upload integration
# ---------------------------------------------------------------------------

async def record_frame_upload(
    frame_id: uuid.UUID,
    session_id: uuid.UUID,
    local_frame_id: str,
    teacher_id: uuid.UUID,
    device_fingerprint: str | None,
    db: AsyncSession,
) -> None:
    """
    Called by the frame upload endpoint when device_fingerprint is provided.
    Creates a SyncQueue entry (entity_type="frame", status="done") so the
    ops dashboard can see that this frame arrived from a specific device.
    """
    if not device_fingerprint:
        return

    device_id = await _resolve_device_id(device_fingerprint, teacher_id, db, create_if_missing=False)

    # Avoid double-entry if the frame was re-uploaded (409 case already handled upstream)
    existing = (
        await db.execute(
            select(SyncQueue)
            .where(SyncQueue.local_entity_id == local_frame_id)
            .where(SyncQueue.entity_type == "frame")
            .where(SyncQueue.session_id == session_id)
        )
    ).scalar_one_or_none()

    if existing:
        existing.status = "done"
        existing.remote_entity_id = frame_id
        existing.device_id = existing.device_id or device_id
    else:
        sq = SyncQueue(
            id=uuid.uuid4(),
            device_id=device_id,
            device_fingerprint=device_fingerprint,
            teacher_id=teacher_id,
            session_id=session_id,
            entity_type="frame",
            local_entity_id=local_frame_id,
            remote_entity_id=frame_id,
            status="done",
            retry_count=0,
        )
        db.add(sq)

    # Note: do NOT commit here — the caller (frame router) commits after its own changes.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _resolve_device_id(
    device_fingerprint: str,
    teacher_id: uuid.UUID,
    db: AsyncSession,
    create_if_missing: bool = True,
) -> uuid.UUID | None:
    """Find a device by fingerprint, optionally creating a minimal record."""
    device = (
        await db.execute(
            select(Device).where(Device.device_fingerprint == device_fingerprint)
        )
    ).scalar_one_or_none()

    if device:
        return device.id

    if not create_if_missing:
        return None

    # Auto-register with minimal info (will be enriched by POST /devices)
    device = Device(
        id=uuid.uuid4(),
        teacher_id=teacher_id,
        device_fingerprint=device_fingerprint,
        platform="android",   # assumed; will be corrected on next POST /devices
        last_seen=datetime.now(timezone.utc),
    )
    db.add(device)
    await db.flush()
    return device.id


async def _maybe_mark_session_synced(
    session_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """
    Mark a session's sync_status as "synced" if all its SyncQueue frame entries
    are done and there is at least one done frame entry.

    Called after acknowledgements so the session card on the dashboard updates.
    """
    session = await db.get(Session, session_id)
    if not session:
        return

    # Count pending/failed frame entries for this session
    unfinished = (
        await db.execute(
            select(func.count(SyncQueue.id))
            .where(SyncQueue.session_id == session_id)
            .where(SyncQueue.entity_type == "frame")
            .where(SyncQueue.status.notin_(["done", "skipped"]))
        )
    ).scalar_one()

    done_frames = (
        await db.execute(
            select(func.count(SyncQueue.id))
            .where(SyncQueue.session_id == session_id)
            .where(SyncQueue.entity_type == "frame")
            .where(SyncQueue.status == "done")
        )
    ).scalar_one()

    if unfinished == 0 and done_frames > 0:
        session.sync_status = "synced"
        logger.info("Session %s fully synced (%d frames)", session_id, done_frames)
