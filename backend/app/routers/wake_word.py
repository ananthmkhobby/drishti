"""GET /v1/wake-word/ws — WebSocket push for on-device "Hey XP"
detections (see app/services/wake_word_service.py). No request/response
body: the frontend just holds the connection open while the assistant is
closed and wake word is enabled, and receives {"type": "wake", ...} the
instant the backend's own microphone hears the phrase.

POST /v1/wake-word/pause and /resume — let the frontend hand the physical
microphone back to the detector once a real voice-command recording is
done (and take it away right before starting one). There's exactly one
mic; the detector's continuous capture and the browser's getUserMedia()
recording don't share it cleanly on this hardware (confirmed 2026-09-16:
manual voice commands stopped transcribing entirely while the detector
was running), so these calls bracket every recording instead of leaving
both sides fighting over the device permanently."""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services import wake_word_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Wake Word"])


@router.websocket("/wake-word/ws")
async def wake_word_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    wake_word_service.register(websocket)
    try:
        while True:
            # Nothing expected from the client — just keep the connection
            # open and notice if it drops. A client-side ping would also
            # land here harmlessly.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        wake_word_service.unregister(websocket)


@router.post("/wake-word/pause", status_code=204)
async def wake_word_pause() -> None:
    await wake_word_service.pause()


@router.post("/wake-word/resume", status_code=204)
async def wake_word_resume() -> None:
    await wake_word_service.resume()
