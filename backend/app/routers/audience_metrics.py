"""
Audience engagement metrics endpoints.

POST /sessions/{session_id}/audience-metrics  — upsert per-minute aggregate from client
POST /sessions/{session_id}/audience-frame    — analyse a JPEG frame server-side (RetinaFace + DeepFace)
GET  /sessions/{session_id}/audience-metrics  — return all minutes for the session
"""
import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, UploadFile, File, Form
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.dependencies import CurrentTeacher, DB
from app.exceptions import ACIError
from app.models.session import Session
from app.models.audience_metric import AudienceMetric

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Audience"])


class AudienceMetricIn(BaseModel):
    minute_number:  int   = Field(..., ge=1, le=999)
    faces_detected: int   = Field(..., ge=0)
    attention_pct:  float = Field(..., ge=0.0, le=100.0)
    hand_raises:    int   = Field(..., ge=0)
    happy_pct:      float = Field(0.0, ge=0.0, le=100.0)
    confused_pct:   float = Field(0.0, ge=0.0, le=100.0)
    surprised_pct:  float = Field(0.0, ge=0.0, le=100.0)
    disengaged_pct: float = Field(0.0, ge=0.0, le=100.0)


@router.post("/sessions/{session_id}/audience-metrics", status_code=201)
async def post_audience_metric(
    session_id: uuid.UUID,
    body: AudienceMetricIn,
    db: DB,
    _: CurrentTeacher,
):
    """Upsert a per-minute audience engagement aggregate from the client."""
    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    # Upsert: overwrite if the same minute already exists
    existing = await db.execute(
        select(AudienceMetric).where(
            AudienceMetric.session_id == session_id,
            AudienceMetric.minute_number == body.minute_number,
        )
    )
    row = existing.scalar_one_or_none()

    if row:
        row.faces_detected = body.faces_detected
        row.attention_pct  = body.attention_pct
        row.hand_raises    = body.hand_raises
        row.happy_pct      = body.happy_pct
        row.confused_pct   = body.confused_pct
        row.surprised_pct  = body.surprised_pct
        row.disengaged_pct = body.disengaged_pct
    else:
        row = AudienceMetric(
            id=uuid.uuid4(),
            session_id=session_id,
            minute_number=body.minute_number,
            faces_detected=body.faces_detected,
            attention_pct=body.attention_pct,
            hand_raises=body.hand_raises,
            happy_pct=body.happy_pct,
            confused_pct=body.confused_pct,
            surprised_pct=body.surprised_pct,
            disengaged_pct=body.disengaged_pct,
            created_at=datetime.now(timezone.utc),
        )
        db.add(row)

    await db.commit()
    await db.refresh(row)

    logger.info(
        "Audience metric min=%d faces=%d att=%.0f%% happy=%.0f%% confused=%.0f%% surprised=%.0f%% disengaged=%.0f%% session=%s",
        row.minute_number, row.faces_detected, row.attention_pct,
        row.happy_pct, row.confused_pct, row.surprised_pct, row.disengaged_pct, session_id,
    )
    return {
        "metric_id":      str(row.id),
        "minute_number":  row.minute_number,
        "faces_detected": row.faces_detected,
        "attention_pct":  row.attention_pct,
        "hand_raises":    row.hand_raises,
        "happy_pct":      row.happy_pct,
        "confused_pct":   row.confused_pct,
        "surprised_pct":  row.surprised_pct,
        "disengaged_pct": row.disengaged_pct,
    }


