"""
GET /sessions/{session_id}/absorption-map

Returns each captured board frame annotated with the audience attention
level recorded at that minute.  No AI — pure data join:

  Frame.captured_at  →  relative minute  →  AudienceMetric.attention_pct
  Frame.id           →  OCRResult.raw_text (board content preview)

Absorption level thresholds:
  high   ≥ 65 % attention
  medium   35–64 %
  low    < 35 %
  unknown  no audience metric for that minute
"""
from __future__ import annotations

import uuid as _uuid_mod
from datetime import timezone as _tz

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.dependencies import CurrentTeacher, DB
from app.models.audience_metric import AudienceMetric
from app.models.frame import Frame
from app.models.ocr_result import OCRResult

router = APIRouter(prefix="/sessions", tags=["absorption"])


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------

class AbsorptionFrame(BaseModel):
    frame_id: str
    sequence_no: int
    captured_at: str | None
    minute: int
    ocr_preview: str | None
    attention_pct: float | None
    confused_pct: float | None
    surprised_pct: float | None
    absorption_level: str  # "high" | "medium" | "low" | "unknown"


class AbsorptionMapResponse(BaseModel):
    session_id: str
    has_audience_data: bool
    total_frames: int
    avg_attention_pct: float | None
    high_count: int
    medium_count: int
    low_count: int
    frames: list[AbsorptionFrame]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _level(att: float | None) -> str:
    if att is None:
        return "unknown"
    if att >= 65:
        return "high"
    if att >= 35:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/{session_id}/absorption-map", response_model=AbsorptionMapResponse)
async def get_absorption_map(
    session_id: str,
    db: DB,
    teacher_id: CurrentTeacher,
):
    try:
        sid = _uuid_mod.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid session_id")

    # Load frames ordered by sequence
    frame_rows = await db.execute(
        select(Frame)
        .where(Frame.session_id == sid)
        .order_by(Frame.sequence_no)
    )
    frames = frame_rows.scalars().all()

    if not frames:
        return AbsorptionMapResponse(
            session_id=session_id,
            has_audience_data=False,
            total_frames=0,
            avg_attention_pct=None,
            high_count=0,
            medium_count=0,
            low_count=0,
            frames=[],
        )

    # Load OCR results keyed by frame_id
    ocr_rows = await db.execute(
        select(OCRResult).where(OCRResult.frame_id.in_([f.id for f in frames]))
    )
    ocr_map = {r.frame_id: r for r in ocr_rows.scalars().all()}

    # Load audience metrics keyed by minute_number
    aud_rows = await db.execute(
        select(AudienceMetric)
        .where(AudienceMetric.session_id == sid)
        .order_by(AudienceMetric.minute_number)
    )
    aud_metrics = {m.minute_number: m for m in aud_rows.scalars().all()}
    has_audience = bool(aud_metrics)

    # Session start = earliest captured_at
    timestamps = [f.captured_at for f in frames if f.captured_at]
    session_start = min(timestamps) if timestamps else None

    result_frames: list[AbsorptionFrame] = []
    for frame in frames:
        minute = 0
        if session_start and frame.captured_at:
            fa = frame.captured_at
            ss = session_start
            if fa.tzinfo is None:
                fa = fa.replace(tzinfo=_tz.utc)
            if ss.tzinfo is None:
                ss = ss.replace(tzinfo=_tz.utc)
            minute = max(0, int((fa - ss).total_seconds() / 60))

        metric = aud_metrics.get(minute) or aud_metrics.get(minute + 1)
        ocr = ocr_map.get(frame.id)
        raw_text = ocr.raw_text if ocr else None
        preview = (raw_text[:200] + "…") if raw_text and len(raw_text) > 200 else raw_text

        att = round(metric.attention_pct, 1) if metric else None
        result_frames.append(AbsorptionFrame(
            frame_id=str(frame.id),
            sequence_no=frame.sequence_no,
            captured_at=frame.captured_at.isoformat() if frame.captured_at else None,
            minute=minute,
            ocr_preview=preview,
            attention_pct=att,
            confused_pct=round(metric.confused_pct, 1) if metric and hasattr(metric, "confused_pct") and metric.confused_pct is not None else None,
            surprised_pct=round(metric.surprised_pct, 1) if metric and hasattr(metric, "surprised_pct") and metric.surprised_pct is not None else None,
            absorption_level=_level(att),
        ))

    levels = [f.absorption_level for f in result_frames]
    high_count = levels.count("high")
    medium_count = levels.count("medium")
    low_count = levels.count("low")
    atts = [f.attention_pct for f in result_frames if f.attention_pct is not None]
    avg_att = round(sum(atts) / len(atts), 1) if atts else None

    return AbsorptionMapResponse(
        session_id=session_id,
        has_audience_data=has_audience,
        total_frames=len(result_frames),
        avg_attention_pct=avg_att,
        high_count=high_count,
        medium_count=medium_count,
        low_count=low_count,
        frames=result_frames,
    )
