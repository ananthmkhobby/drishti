#!/usr/bin/env python3
"""
Local OCR test script.

Usage:
  python scripts/test_ocr.py path/to/image.jpg
  python scripts/test_ocr.py path/to/image.jpg --board-type whiteboard
  python scripts/test_ocr.py path/to/image.jpg --board-type chalkboard --save-debug ./debug_out
  python scripts/test_ocr.py images/                  # process all jpg/png in a directory

Options:
  --board-type   chalkboard | whiteboard | smartboard  (default: chalkboard)
  --frame-id     custom frame id string                (default: auto-generated)
  --save-debug   directory to write preprocessed images and debug overlays
  --no-color     disable ANSI colour output
  --json         print full JSON result to stdout

The script imports app.ocr directly, so run it from the backend/ directory:
  cd /path/to/ACI/backend
  python scripts/test_ocr.py /path/to/image.jpg
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

# Add the backend directory to sys.path so `app` is importable
BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))


# ---------------------------------------------------------------------------
# ANSI colours
# ---------------------------------------------------------------------------

RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
DIM = "\033[2m"


def _c(text: str, *codes: str, use_color: bool = True) -> str:
    if not use_color:
        return text
    return "".join(codes) + text + RESET


# ---------------------------------------------------------------------------
# Imports (deferred so --help works without cv2 installed)
# ---------------------------------------------------------------------------

def _import_pipeline():
    """Import the OCR pipeline, exit with a helpful message if deps are missing."""
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        print("ERROR: opencv-python-headless and numpy are required.")
        print("  pip install opencv-python-headless numpy")
        sys.exit(1)

    try:
        from app.ocr.image_preprocessor import validate_frame, to_ocr_ready
        from app.ocr.board_detector import detect_board, draw_board_outline
        from app.ocr.ocr_service import process_frame
        from app.ocr.ocr_engine import FrameOCRResult
        return validate_frame, to_ocr_ready, detect_board, draw_board_outline, process_frame, FrameOCRResult
    except ImportError as e:
        print(f"ERROR: Could not import app.ocr: {e}")
        print("  Run this script from the backend/ directory:")
        print("    cd /path/to/ACI/backend && python scripts/test_ocr.py <image>")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Per-image processing
# ---------------------------------------------------------------------------

def process_image(
    image_path: Path,
    board_type: str,
    frame_id: str,
    save_debug: Path | None,
    use_color: bool,
    as_json: bool,
) -> None:
    import cv2
    import numpy as np

    validate_frame, to_ocr_ready, detect_board, draw_board_outline, process_frame, FrameOCRResult = _import_pipeline()

    print(_c(f"\n{'─' * 60}", DIM, use_color=use_color))
    print(_c(f"Image:      ", BOLD, use_color=use_color) + str(image_path))
    print(_c(f"Board type: ", BOLD, use_color=use_color) + board_type)
    print(_c(f"Frame ID:   ", BOLD, use_color=use_color) + frame_id)

    # ---- Validate ----
    image_bgr = cv2.imread(str(image_path))
    if image_bgr is None:
        print(_c("  ERROR: Cannot read image file", RED, use_color=use_color))
        return

    from app.ocr.image_preprocessor import validate_frame, to_ocr_ready
    validation = validate_frame(image_bgr)
    h, w = image_bgr.shape[:2]
    print(f"\n{_c('VALIDATION', CYAN, BOLD, use_color=use_color)}")
    print(f"  Size:       {w}×{h} px")
    print(f"  Blur score: {validation.blur_score:.1f}  (threshold: 50)")
    print(f"  Brightness: {validation.brightness:.1f}  (threshold: 30)")

    if not validation.is_valid:
        print(_c(f"  Result:     REJECTED — {validation.reason}", RED, use_color=use_color))
        print(_c("  (Frame will be skipped in the pipeline)", YELLOW, use_color=use_color))
        return
    else:
        print(_c("  Result:     VALID", GREEN, use_color=use_color))

    # ---- Board detection ----
    from app.ocr.board_detector import detect_board, draw_board_outline
    board = detect_board(image_bgr)
    print(f"\n{_c('BOARD DETECTION', CYAN, BOLD, use_color=use_color)}")
    if board.found:
        print(_c(f"  Board found at {board.original_bbox}", GREEN, use_color=use_color))
        hw, ww = board.warped.shape[:2]
        print(f"  Warped size: {ww}×{hw} px")
    else:
        print(_c("  No board boundary detected — using full frame", YELLOW, use_color=use_color))

    # ---- Preprocessing ----
    _, ocr_ready = to_ocr_ready(board.warped, board_type)
    print(f"\n{_c('PREPROCESSING', CYAN, BOLD, use_color=use_color)}")
    print(f"  Board type: {board_type}")
    print(f"  Output:     grayscale enhanced ({ocr_ready.shape[1]}×{ocr_ready.shape[0]})")

    # Save debug images
    if save_debug:
        save_debug.mkdir(parents=True, exist_ok=True)
        stem = image_path.stem

        outline_img = draw_board_outline(image_bgr, board)
        cv2.imwrite(str(save_debug / f"{stem}_01_board_outline.jpg"), outline_img)

        cv2.imwrite(str(save_debug / f"{stem}_02_warped.jpg"), board.warped)
        cv2.imwrite(str(save_debug / f"{stem}_03_preprocessed.jpg"), ocr_ready)
        print(f"  Debug saved to {save_debug}/")

    # ---- OCR ----
    print(f"\n{_c('OCR', CYAN, BOLD, use_color=use_color)}")
    with open(image_path, "rb") as f:
        image_bytes = f.read()

    result = process_frame(image_bytes, frame_id=frame_id, board_type=board_type)

    if result.error:
        if "skipped_invalid" in result.error:
            print(_c(f"  SKIPPED: {result.error}", YELLOW, use_color=use_color))
        elif "No OCR engine" in result.error:
            print(_c(f"  WARNING: {result.error}", YELLOW, use_color=use_color))
            print(_c("  Install: pip install paddlepaddle paddleocr  OR  pytesseract", DIM, use_color=use_color))
        else:
            print(_c(f"  ERROR: {result.error}", RED, use_color=use_color))
        return

    conf_color = GREEN if result.confidence >= 0.75 else (YELLOW if result.confidence >= 0.50 else RED)
    print(f"  Engine:     {result.engine_used}")
    print(f"  Confidence: {_c(f'{result.confidence:.3f}', conf_color, use_color=use_color)}")
    print(f"  Regions:    {len(result.regions)}")
    print(f"  Time:       {result.processing_ms} ms")
    if result.needs_review:
        print(_c("  ⚠ Flagged for manual review (confidence < 0.50)", YELLOW, use_color=use_color))

    # ---- Regions table ----
    print(f"\n{_c('REGIONS', CYAN, BOLD, use_color=use_color)}")
    if not result.regions:
        print(_c("  (no regions detected)", DIM, use_color=use_color))
    else:
        type_colors = {
            "heading": BOLD,
            "formula": YELLOW,
            "list": CYAN,
            "text": RESET,
            "diagram": DIM,
        }
        for i, r in enumerate(result.regions, 1):
            tc = type_colors.get(r.type, RESET)
            content_preview = (r.content or "(diagram)")[:80]
            if r.content and len(r.content) > 80:
                content_preview += "…"
            conf_str = f"{r.confidence:.2f}" if r.confidence is not None else "n/a "
            print(
                f"  {i:2}. {_c(f'{r.type:<10}', tc, use_color=use_color)} "
                f"conf={conf_str}  {content_preview}"
            )

    # ---- Merged text preview ----
    if result.raw_text:
        print(f"\n{_c('RAW TEXT (preview)', CYAN, BOLD, use_color=use_color)}")
        lines = result.raw_text.split("\n")
        for line in lines[:20]:
            print(f"  {line}")
        if len(lines) > 20:
            print(_c(f"  … ({len(lines) - 20} more lines)", DIM, use_color=use_color))

    # ---- JSON output ----
    if as_json:
        payload = {
            "frame_id": result.frame_id,
            "engine_used": result.engine_used,
            "confidence": result.confidence,
            "needs_review": result.needs_review,
            "processing_ms": result.processing_ms,
            "regions": [
                {
                    "type": r.type,
                    "content": r.content,
                    "bbox": r.bbox,
                    "confidence": r.confidence,
                    "engine": r.engine,
                }
                for r in result.regions
            ],
            "raw_text": result.raw_text,
        }
        print(f"\n{_c('JSON', CYAN, BOLD, use_color=use_color)}")
        print(json.dumps(payload, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test the ACI OCR pipeline on a local image or directory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("input", help="Image file (.jpg/.png) or directory")
    parser.add_argument(
        "--board-type",
        default="chalkboard",
        choices=["chalkboard", "whiteboard", "smartboard"],
        help="Board type (default: chalkboard)",
    )
    parser.add_argument("--frame-id", default=None, help="Custom frame ID (default: random UUID)")
    parser.add_argument("--save-debug", default=None, help="Directory to save debug images")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colours")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    args = parser.parse_args()

    use_color = not args.no_color and sys.stdout.isatty()
    input_path = Path(args.input)
    save_debug = Path(args.save_debug) if args.save_debug else None

    if input_path.is_dir():
        images = sorted(
            p for p in input_path.iterdir()
            if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
        )
        if not images:
            print(f"No .jpg/.png files found in {input_path}")
            sys.exit(1)
        print(_c(f"Found {len(images)} image(s) in {input_path}", BOLD, use_color=use_color))
        for img in images:
            fid = args.frame_id or str(uuid.uuid4())
            process_image(img, args.board_type, fid, save_debug, use_color, args.json)
    elif input_path.is_file():
        fid = args.frame_id or str(uuid.uuid4())
        process_image(input_path, args.board_type, fid, save_debug, use_color, args.json)
    else:
        print(f"ERROR: {input_path} does not exist")
        sys.exit(1)

    print(_c(f"\n{'─' * 60}\nDone.", DIM, use_color=use_color))


if __name__ == "__main__":
    main()
