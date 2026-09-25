# Skill: OCR Processing

**Purpose:** Defines the step-by-step process for extracting text from classroom board images. Covers image preprocessing, engine selection, confidence handling, and multi-frame merging.

---

## Inputs

- One or more JPEG/PNG frames from a classroom session
- Session metadata: `board_type` (chalkboard / whiteboard / smartboard), `subject`, `grade`
- Frame sequence numbers and capture timestamps

---

## Step-by-Step

### Step 1: Validate Frame
```python
# Reject frames that are:
# - Too blurry (Laplacian variance < 50)
# - Too dark (mean pixel value < 30)
# - Too small (<480×320 px)
def is_valid_frame(image) -> bool:
    if laplacian_variance(image) < 50:
        return False  # motion blur
    if mean_brightness(image) < 30:
        return False  # unde rexposed
    if image.shape[0] < 320 or image.shape[1] < 480:
        return False
    return True
```
Invalid frames: log as `skipped_invalid`, do not process further.

---

### Step 2: Board Detection
Use OpenCV contour detection to locate the board region:
```python
# Approach: find the largest rectangular contour in the image
# that occupies >30% of frame area
board_bbox = detect_largest_rectangle(image, min_area_ratio=0.30)
if board_bbox is None:
    # No board detected — use full frame
    board_region = image
else:
    board_region = crop_to_bbox(image, board_bbox)
```

---

### Step 3: Perspective Correction
If board was captured at an angle:
```python
# Apply homography transform using the detected board corners
corrected = cv2.warpPerspective(board_region, H, (target_w, target_h))
```
Skip if board detection used full frame (no perspective to correct).

---

### Step 4: Preprocessing based on board type

**Chalkboard** (light text on dark background):
```python
image = cv2.bitwise_not(image)          # invert: dark text on white
image = apply_clahe(image, clip=3.0)    # enhance contrast
image = remove_chalk_dust(image)        # morphological opening
```

**Whiteboard / Marker board** (dark text on light background):
```python
image = apply_clahe(image, clip=2.0)
image = remove_glare(image)             # suppress high-intensity regions
```

**Smartboard** (projected content):
```python
image = apply_clahe(image, clip=1.5)    # light enhancement only
```

---

### Step 5: OCR Extraction

```python
# Primary: PaddleOCR
result = paddleocr.ocr(image, cls=True)
confidence = mean([r[1][1] for r in result])

if confidence >= 0.75:
    use_result = result
    engine = "paddleocr"

elif confidence >= 0.50:
    # Run Tesseract as well, pick higher confidence
    tess_result = tesseract.image_to_data(image)
    tess_confidence = parse_tesseract_confidence(tess_result)
    if tess_confidence > confidence:
        use_result = tess_result
        engine = "tesseract"
    else:
        use_result = result
        engine = "paddleocr"

else:
    # Low confidence — use best available, flag for review
    use_result = result
    engine = "paddleocr"
    flag_for_review = True
```

---

### Step 6: Region Classification

For each detected text block, classify type:
```python
def classify_region(text: str, bbox, image) -> str:
    if is_formula(text):       return "formula"
    if is_heading(text, bbox): return "heading"
    if is_list_item(text):     return "list"
    if is_diagram(bbox, image): return "diagram"
    return "text"

def is_formula(text):
    return bool(re.search(r'[=\+\-×÷∫∑√]', text)) and len(text.split()) < 10

def is_heading(text, bbox):
    # Larger font (bbox height > 1.5× median), short text, top 20% of board
    return bbox_height(bbox) > 1.5 * median_height and len(text.split()) < 8
```

---

### Step 7: Structured Output per Frame

```python
{
  "frame_id": "uuid",
  "engine_used": "paddleocr",
  "confidence": 0.82,
  "regions": [
    { "type": "heading", "content": "Newton's Laws", "bbox": [...], "confidence": 0.91 },
    { "type": "formula", "content": "F = ma", "bbox": [...], "confidence": 0.88 },
    { "type": "text", "content": "Where F is force...", "bbox": [...], "confidence": 0.79 },
    { "type": "diagram", "content": null, "bbox": [...], "confidence": null }
  ]
}
```

---

### Step 8: Multi-Frame Merge

After processing all frames in a session:
```python
def merge_session_frames(frame_results: list) -> str:
    all_regions = []
    for frame in sorted(frame_results, key=lambda f: f["sequence_no"]):
        for region in frame["regions"]:
            if region["type"] == "diagram":
                continue  # skip diagrams in text merge
            if not is_near_duplicate(region["content"], all_regions):
                all_regions.append(region)

    # Order: headings first, then lists, then text, formulas inline
    return format_as_markdown(all_regions)
```

Similarity threshold for near-duplicate: >85% token overlap.

---

## Error States

| State | Trigger | Action |
|---|---|---|
| `skipped_invalid` | Frame fails validation | Log, continue to next frame |
| `low_confidence` | Mean OCR confidence <0.50 | Use result, flag in DB |
| `no_text_detected` | Zero regions found | Log warning, skip frame in merge |
| `ocr_failed` | Engine throws exception | Mark frame `ocr_status=failed`, alert |

A session is processable if ≥1 frame has `ocr_status=done` with confidence ≥0.50.

---

## Performance Notes

- PaddleOCR full model: ~2–5s per frame on CPU server
- Tesseract: ~1–3s per frame
- Preprocessing: <0.5s per frame with OpenCV
- Target: full session OCR (20 frames) in <2 minutes on 4-core server
