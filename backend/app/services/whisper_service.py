"""
Whisper transcription service.

Calls openai.audio.transcriptions.create() with verbose_json to get
both the full transcript and per-segment timestamps.

Hallucination guards:
  - Minimum 3-second recording required
  - Segments with no_speech_prob > 0.6 are dropped
  - If remaining transcript matches known hallucination patterns → return empty
  - avg_logprob < -1.0 on a segment means very uncertain → drop it

Large audio handling:
  - Whisper hard limit is 25 MB
  - Files > 24 MB are split into ~12-min chunks using ffmpeg
  - Each chunk is transcribed separately; results are concatenated
"""
from __future__ import annotations

import asyncio
import logging
import io
import re
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_FILE_MB = 25        # Whisper API hard limit
_CHUNK_LIMIT_MB = 24     # Split threshold (leave 1MB headroom)
_CHUNK_DURATION_SEC = 700  # ~11.7 min — keeps each chunk safely under 24 MB at 16kHz mono
_MIN_DURATION_SEC = 2.0  # Don't bother transcribing recordings shorter than this

# Whisper commonly hallucinates these strings on silence/noise
_HALLUCINATION_PATTERNS = re.compile(
    r"^\s*("
    r"thank you(\s+for\s+watching)?[.!]?|"
    r"thanks(\s+for\s+watching)?[.!]?|"
    r"subscribe(\s+for more)?[.!]?|"
    r"please like and subscribe[.!]?|"
    r"\[music\]|"
    r"\(music\)|"
    r"♪+|"
    r"\.{1,5}|"
    r"\s*"
    r")\s*$",
    re.IGNORECASE,
)

# Drop segments where Whisper itself is not confident there is speech
_NO_SPEECH_THRESHOLD = 0.60  # prob > this → likely silence
_AVG_LOGPROB_THRESHOLD = -1.0  # lower → very uncertain transcription


class TranscriptResult:
    __slots__ = ("text", "segments", "language", "duration_sec")

    def __init__(
        self,
        text: str,
        segments: list[dict],
        language: str,
        duration_sec: float,
    ) -> None:
        self.text = text
        self.segments = segments      # [{id, start, end, text}, ...]
        self.language = language
        self.duration_sec = duration_sec


async def _split_audio_ffmpeg(audio_data: bytes, filename: str) -> list[tuple[bytes, float]]:
    """
    Split audio bytes into chunks of at most _CHUNK_DURATION_SEC using ffmpeg.
    Returns list of (chunk_bytes, start_sec) pairs, in order.
    """
    ext = Path(filename).suffix.lstrip(".") or "wav"
    chunks: list[tuple[bytes, float]] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_in = Path(tmpdir) / f"input.{ext}"
        tmp_in.write_bytes(audio_data)

        # First get total duration
        probe = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(tmp_in),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        probe_out, _ = await probe.communicate()
        try:
            total_dur = float(probe_out.decode().strip())
        except (ValueError, TypeError):
            # Can't probe — return as single chunk and let Whisper handle it
            return [(audio_data, 0.0)]

        if total_dur <= _CHUNK_DURATION_SEC:
            return [(audio_data, 0.0)]

        # Split into segments
        seg_dir = Path(tmpdir) / "segs"
        seg_dir.mkdir()
        seg_proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", str(tmp_in),
            "-f", "segment",
            "-segment_time", str(_CHUNK_DURATION_SEC),
            "-ar", "16000", "-ac", "1",
            str(seg_dir / f"chunk_%03d.wav"),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, seg_err = await seg_proc.communicate()
        if seg_proc.returncode != 0:
            logger.warning("ffmpeg audio split failed: %s", seg_err.decode()[-300:])
            return [(audio_data, 0.0)]

        for i, seg_path in enumerate(sorted(seg_dir.glob("chunk_*.wav"))):
            start_sec = i * _CHUNK_DURATION_SEC
            chunks.append((seg_path.read_bytes(), start_sec))
            logger.info(
                "Audio chunk %d: %.1f KB start=%.0fs",
                i, len(chunks[-1][0]) / 1024, start_sec,
            )

    return chunks if chunks else [(audio_data, 0.0)]


