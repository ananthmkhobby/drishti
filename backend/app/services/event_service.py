"""Emit sync_events rows so clients can poll for processing completions."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sync_event import SyncEvent

logger = logging.getLogger(__name__)

VALID_TYPES = frozenset({
    "FRAME_PROCESSED",
    "OCR_DONE",
    "AUDIO_TRANSCRIBED",
    "VIDEO_PROCESSED",
    "AI_OUTPUT_READY",
    "PRACTICE_ATTEMPT_DONE",
})


async def emit(
    db: AsyncSession,
    event_type: str,
    session_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    if event_type not in VALID_TYPES:
        logger.warning("Unknown sync event type %r — skipped", event_type)
        return
    try:
        ev = SyncEvent(
            session_id=session_id,
            type=event_type,
            payload_json=json.dumps(payload) if payload else None,
        )
        db.add(ev)
        await db.commit()
    except Exception:
        logger.exception("Failed to emit sync event %s for session %s", event_type, session_id)