@router.post("/sessions/{session_id}/audience-frame")
async def post_audience_frame(
    session_id: uuid.UUID,
    db: DB,
    _: CurrentTeacher,
    file: UploadFile = File(...),
    minute_number: int = Form(..., ge=1, le=999),
):
    """
    Analyse a classroom frame server-side using RetinaFace + DeepFace.

    Accepts a JPEG/PNG upload, runs face detection + emotion classification,
    upserts the per-minute AudienceMetric row (merging with any existing data),
    and returns the full per-face + per-zone breakdown for the frontend overlay.

    DeepFace must be installed (pip install "aci-backend[audience]").
    If not installed, returns a zero-count result gracefully.
    """
    from app.services.audience_analysis import analyse_audience_frame

    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    image_bytes = await file.read()
    result = await analyse_audience_frame(image_bytes)

    faces_detected: int    = result["faces_detected"]
    attention_pct:  float  = result["attention_pct"]
    emotion_bd:     dict   = result["emotion_breakdown"]
    zone_summary:   dict   = result["zone_summary"]

    # Map emotion_breakdown to model columns
    happy_pct      = emotion_bd.get("happy", 0.0)
    confused_pct   = emotion_bd.get("confused", 0.0)
    surprised_pct  = emotion_bd.get("surprised", 0.0)
    disengaged_pct = emotion_bd.get("disengaged", 0.0)

    # Upsert AudienceMetric
    existing = await db.execute(
        select(AudienceMetric).where(
            AudienceMetric.session_id == session_id,
            AudienceMetric.minute_number == minute_number,
        )
    )
    row = existing.scalar_one_or_none()

    if row:
        # Average new reading into existing minute (rolling update)
        row.faces_detected = max(row.faces_detected, faces_detected)
        row.attention_pct  = round((row.attention_pct + attention_pct) / 2, 1)
        row.happy_pct      = round((row.happy_pct + happy_pct) / 2, 1)
        row.confused_pct   = round((row.confused_pct + confused_pct) / 2, 1)
        row.surprised_pct  = round((row.surprised_pct + surprised_pct) / 2, 1)
        row.disengaged_pct = round((row.disengaged_pct + disengaged_pct) / 2, 1)
        row.zone_data      = zone_summary
    else:
        row = AudienceMetric(
            id=uuid.uuid4(),
            session_id=session_id,
            minute_number=minute_number,
            faces_detected=faces_detected,
            attention_pct=attention_pct,
            hand_raises=0,
            happy_pct=happy_pct,
            confused_pct=confused_pct,
            surprised_pct=surprised_pct,
            disengaged_pct=disengaged_pct,
            zone_data=zone_summary,
            created_at=datetime.now(timezone.utc),
        )
        db.add(row)

    await db.commit()
    await db.refresh(row)

    logger.info(
        "Audience frame analysed: min=%d faces=%d att=%.0f%% session=%s",
        minute_number, faces_detected, attention_pct, session_id,
    )

    return {
        "minute_number":    minute_number,
        "faces_detected":   faces_detected,
        "attention_pct":    attention_pct,
        "dominant_emotion": result["dominant_emotion"],
        "zone_summary":     zone_summary,
        "emotion_breakdown": emotion_bd,
        "faces":            result["faces"],
    }


@router.get("/sessions/{session_id}/audience-metrics")
async def get_audience_metrics(
    session_id: uuid.UUID,
    db: DB,
    _: CurrentTeacher,
):
    """Return all per-minute audience metrics for a session, ordered by minute."""
    session = await db.get(Session, session_id)
    if not session:
        raise ACIError("SESSION_NOT_FOUND", "Session not found", 404)

    result = await db.execute(
        select(AudienceMetric)
        .where(AudienceMetric.session_id == session_id)
        .order_by(AudienceMetric.minute_number)
    )
    rows = result.scalars().all()

    if not rows:
        avg_attention = None
    else:
        avg_attention = round(sum(r.attention_pct for r in rows) / len(rows), 1)

    return {
        "session_id": str(session_id),
        "minute_count": len(rows),
        "avg_attention_pct": avg_attention,
        "metrics": [
            {
                "minute_number":  r.minute_number,
                "faces_detected": r.faces_detected,
                "attention_pct":  r.attention_pct,
                "hand_raises":    r.hand_raises,
                "happy_pct":      r.happy_pct,
                "confused_pct":   r.confused_pct,
                "surprised_pct":  r.surprised_pct,
                "disengaged_pct": r.disengaged_pct,
                "zone_data":      r.zone_data,
            }
            for r in rows
        ],
    }
