# ACI – OCR Pipeline

---

## Pipeline Overview

```
Raw Frame
    │
    ▼
[1] Board Detection
    │  OpenCV contour detection, edge finding
    │  Reject frames without detectable board
    │
    ▼
[2] Perspective Correction
    │  Homography transform to flatten tilted/angled captures
    │  Handles tripod misalignment and handheld angles
    │
    ▼
[3] Glare & Reflection Removal
    │  Detect high-intensity specular regions
    │  Inpaint or suppress glare zones
    │
    ▼
[4] Contrast Enhancement
    │  CLAHE (Contrast Limited Adaptive Histogram Equalization)
    │  Improve text-background separation on chalk / marker
    │
    ▼
[5] Noise Reduction
    │  Gaussian blur for chalk dust artifacts
    │  Morphological ops to clean isolated specks
    │
    ▼
[6] OCR Extraction
    │  PaddleOCR (primary)
    │  Tesseract (fallback if confidence < threshold)
    │
    ▼
[7] Region Classification
    │  Classify regions: text | heading | formula | diagram
    │  Preserve bounding box metadata for each region
    │
    ▼
[8] Multi-Frame Merge
    │  Deduplicate content across frames from same session
    │  Stitch partial board captures into unified text
    │
    ▼
Structured Text Output (JSON)
```

---

## OCR Requirements

| ID | Requirement |
|---|---|
| ACI-OCR-001 | Detect handwritten chalk text |
| ACI-OCR-002 | Handle messy / irregular handwriting |
| ACI-OCR-003 | Support marker writing on whiteboards |
| ACI-OCR-004 | Detect and flag diagram regions |
| ACI-OCR-005 | Merge captures from the same session |
| ACI-OCR-006 | Handle partially erased text gracefully |
| ACI-OCR-007 | Ignore background noise (chalk dust, smears) |
| ACI-OCR-008 | Handle uneven or low lighting |

---

## Real Classroom Assumptions

The pipeline must tolerate:
- Messy, informal handwriting
- Chalk dust and smearing
- Board glare from windows or tube lights
- Tilted or off-center camera angles
- Partial erasure mid-session
- Teacher's body partially blocking the board
- Mixed text + diagram layouts
- Low-end Android cameras (8MP, no OIS)
- Frames captured every 20–60s (not video)

---

## OCR Engine Strategy

### Primary: PaddleOCR
- Best accuracy on handwritten, low-quality, non-Latin text
- Supports detection + recognition in one pass
- Runs on CPU; can run on-device (lite model) or server-side (full model)
- Returns bounding boxes + text + confidence per region

### Fallback: Tesseract OCR
- Used when PaddleOCR confidence falls below threshold (e.g., <0.65)
- Also used as a parallel validator for critical frames
- Slower but useful as a cross-check

### Confidence Threshold Logic
```
paddleocr_confidence >= 0.75  → use PaddleOCR result
paddleocr_confidence 0.50–0.74 → run Tesseract, pick higher confidence
paddleocr_confidence < 0.50  → flag frame for manual review, still return best result
```

---

## Multi-Frame Session Merge

A session produces N frames (1 every 30s → ~40 frames/hr). The merge step:

1. Run OCR on each frame independently
2. Extract text blocks with timestamps
3. Diff adjacent frames to detect new content (board additions)
4. Deduplicate repeated content across frames
5. Order blocks by appearance sequence
6. Produce a single unified text document per session

Merge strategy: **union with temporal ordering** — keep first occurrence of each unique text block.

---

## Output Format

```json
{
  "session_id": "uuid",
  "merged_text": "Newton's Second Law\nF = ma\n...",
  "regions": [
    {
      "frame_id": "uuid",
      "sequence_no": 3,
      "type": "heading",
      "content": "Newton's Second Law",
      "bbox": [120, 45, 680, 90],
      "confidence": 0.91
    },
    {
      "frame_id": "uuid",
      "sequence_no": 3,
      "type": "formula",
      "content": "F = ma",
      "bbox": [200, 100, 350, 140],
      "confidence": 0.88
    },
    {
      "frame_id": "uuid",
      "sequence_no": 5,
      "type": "diagram",
      "content": null,
      "bbox": [400, 200, 700, 500],
      "confidence": null
    }
  ]
}
```

---

## Region Types

| Type | Detection Method |
|---|---|
| `heading` | Larger font size, top region, underlined |
| `text` | Standard paragraph text |
| `formula` | Contains `=`, math symbols, isolated short lines |
| `list` | Numbered or bulleted items |
| `diagram` | Low text density region with connected components |
| `table` | Grid-like structure |

---

## On-Device vs Server OCR

| Mode | When Used | Model |
|---|---|---|
| On-device lite | Offline mode, quick preview | PaddleOCR mobile lite |
| Server full | Connected, final processing | PaddleOCR full + Tesseract |

For MVP, on-device OCR is optional — the full pipeline runs server-side after sync.

---

## Performance Targets

| Metric | Target |
|---|---|
| OCR accuracy (readable text) | >75% |
| Per-frame processing time (server) | <10s |
| Per-session merge time | <30s |
| Low-confidence frame rate | <20% of frames |

---

## Known Limitations (MVP)

- Diagrams: detected but not interpreted (Phase 3 adds Vision AI)
- Mathematical equations: OCR may misread complex symbols
- Mixed-language text: English primary; multilingual planned Phase 4
- Severely erased content: not recoverable
- Camera motion blur: severe blur frames are skipped
