import uuid
from datetime import datetime
from pydantic import BaseModel


class FrameUploadResponse(BaseModel):
    frame_id: uuid.UUID
    status: str
    message: str


class FrameResponse(BaseModel):
    frame_id: uuid.UUID
    session_id: uuid.UUID
    sequence_no: int
    local_frame_id: str
    image_size_kb: int | None
    captured_at: datetime | None
    ocr_status: str
    ai_status: str
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, obj):
        return cls(
            frame_id=obj.id,
            session_id=obj.session_id,
            sequence_no=obj.sequence_no,
            local_frame_id=obj.local_frame_id,
            image_size_kb=obj.image_size_kb,
            captured_at=obj.captured_at,
            ocr_status=obj.ocr_status,
            ai_status=obj.ai_status,
            created_at=obj.created_at,
        )


class FrameListResponse(BaseModel):
    frames: list[FrameResponse]
    total: int


class OCRRegion(BaseModel):
    type: str
    bbox: list[int | float] | None = None
    content: str | None = None
    confidence: float | None = None


class OCRResultResponse(BaseModel):
    frame_id: uuid.UUID
    ocr_text: str | None
    confidence: float | None
    regions: list[OCRRegion]
    engine_used: str | None
    processed_at: datetime
    privacy_blurred: int = 0       # number of face/body regions blurred (0 = no people)
    board_type: str = "chalkboard" # auto-detected board type used for preprocessing
    board_confidence: float = 0.0  # board detection confidence 0–1
    board_detection_method: str = "fallback"  # calibrated|vision|yolo|contour|fallback