async def transcribe_local(
    audio_data: bytes,
    filename: str,
    base_url: str,
    language: str | None = None,
    timeout_sec: float = 25.0,
) -> TranscriptResult | None:
    """
    Transcribe via a local whisper-server (whisper.cpp) instance — for the
    voice COMMAND path only (short, deliberate utterances), not the
    long-form recording pipeline; see the config.py comment on
    local_whisper_enabled for why.

    timeout_sec default is 25s, not the sub-second latency this path is
    named for — that number was only ever validated on a Mac with GPU
    acceleration. On this Pi's CPU-only ARM hardware, a real, successful
    local transcription of a several-second command can itself take
    10s+ (confirmed 2026-09-17: whisper.cpp was still processing a 6.7s
    clip past the previous 10s timeout, which aborted a transcription
    that would otherwise have succeeded, wastefully falling back to a
    cloud call that then ALSO failed). Local is still worth attempting
    even at this speed — no network dependency — as long as the timeout
    doesn't cut off a transcription that was actually about to finish.

    Returns None (never raises) on any failure — connection refused, timeout,
    bad response — so the caller can fall back to transcribe() (OpenAI)
    exactly like the local/cloud pattern already used for intent
    classification. This is a "try local first" helper, not a hard
    requirement.
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/inference",
                files={"file": (filename, audio_data, _mime_for(filename))},
                data={"response_format": "json", "language": language or "en"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.info("Local whisper-server unavailable (%s) — falling back to cloud", exc)
        return None

    raw_text = (data.get("text") or "").strip()

    # No per-segment confidence scores from this endpoint (that's what the
    # cloud path's no_speech_prob/avg_logprob filtering leans on) — the one
    # guard that still applies cheaply here is the same known-filler-phrase
    # check used everywhere else. Audio bytes are compressed (webm/opus),
    # so there's no cheap way to estimate real duration without an ffprobe
    # subprocess call — not worth paying that cost on this fast path just
    # for a minimum-duration gate.
    if raw_text and _HALLUCINATION_PATTERNS.fullmatch(raw_text):
        logger.info("Local whisper: suppressing hallucinated transcript %r", raw_text)
        raw_text = ""

    logger.info("Local whisper: file=%s chars=%d", filename, len(raw_text))
    return TranscriptResult(text=raw_text, segments=[], language=language or "en", duration_sec=0.0)


async def transcribe(
    audio_data: bytes,
    filename: str,
    api_key: str,
    language: str | None = None,
    min_duration_sec: float = _MIN_DURATION_SEC,
    timeout_sec: float = 120.0,
) -> TranscriptResult:
    """
    Transcribe audio bytes using OpenAI Whisper.

    Files > 24 MB are automatically split into ~12-min chunks and each
    chunk is transcribed separately; results are merged in order.

    Returns TranscriptResult. text="" when audio is silent/noise.
    Raises RuntimeError on API failure.

    min_duration_sec defaults to the module-level guard (2.0s), tuned for
    the long-form lecture-recording path where a very short clip is more
    likely to be an accidental blip than real content. A deliberate,
    VAD-stopped guided-practice answer is different — a short but complete
    answer ("42", "yes") could legitimately land under 2s once VAD's own
    silence tail is subtracted, and silently blanking a real answer reads
    as "didn't catch an answer" for something the student actually said
    (confirmed as a real risk 2026-09-17, fixed here 2026-09-19). Callers
    on that path should pass a much lower value.

    timeout_sec bounds the actual OpenAI API call — the openai SDK's own
    default (no timeout passed) is ~600s PLUS up to 2 automatic retries,
    so on a flaky/slow connection (a Pi's wifi, say) a single transcription
    could silently hang for the better part of 30 minutes with nothing
    surfaced to the user. 120s default is generous enough for the long-
    form lecture-recording path this was originally written for; the
    voice-COMMAND path (a few seconds of speech, answered live mid-lesson)
    passes a much tighter value — see voice.py's _transcribe_command,
    where an unbounded hang here was confirmed to be exactly what made a
    voice command sit on "Thinking…" for several minutes before failing.
    """
    size_mb = len(audio_data) / (1024 * 1024)
    if size_mb > _CHUNK_LIMIT_MB:
        logger.info(
            "Audio %.1f MB > %.0f MB limit — splitting into chunks of %ds each",
            size_mb, _CHUNK_LIMIT_MB, _CHUNK_DURATION_SEC,
        )
        chunks = await _split_audio_ffmpeg(audio_data, filename)
        if len(chunks) > 1:
            return await _transcribe_chunked(chunks, api_key, language)
        # Split failed — fall through and let the size check below handle it gracefully

    if size_mb > _MAX_FILE_MB:
        logger.warning(
            "Audio %.1f MB still exceeds hard limit after split attempt — skipping transcription",
            size_mb,
        )
        return TranscriptResult(text="", segments=[], language="en", duration_sec=0)

    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise RuntimeError("openai package not installed") from exc

    client = AsyncOpenAI(api_key=api_key)

    audio_file = (filename, io.BytesIO(audio_data), _mime_for(filename))

    kwargs: dict = dict(
        model="whisper-1",
        file=audio_file,
        response_format="verbose_json",
        timestamp_granularities=["segment"],
        temperature=0,  # deterministic — reduces hallucination
        timeout=timeout_sec,
    )
    if language:
        kwargs["language"] = language  # strong signal cuts hallucination significantly

    try:
        response = await client.audio.transcriptions.create(**kwargs)
    except Exception as exc:
        raise RuntimeError(f"Whisper transcription failed: {exc}") from exc

    raw_text = (getattr(response, "text", "") or "").strip()
    raw_segs = getattr(response, "segments", None) or []
    detected_lang = getattr(response, "language", "en") or "en"
    duration = float(getattr(response, "duration", 0) or 0)

    # ── Guard 1: too short to contain real speech ──────────────────────────────
    if duration < min_duration_sec:
        logger.info(
            "Whisper: skipping transcript — recording too short (%.1fs < %.1fs)",
            duration, min_duration_sec,
        )
        return TranscriptResult(text="", segments=[], language=detected_lang, duration_sec=duration)

    # ── Guard 2: filter low-confidence / silence segments ─────────────────────
    good_segments = []
    for i, s in enumerate(raw_segs):
        def _g(key: str, default):
            return s.get(key, default) if isinstance(s, dict) else getattr(s, key, default)

        no_speech_prob = float(_g("no_speech_prob", 0.0))
        avg_logprob    = float(_g("avg_logprob", 0.0))
        seg_text       = str(_g("text", "")).strip()

        if no_speech_prob > _NO_SPEECH_THRESHOLD:
            logger.debug("Dropping segment %d: no_speech_prob=%.2f text=%r", i, no_speech_prob, seg_text)
            continue
        if avg_logprob < _AVG_LOGPROB_THRESHOLD:
            logger.debug("Dropping segment %d: avg_logprob=%.2f text=%r", i, avg_logprob, seg_text)
            continue

        good_segments.append({
            "id":    _g("id", i),
            "start": float(_g("start", 0)),
            "end":   float(_g("end", 0)),
            "text":  seg_text,
        })

    clean_text = " ".join(s["text"] for s in good_segments).strip()

    # ── Guard 3: known hallucination patterns on silence ──────────────────────
    if clean_text and _HALLUCINATION_PATTERNS.fullmatch(clean_text):
        logger.info("Whisper: suppressing hallucinated transcript %r", clean_text)
        clean_text = ""
        good_segments = []

    # If all segments were noise, also blank the text
    if not good_segments:
        clean_text = ""

    logger.info(
        "Whisper: file=%s lang=%s duration=%.1fs raw_segs=%d good_segs=%d chars=%d",
        filename, detected_lang, duration, len(raw_segs), len(good_segments), len(clean_text),
    )
    return TranscriptResult(
        text=clean_text,
        segments=good_segments,
        language=detected_lang,
        duration_sec=duration,
    )


async def _transcribe_chunked(
    chunks: list[tuple[bytes, float]],
    api_key: str,
    language: str | None,
) -> TranscriptResult:
    """Transcribe multiple audio chunks sequentially and merge results."""
    all_segments: list[dict] = []
    all_text_parts: list[str] = []
    detected_lang = "en"
    total_duration = 0.0

    for chunk_bytes, start_offset in chunks:
        try:
            result = await transcribe(chunk_bytes, "chunk.wav", api_key, language)
        except Exception as exc:
            logger.warning("Chunk transcription failed (offset=%.0fs): %s", start_offset, exc)
            continue

        if result.language:
            detected_lang = result.language
        total_duration = max(total_duration, start_offset + (result.duration_sec or 0))

        if result.text:
            all_text_parts.append(result.text)

        for seg in result.segments:
            adjusted = dict(seg)
            adjusted["start"] = seg["start"] + start_offset
            adjusted["end"]   = seg["end"]   + start_offset
            all_segments.append(adjusted)

    combined_text = " ".join(all_text_parts).strip()
    logger.info(
        "Chunked transcription: %d chunks → %d chars lang=%s",
        len(chunks), len(combined_text), detected_lang,
    )
    return TranscriptResult(
        text=combined_text,
        segments=all_segments,
        language=detected_lang,
        duration_sec=total_duration,
    )


def _mime_for(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    return {
        "webm": "audio/webm",
        "ogg":  "audio/ogg",
        "mp4":  "audio/mp4",
        "m4a":  "audio/mp4",
        "wav":  "audio/wav",
        "mp3":  "audio/mpeg",
    }.get(ext, "audio/webm")
