"""
ACI OCR Pipeline
================

Public API:

    from app.ocr import process_frame, merge_session_frames
    from app.ocr import FrameOCRResult, SessionMergeResult, TextRegion

Full modular pipeline:
  image_preprocessor → board_detector → ocr_engine → ocr_service (orchestrator)
"""

from app.ocr.ocr_engine import FrameOCRResult, TextRegion
from app.ocr.ocr_service import process_frame, merge_session_frames, SessionMergeResult

__all__ = [
    "process_frame",
    "merge_session_frames",
    "FrameOCRResult",
    "SessionMergeResult",
    "TextRegion",
]
