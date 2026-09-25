# ACI — Sample Images for OCR Testing

This directory holds real board photographs for local OCR evaluation.
Synthetic test images are generated automatically by `backend/scripts/test_ocr_local.py`.
Place real photos here to benchmark the pipeline against genuine classroom conditions.

---

## Directory Layout

```
sample_images/
├── blackboard/          ← Black chalkboard with white/yellow chalk
├── greenboard/          ← Green chalkboard with white/pale-yellow chalk
├── whiteboard/          ← White or light-grey marker board
├── messy_handwriting/   ← Rushed, uneven, or overlapping text
├── tilted_board/        ← Board photographed at an angle (not head-on)
└── low_light/           ← Underexposed / low-light shots
```

Each subdirectory accepts `.jpg`, `.jpeg`, or `.png` files.

---

## Category Guide

### `blackboard/`

**What it tests:** Chalkboard inversion, chalk-dust removal, CLAHE contrast enhancement.

**Capture tips:**
- Background should be near-black (not green)
- Text in white, yellow, or light-blue chalk
- Any subject — equations, notes, diagrams

**Expected OCR behaviour:**
- Pipeline inverts the image so chalk text becomes dark on white
- Morphological opening removes chalk-dust speckles
- High confidence (≥ 0.75) expected for clear boards

**Preprocessing path:** `_preprocess_chalkboard()` → invert → CLAHE (clip=3.0) → dust removal

---

### `greenboard/`

**What it tests:** HSV hue detection for green boards, LAB L-channel inversion.

**Capture tips:**
- Background should be distinctly green (not black or grey)
- Use white or pale-yellow chalk — coloured chalk may reduce contrast
- Avoid excessive board shine or moisture patches

**Expected OCR behaviour:**
- `_is_green_chalkboard()` detects green hue in the border region
- LAB L-channel used instead of BGR grayscale for cleaner chalk separation
- Similar confidence to blackboard when lit evenly

**Preprocessing path:** `_preprocess_chalkboard()` → LAB L-channel → invert → CLAHE (clip=3.0) → dust removal

---

### `whiteboard/`

**What it tests:** Glare suppression, bilateral smoothing, dark-text preservation.

**Capture tips:**
- Background should be white or light grey
- Dark marker text (black, blue, or red) preferred
- Capture from an angle slightly off-centre to expose specular glare

**Expected OCR behaviour:**
- `remove_glare()` inpaints specular hotspots (pixels > 240 brightness)
- Bilateral filter smooths noise while preserving marker edges
- CLAHE clip=2.0 (lower than chalkboard — less contrast lift needed)
- Very high confidence expected for clean whiteboard + dark marker

**Preprocessing path:** `_preprocess_whiteboard()` → CLAHE (clip=2.0) → glare suppression → bilateral filter

---

### `messy_handwriting/`

**What it tests:** Confidence routing between PaddleOCR and Tesseract, `needs_review` flag.

**Capture tips:**
- Rushed or informal handwriting (not printed)
- Overlapping lines, varying letter sizes, or tilted baselines
- Mixed print and cursive is ideal

**Expected OCR behaviour:**
- PaddleOCR confidence typically 0.50–0.74 → Tesseract fallback triggered
- `needs_review=True` likely when confidence < 0.50
- Region classification may produce more `"text"` than `"heading"` / `"formula"` types
- Raw text extraction still usable despite lower confidence

**Confidence thresholds:**
```
conf ≥ 0.75 → PaddleOCR result accepted (green)
conf 0.50–0.74 → Tesseract also run, best picked (yellow)
conf < 0.50 → both engines used, needs_review flag set (red)
```

---

### `tilted_board/`

**What it tests:** Perspective (tilt) correction in `board_detector.py`.

**Capture tips:**
- Photograph the board from 20–45° off-axis (not straight-on)
- Ensure the full board rectangle is visible in the frame
- Board should cover > 30% of the frame area (minimum area ratio for detection)

**Expected OCR behaviour:**
- `detect_board()` finds the largest 4-sided contour
- `_perspective_transform()` warps it to a flat rectangle
- `board.found = True` and `board.original_bbox` will be set
- Text confidence should be similar to a head-on shot after correction

**Failure mode:** If the board edges are not visible (cropped), `board.found = False` and
the full frame is used — confidence may be lower due to residual perspective distortion.

---

### `low_light/`

**What it tests:** Frame validation rejection for underexposed images.

**Capture tips:**
- Photograph a board in very dim conditions (no artificial lighting)
- Mean pixel brightness should be < 30 (pipeline threshold)
- Intentionally bad shots — these are expected to be rejected

**Expected OCR behaviour:**
- `validate_frame()` computes mean brightness of the grayscale image
- Frames with mean brightness < 30.0 are rejected with reason `"too_dark"`
- `FrameOCRResult.error = "skipped_invalid:too_dark"`
- The test harness marks this as `EXPECTED REJECTION` (not a failure)

**Other rejection reasons:**
```
too_small    → image < 480×320 px
too_blurry   → Laplacian variance < 50.0 (motion blur)
too_dark     → mean brightness < 30.0
```

---

## Adding Your Own Images

1. Take a photo with your phone or download a classroom image
2. Drop it into the appropriate subdirectory (e.g. `sample_images/whiteboard/lesson.jpg`)
3. Run the harness:
   ```bash
   cd backend
   .venv/bin/python scripts/test_ocr_local.py --category whiteboard
   ```
4. Or process a single image directly:
   ```bash
   .venv/bin/python scripts/test_ocr_local.py --image ../sample_images/whiteboard/lesson.jpg \
     --board-type whiteboard --save-debug ./debug_out
   ```

The harness automatically uses real images from the relevant subdirectory if they exist,
and generates a synthetic one as a fallback.

---

## OCR Quality Benchmarks

Expected confidence ranges for each category under good conditions:

| Category | Engine | Expected Confidence | `needs_review` |
|---|---|---|---|
| `blackboard` | PaddleOCR | ≥ 0.80 | No |
| `greenboard` | PaddleOCR | ≥ 0.75 | No |
| `whiteboard` | PaddleOCR | ≥ 0.85 | No |
| `messy_handwriting` | PaddleOCR + Tesseract | 0.45–0.70 | Sometimes |
| `tilted_board` | PaddleOCR | ≥ 0.70 (after correction) | No |
| `low_light` | — | REJECTED | — |

Confidence below 0.50 with `needs_review=True` is logged to the backend and surfaced in
the teacher dashboard as a frame that may need manual OCR correction.

---

## Synthetic Images (auto-generated)

When no real images are present in a subdirectory, `test_ocr_local.py` generates a
synthetic image for that category using OpenCV. Generated images are saved to
`backend/debug_out/<category>/00_synthetic_input.jpg` and labelled clearly in the output.

Synthetic images are not intended to match real-world accuracy — they validate that
the preprocessing pipeline runs correctly end-to-end.

---

## Related Files

| File | Purpose |
|---|---|
| `backend/scripts/test_ocr_local.py` | Full test harness (this tool) |
| `backend/scripts/test_ocr.py` | Single-image inspector |
| `backend/app/ocr/image_preprocessor.py` | Validation + board-type preprocessing |
| `backend/app/ocr/board_detector.py` | Perspective correction |
| `backend/app/ocr/ocr_engine.py` | PaddleOCR + Tesseract routing |
| `backend/app/ocr/ocr_service.py` | Full pipeline orchestrator |
| `docs/OCR_PIPELINE.md` | Pipeline architecture reference |
