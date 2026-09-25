"""
Server-side audience analysis.

Primary detector: YuNet face detection + FER+ emotion classification.
Both run through OpenCV's DNN module — no TensorFlow needed, works on
Python 3.14. Model files live in backend/models/:
  face_detection_yunet_2023mar.onnx  (OpenCV model zoo, ~230 KB)
  emotion-ferplus-8.onnx             (ONNX model zoo, ~34 MB)

Fallback chain:
  1. DeepFace + RetinaFace  (only if `deepface` installed — Python ≤3.12)
  2. YuNet + FER+           (model files present — the normal path)
  3. Haar cascade           (last resort, no models needed; neutral-only)

Zone thresholds (face pixel size = max(w, h)):
  front:  >= 80 px  (close / front row)
  middle: 40–79 px  (mid rows)
  back:   <  40 px  (back rows / small distant faces)

Privacy: raw frames written to a temp file, analysed, then deleted immediately.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

_FRONT_PX  = 80
_MIDDLE_PX = 40

_MODELS_DIR   = Path(__file__).resolve().parent.parent.parent / "models"
_YUNET_PATH   = _MODELS_DIR / "face_detection_yunet_2023mar.onnx"
_FERPLUS_PATH = _MODELS_DIR / "emotion-ferplus-8.onnx"

# Minimum YuNet confidence to accept a detection. Kills the false positives
# Haar produced on circular objects and whiteboard writing.
_MIN_FACE_CONF = 0.65

_EMOTION_MAP: dict[str, str] = {
    "happy":    "happy",
    "surprise": "surprised",
    "fear":     "confused",
    "disgust":  "confused",
    "sad":      "disengaged",
    "angry":    "disengaged",
    "neutral":  "neutral",
}

_ZERO_EMOTIONS = {
    "happy": 0.0, "surprised": 0.0, "confused": 0.0, "disengaged": 0.0, "neutral": 100.0,
}


def _zone(face_size_px: int) -> str:
    if face_size_px >= _FRONT_PX:
        return "front"
    if face_size_px >= _MIDDLE_PX:
        return "middle"
    return "back"


# ── YuNet + FER+ (primary — OpenCV DNN, no TensorFlow) ───────────────────────

# FER+ output order (fixed by the model)
_FERPLUS_LABELS = [
    "neutral", "happiness", "surprise", "sadness",
    "anger", "disgust", "fear", "contempt",
]
_FERPLUS_MAP = {
    "neutral":   "neutral",
    "happiness": "happy",
    "surprise":  "surprised",
    "sadness":   "disengaged",
    "anger":     "disengaged",
    "contempt":  "disengaged",
    "disgust":   "confused",
    "fear":      "confused",
}

_dnn_lock = threading.Lock()
_yunet = None
_ferplus = None


def _get_dnn_models():
    """Lazy-load the DNN models once per process."""
    global _yunet, _ferplus
    import cv2

    if _yunet is None:
        _yunet = cv2.FaceDetectorYN.create(
            str(_YUNET_PATH), "", (320, 320), _MIN_FACE_CONF, 0.3, 5000,
        )
    if _ferplus is None:
        _ferplus = cv2.dnn.readNetFromONNX(str(_FERPLUS_PATH))
    return _yunet, _ferplus


def _classify_emotion(ferplus, gray_face) -> dict[str, float]:
    """Run FER+ on a grayscale face crop → per-bucket percentages."""
    import cv2
    import numpy as np

    resized = cv2.resize(gray_face, (64, 64), interpolation=cv2.INTER_CUBIC)
    blob = resized.reshape(1, 1, 64, 64).astype(np.float32)
    ferplus.setInput(blob)
    raw = ferplus.forward()[0]

    # Softmax → probabilities
    exp = np.exp(raw - raw.max())
    probs = exp / exp.sum()

    scores = {"happy": 0.0, "surprised": 0.0, "confused": 0.0, "disengaged": 0.0, "neutral": 0.0}
    for label, p in zip(_FERPLUS_LABELS, probs):
        scores[_FERPLUS_MAP[label]] += float(p) * 100.0
    return {k: round(v, 1) for k, v in scores.items()}


def _analyse_dnn(image_path: str) -> list[dict[str, Any]]:
    """
    YuNet face detection + FER+ emotion classification.
    Attentiveness = face is confidently detected AND roughly frontal
    (nose landmark sits between the eyes) — a turned-away head fails this.
    """
    import cv2

    img = cv2.imread(image_path)
    if img is None:
        return []

    img_h, img_w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    with _dnn_lock:
        yunet, ferplus = _get_dnn_models()
        yunet.setInputSize((img_w, img_h))
        _, raw = yunet.detect(img)

        faces: list[dict[str, Any]] = []
        if raw is None:
            return faces

        for row in raw:
            x, y, w, h = (int(v) for v in row[:4])
            conf = float(row[14])
            if conf < _MIN_FACE_CONF or w < 8 or h < 8:
                continue

            # Landmarks: right eye, left eye, nose tip, right/left mouth corner
            re_x, re_y = float(row[4]), float(row[5])
            le_x, le_y = float(row[6]), float(row[7])
            nose_x, nose_y = float(row[8]), float(row[9])
            rm_y, lm_y = float(row[11]), float(row[13])

            # Yaw: nose between the eyes. 0.5 = dead-on frontal; a 3/4-turned
            # head measures ~0.3 / ~0.7 (calibrated on sample portraits).
            eye_min = min(re_x, le_x)
            eye_span = max(1.0, abs(le_x - re_x))
            yaw_ratio = (nose_x - eye_min) / eye_span

            # Pitch: nose tip position between eye line and mouth line.
            # ~0.55 when level; drifts out of band when looking down or up.
            eye_cy = (re_y + le_y) / 2
            mouth_cy = (rm_y + lm_y) / 2
            pitch_ratio = (nose_y - eye_cy) / max(1.0, mouth_cy - eye_cy)

            # Widened from the original 0.35-0.65 / 0.35-0.80 band, which was
            # calibrated on posed portrait photos — a real classroom photo is
            # shot from wherever the teacher's phone happens to be (off to
            # one side, above head height, etc.), and a student who is
            # genuinely facing the front of the room routinely measured just
            # outside that narrow band, reading as "not attentive" even
            # though a human looking at the same photo would call it fine.
            frontal = (0.28 <= yaw_ratio <= 0.72) and (0.25 <= pitch_ratio <= 0.90)

            # Emotion on the (clamped) face crop
            x1, y1 = max(0, x), max(0, y)
            x2, y2 = min(img_w, x + w), min(img_h, y + h)
            crop = gray[y1:y2, x1:x2]
            if crop.size > 0:
                emotion_scores = _classify_emotion(ferplus, crop)
            else:
                emotion_scores = dict(_ZERO_EMOTIONS)
            dominant = max(emotion_scores.items(), key=lambda kv: kv[1])[0]

            # FER+ was trained on posed studio expressions and is noisy on
            # real candid photos — a calm, attentive face very often lands
            # a hair under "neutral" in the model's own probabilities, with
            # "disengaged" (sadness/anger/contempt) winning by a point or
            # two. Treating that bare plurality as equivalent to genuinely
            # checked-out is what let a single attentive-looking face score
            # 0%. Only let "disengaged" override attentiveness when it
            # clearly beats neutral, not on a coin-flip margin.
            is_disengaged = (
                dominant == "disengaged"
                and emotion_scores["disengaged"] - emotion_scores["neutral"] >= 15.0
            )

            face_size = max(w, h)
            faces.append({
                "box":          {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1},
                "face_size":    face_size,
                "zone":         _zone(face_size),
                "confidence":   round(conf, 3),
                # Attentive = facing the camera and not clearly checked out
                "attentive":    frontal and not is_disengaged,
                "emotion":      dominant,
                "emotion_scores": emotion_scores,
            })
    return faces


# ── OpenCV Haar cascade (last-resort fallback) ────────────────────────────────

def _analyse_opencv(image_path: str) -> list[dict[str, Any]]:
    """
    Detect faces using the Haar cascade bundled with opencv-python-headless.
    No extra install required. Detects frontal faces only; detected face =
    roughly attentive (frontal-facing). Emotion always reported as neutral.
    """
    import cv2

    img = cv2.imread(image_path)
    if img is None:
        return []

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Equalise histogram to handle varying classroom lighting
    gray = cv2.equalizeHist(gray)

    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(cascade_path)

    # scaleFactor 1.05 = slower but catches more faces at distance
    raw = detector.detectMultiScale(
        gray,
        scaleFactor=1.05,
        minNeighbors=4,
        minSize=(20, 20),
        flags=cv2.CASCADE_SCALE_IMAGE,
    )

    faces: list[dict[str, Any]] = []
    if len(raw) == 0:
        return faces

    for (x, y, w, h) in raw:
        face_size = max(int(w), int(h))
        faces.append({
            "box":          {"x": int(x), "y": int(y), "w": int(w), "h": int(h)},
            "face_size":    face_size,
            "zone":         _zone(face_size),
            "confidence":   0.85,   # Haar only detects frontal faces → treated as attentive
            "attentive":    True,
            "emotion":      "neutral",
            "emotion_scores": dict(_ZERO_EMOTIONS),
        })
    return faces


# ── DeepFace + RetinaFace (optional — requires Python ≤3.12 + deepface) ──────

def _analyse_deepface(image_path: str) -> list[dict[str, Any]]:
    """
    Richer analysis: RetinaFace detector + 7-class emotion via DeepFace.
    Small faces (<40 px) are upscaled 4× before emotion classification.
    Only used when `deepface` and `tf-keras` are installed.
    """
    import cv2
    import numpy as np
    from deepface import DeepFace

    img = cv2.imread(image_path)
    if img is None:
        return []

    img_h, img_w = img.shape[:2]

    try:
        raw_results = DeepFace.analyze(
            img_path=image_path,
            actions=["emotion"],
            detector_backend="retinaface",
            enforce_detection=False,
            silent=True,
        )
    except Exception:
        return []

    if not isinstance(raw_results, list):
        raw_results = [raw_results]

    faces: list[dict[str, Any]] = []
    for r in raw_results:
        region = r.get("region") or {}
        x = int(region.get("x", 0))
        y = int(region.get("y", 0))
        w = int(region.get("w", 0))
        h = int(region.get("h", 0))
        face_size = max(w, h)
        if face_size < 8:
            continue

        confidence = float(r.get("face_confidence") or 1.0)
        emotion_scores_raw: dict[str, float] = r.get("emotion") or {}
        dominant_raw: str = r.get("dominant_emotion") or "neutral"

        # Upscale small faces for better emotion accuracy
        if face_size < 40:
            x1, y1 = max(0, x), max(0, y)
            x2, y2 = min(img_w, x + w), min(img_h, y + h)
            crop = img[y1:y2, x1:x2]
            if crop.size > 0:
                upscaled = cv2.resize(
                    crop, (crop.shape[1] * 4, crop.shape[0] * 4),
                    interpolation=cv2.INTER_CUBIC,
                )
                tmp_up = image_path + "_up.jpg"
                try:
                    cv2.imwrite(tmp_up, upscaled)
                    up = DeepFace.analyze(
                        img_path=tmp_up,
                        actions=["emotion"],
                        detector_backend="retinaface",
                        enforce_detection=False,
                        silent=True,
                    )
                    if up:
                        best = up[0] if isinstance(up, list) else up
                        emotion_scores_raw = best.get("emotion") or emotion_scores_raw
                        dominant_raw = best.get("dominant_emotion") or dominant_raw
                except Exception:
                    pass
                finally:
                    if os.path.exists(tmp_up):
                        os.unlink(tmp_up)

        mapped_scores = {
            "happy":      float(emotion_scores_raw.get("happy", 0)),
            "surprised":  float(emotion_scores_raw.get("surprise", 0)),
            "confused":   (float(emotion_scores_raw.get("fear", 0)) + float(emotion_scores_raw.get("disgust", 0))) / 2,
            "disengaged": (float(emotion_scores_raw.get("sad", 0)) + float(emotion_scores_raw.get("angry", 0))) / 2,
            "neutral":    float(emotion_scores_raw.get("neutral", 0)),
        }
        faces.append({
            "box":          {"x": x, "y": y, "w": w, "h": h},
            "face_size":    face_size,
            "zone":         _zone(face_size),
            "confidence":   confidence,
            "attentive":    confidence >= 0.75,
            "emotion":      _EMOTION_MAP.get(dominant_raw, "neutral"),
            "emotion_scores": mapped_scores,
        })
    return faces


def _analyse_frame_sync(image_path: str) -> list[dict[str, Any]]:
    """DeepFace → YuNet+FER+ → Haar cascade, best available first."""
    try:
        import deepface  # noqa: F401
        return _analyse_deepface(image_path)
    except ImportError:
        pass
    if _YUNET_PATH.exists() and _FERPLUS_PATH.exists():
        return _analyse_dnn(image_path)
    return _analyse_opencv(image_path)


# ── Aggregation ───────────────────────────────────────────────────────────────

def _aggregate(faces: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[dict]] = {"front": [], "middle": [], "back": []}
    for f in faces:
        buckets[f["zone"]].append(f)

    def _zone_summary(zf: list[dict]) -> dict:
        if not zf:
            return {
                "count": 0, "attention_pct": 0.0, "dominant_emotion": "neutral",
                "emotions": {"happy": 0.0, "confused": 0.0, "surprised": 0.0, "disengaged": 0.0, "neutral": 0.0},
            }
        att = round(sum(1 for f in zf if f["attentive"]) / len(zf) * 100, 1)
        totals: dict[str, float] = {}
        for f in zf:
            for em, sc in f["emotion_scores"].items():
                totals[em] = totals.get(em, 0.0) + sc
        n = len(zf)
        avg = {em: round(sc / n, 1) for em, sc in totals.items()}
        dominant = max(avg.items(), key=lambda kv: kv[1])[0] if avg else "neutral"
        return {"count": len(zf), "attention_pct": att, "dominant_emotion": dominant, "emotions": avg}

    total = len(faces)
    overall_att = round(sum(1 for f in faces if f["attentive"]) / total * 100, 1) if total else 0.0

    totals: dict[str, float] = {}
    for f in faces:
        for em, sc in f["emotion_scores"].items():
            totals[em] = totals.get(em, 0.0) + sc
    emotion_breakdown = (
        {em: round(sc / total, 1) for em, sc in totals.items()} if total
        else {"happy": 0.0, "confused": 0.0, "surprised": 0.0, "disengaged": 0.0, "neutral": 0.0}
    )
    dominant_overall = max(emotion_breakdown.items(), key=lambda kv: kv[1])[0] if total else "neutral"

    return {
        "faces_detected":    total,
        "attention_pct":     overall_att,
        "dominant_emotion":  dominant_overall,
        "zone_summary":      {k: _zone_summary(v) for k, v in buckets.items()},
        "emotion_breakdown": emotion_breakdown,
        "faces": [
            {
                "box":        f["box"],
                "zone":       f["zone"],
                "emotion":    f["emotion"],
                "confidence": round(f["confidence"], 3),
                "attentive":  f["attentive"],
            }
            for f in faces
        ],
    }


# ── Async entry point ─────────────────────────────────────────────────────────

async def analyse_audience_frame(image_bytes: bytes) -> dict[str, Any]:
    """
    Write bytes to temp file, run analysis in thread pool (CPU-bound),
    delete temp file, return aggregated result.
    """
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name

        loop = asyncio.get_event_loop()
        faces = await loop.run_in_executor(None, _analyse_frame_sync, tmp_path)
        return _aggregate(faces)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
