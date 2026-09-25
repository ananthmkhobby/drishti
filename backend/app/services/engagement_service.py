"""
Engagement metrics derived from Whisper segment timestamps.

No ML models — pure arithmetic over {start, end, text} segment data.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Words-per-minute thresholds for engagement level classification
_HIGH_WPM_PER_MINUTE = 80   # ≥80 words in a 1-min window → high activity
_MED_WPM_PER_MINUTE  = 25   # ≥25 words                   → medium activity


def compute_engagement_metrics(
    recordings: list[Any],
) -> dict:
    """
    recordings: list of SessionAudio ORM rows with .segments and .duration_sec.
    Returns engagement dict suitable for injecting into the combined_analysis prompt.
    """
    # Merge segments across recordings, advancing timestamp offset per recording
    all_segments: list[dict] = []
    offset = 0.0
    total_duration = 0.0

    for rec in recordings:
        segs = rec.segments or []
        dur  = float(rec.duration_sec or 0)
        for s in segs:
            try:
                all_segments.append({
                    "start": float(s.get("start", 0)) + offset,
                    "end":   float(s.get("end",   0)) + offset,
                    "text":  str(s.get("text", "")),
                })
            except Exception:
                pass
        if dur > 0:
            total_duration += dur
            offset += dur

    if not all_segments or total_duration < 2:
        return _empty_metrics(total_duration)

    # ── Silence ratio ──────────────────────────────────────────────────────
    speech_sec = sum(max(0.0, s["end"] - s["start"]) for s in all_segments)
    silence_sec = max(0.0, total_duration - speech_sec)
    silence_ratio = silence_sec / total_duration

    # ── Overall WPM (during speech only) ──────────────────────────────────
    total_words = sum(len(s["text"].split()) for s in all_segments)
    speech_min = speech_sec / 60.0
    wpm = total_words / speech_min if speech_min > 0 else 0.0

    # ── Question count ─────────────────────────────────────────────────────
    question_count = sum(
        1 for s in all_segments if s["text"].strip().endswith("?")
    )

    # ── Per-minute engagement curve ────────────────────────────────────────
    bucket_words: dict[int, int] = {}
    for s in all_segments:
        bucket = int(s["start"] // 60)
        bucket_words[bucket] = bucket_words.get(bucket, 0) + len(s["text"].split())

    total_minutes = max(1, int(total_duration // 60) + 1)
    engagement_curve: list[dict] = []
    for minute in range(total_minutes):
        words = bucket_words.get(minute, 0)
        level = (
            "high"   if words >= _HIGH_WPM_PER_MINUTE else
            "medium" if words >= _MED_WPM_PER_MINUTE  else
            "low"
        )
        engagement_curve.append({"minute": minute + 1, "words": words, "level": level})

    # ── Liveness score 0-10 ────────────────────────────────────────────────
    speech_ratio   = 1.0 - silence_ratio                                  # 0-1
    question_rate  = min(1.0, question_count / max(1, total_minutes) / 2) # up to 2 q/min = max
    word_counts    = [bucket_words.get(i, 0) for i in range(total_minutes)]
    if len(word_counts) > 1:
        mean_w = sum(word_counts) / len(word_counts)
        variance = sum((w - mean_w) ** 2 for w in word_counts) / len(word_counts)
        variance_score = min(1.0, variance / 4000)
    else:
        variance_score = 0.0

    liveness_raw = (speech_ratio * 5.0) + (question_rate * 3.0) + (variance_score * 2.0)
    liveness_score = max(0, min(10, round(liveness_raw)))

    high_minutes = [e["minute"] for e in engagement_curve if e["level"] == "high"]
    low_minutes  = [e["minute"] for e in engagement_curve if e["level"] == "low"]

    logger.info(
        "Engagement metrics: duration=%.0fs silence=%.0f%% wpm=%.0f questions=%d liveness=%d/10",
        total_duration, silence_ratio * 100, wpm, question_count, liveness_score,
    )

    return {
        "total_duration_sec":       round(total_duration, 1),
        "silence_ratio":            round(silence_ratio, 3),
        "speech_density_wpm":       round(wpm, 1),
        "question_count":           question_count,
        "liveness_score":           liveness_score,
        "engagement_curve":         engagement_curve,
        "high_engagement_minutes":  high_minutes,
        "low_engagement_minutes":   low_minutes,
    }


def _empty_metrics(duration: float = 0.0) -> dict:
    return {
        "total_duration_sec":       duration,
        "silence_ratio":            1.0,
        "speech_density_wpm":       0.0,
        "question_count":           0,
        "liveness_score":           0,
        "engagement_curve":         [],
        "high_engagement_minutes":  [],
        "low_engagement_minutes":   [],
    }
