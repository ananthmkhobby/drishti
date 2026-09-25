"""
On-device wake-word ("Hey XP") detection via openWakeWord — free,
open-source, ONNX/CPU-only, no account or review queue (unlike the
Picovoice Porcupine alternative this replaced, see wake_word_enabled in
config.py). Runs as a single background asyncio task for the life of this
process, reading raw audio from THIS machine's own microphone, and pushes a
detection to every currently-connected frontend over WebSocket (see
app/routers/wake_word.py) — the frontend then opens the assistant exactly
as a manual mic tap would.

Deliberately process-wide, not per-connection: there is exactly one
physical microphone (the Pi's), so one detector feeding N listeners is the
right shape, not one detector per browser tab.

Fails soft end-to-end: a missing optional dependency, missing/busy
microphone, or model load error logs a warning and leaves the rest of the
backend fully working — start() below never raises.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
import time

from fastapi import WebSocket

from app.config import get_settings

logger = logging.getLogger(__name__)

_listeners: set[WebSocket] = set()
_task: asyncio.Task | None = None

# Pause/resume coordination — there is exactly one physical microphone, and
# a real voice-command recording (manual tap OR a "Hey XP" detection
# opening the assistant) needs exclusive use of it. Without this, the
# detector's own continuous sd.RawInputStream fights the browser's
# getUserMedia() for the same hardware device, which on this Pi's audio
# stack doesn't share cleanly — confirmed 2026-09-16: with the detector
# running, manual voice commands stopped transcribing entirely, not just
# wake-word detection misbehaving. pause()/resume() are called over HTTP
# (POST /v1/wake-word/pause, /resume — see app/routers/wake_word.py) right
# as the FRONTEND opens/closes its own mic stream (before any audio is
# captured, not after — by the time a finished recording reaches
# /voice/command the contention already happened), so the detector steps
# aside for exactly as long as a real recording is in progress.
_pause_requested = asyncio.Event()
_resumed = asyncio.Event()
_currently_paused = asyncio.Event()

# openWakeWord's own documented input contract: 16kHz mono 16-bit PCM,
# fed in 80ms frames (1280 samples) — matches its examples/detect_from_microphone.py.
_SAMPLE_RATE = 16_000
_CHUNK_SAMPLES = 1280

# Pretrained, no-setup-required stand-in for "Hey XP" (see
# wake_word_model_path) — used only if that custom model file is ever
# missing (a fresh checkout without it, a bad path, etc.), so the detection
# -> WebSocket push -> frontend-opens path degrades gracefully instead of
# silently doing nothing.
_FALLBACK_STOCK_KEYWORD = "hey_jarvis"

# A detection re-fires on every 80ms frame that stays above threshold while
# the wake phrase is still being spoken — without this, one utterance of
# "Hey XP" would open/re-open the assistant several times in a row.
_COOLDOWN_SEC = 3.0


def register(ws: WebSocket) -> None:
    _listeners.add(ws)


def unregister(ws: WebSocket) -> None:
    _listeners.discard(ws)


async def _broadcast(label: str, score: float) -> None:
    dead: list[WebSocket] = []
    for ws in list(_listeners):
        try:
            await ws.send_json({"type": "wake", "label": label, "score": score})
        except Exception:
            dead.append(ws)
    for ws in dead:
        _listeners.discard(ws)


async def start() -> None:
    """Call once from the app lifespan. No-op (never raises) if disabled or
    dependencies/mic aren't available on this machine."""
    global _task
    settings = get_settings()
    if not settings.wake_word_enabled:
        logger.info("Wake word detection disabled (WAKE_WORD_ENABLED=false)")
        return
    try:
        import openwakeword  # noqa: F401
        import sounddevice  # noqa: F401
    except ImportError:
        logger.warning(
            "WAKE_WORD_ENABLED=true but openwakeword/sounddevice aren't "
            "installed — run `pip install -e \".[wake-word]\"` on the "
            "machine with the microphone. Wake word stays off; nothing "
            "else is affected."
        )
        return

    _task = asyncio.create_task(_run(settings))


async def stop() -> None:
    """
    Cancel the detector task AND wait for it to actually finish before
    returning. Without the wait, cancel() only *schedules* the
    cancellation — the mic device isn't released until the task's `with
    stream:` block actually unwinds, which happens on a later event-loop
    iteration, not synchronously here. A restart that doesn't wait for that
    can tear down this process (SIGTERM/SIGKILL) before the old task ever
    releases the microphone, leaving the NEW process's own attempt to open
    it fail with "failed to open microphone" — confirmed 2026-09-16: a
    fast `systemctl restart` reliably reproduced this, one restart after
    another that worked fine.
    """
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await asyncio.wait_for(_task, timeout=3.0)
        except (asyncio.CancelledError, TimeoutError):
            pass
        _task = None
        _pause_requested.clear()
        _resumed.clear()
        _currently_paused.clear()


async def pause() -> None:
    """
    Release the microphone RIGHT NOW — call this before opening any real
    voice-command recording elsewhere on this machine, and always pair it
    with resume() once that recording ends. A no-op when the detector
    isn't running at all (wake word disabled, or failed to start), so
    callers can invoke this unconditionally without checking first.

    Waits for the release to actually complete (same "don't just request
    it, wait for it" reasoning as stop()) so the caller's own mic open
    can't race the detector's release.
    """
    if _task is None or _task.done():
        return
    _currently_paused.clear()
    _pause_requested.set()
    try:
        await asyncio.wait_for(_currently_paused.wait(), timeout=2.0)
    except TimeoutError:
        logger.warning("Wake word: pause() timed out waiting for mic release")


async def resume() -> None:
    """Let the detector reacquire the microphone once a recording is done.
    A no-op when the detector isn't running — see pause()."""
    if _task is None or _task.done():
        return
    _resumed.set()


async def _run(settings) -> None:
    import openwakeword

    model_path = pathlib.Path(settings.wake_word_model_path)
    if model_path.exists():
        keyword_arg = str(model_path)
        logger.info("Wake word: loading custom model %s", model_path)
    else:
        keyword_arg = _FALLBACK_STOCK_KEYWORD
        logger.warning(
            "Wake word: no 'Hey XP' model at %s — using the stock '%s' "
            "keyword as a stand-in (say 'Hey Jarvis' to test). Check that "
            "backend/models/hey_xp.onnx was synced to this machine, then "
            "restart the backend.",
            model_path, _FALLBACK_STOCK_KEYWORD,
        )

    try:
        # One-time (per machine) download of the small pretrained feature-
        # extraction models plus the stock keyword above — cached locally
        # afterward, so this is a no-op (and needs no internet) on every
        # run after the first. Custom models at wake_word_model_path are
        # loaded straight from disk and never go through this.
        openwakeword.utils.download_models()
    except Exception:
        logger.warning(
            "Wake word: couldn't fetch pretrained models (offline?) — will "
            "still work if they're already cached from a previous run.",
        )

    try:
        from openwakeword.model import Model
        model = Model(wakeword_models=[keyword_arg], inference_framework="onnx")
    except Exception:
        logger.exception("Wake word: failed to load model — disabled for this run")
        return

    try:
        while True:
            opened = await _listen_until_paused(model, keyword_arg, settings)
            if not opened:
                # Mic open failed (busy/unavailable) — brief backoff before
                # retrying rather than busy-looping on a device that isn't
                # free yet.
                await asyncio.sleep(2.0)
                continue

            # _listen_until_paused only returns True after voluntarily
            # releasing the mic because pause() was called — signal that
            # it's actually free now, then wait for resume() before
            # reopening it.
            _currently_paused.set()
            logger.info("Wake word: paused (microphone released for a voice command)")
            await _resumed.wait()
            _pause_requested.clear()
            _resumed.clear()
            _currently_paused.clear()
            # resume() fires the instant the BROWSER's mr.onstop handler
            # runs — which is when it ASKS the OS to release the mic, not
            # necessarily when the OS has actually finished doing so.
            # Reopening immediately raced that release and failed with
            # "failed to open microphone" (confirmed 2026-09-16), which the
            # retry-with-backoff below did recover from, but only after a
            # ~9s gap where "Hey XP" genuinely didn't work. A short grace
            # period here is cheap — nobody is going to say the wake word
            # in the same instant a command they just gave finishes — and
            # avoids hitting that race at all in the common case.
            await asyncio.sleep(0.5)
            logger.info("Wake word: resuming")
    except asyncio.CancelledError:
        logger.info("Wake word: stopped")
        raise


async def _listen_until_paused(model, keyword_arg: str, settings) -> bool:
    """
    Opens the microphone and listens for the wake word until pause() sets
    _pause_requested, then releases it and returns. Returns False (instead
    of raising) if the microphone couldn't be opened at all, so the outer
    loop can back off and retry rather than crash the whole detector.
    """
    import numpy as np
    import sounddevice as sd

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=8)

    def _on_audio(indata, _frames, _time_info, status) -> None:
        if status:
            logger.debug("Wake word mic status: %s", status)
        try:
            loop.call_soon_threadsafe(queue.put_nowait, bytes(indata))
        except (asyncio.QueueFull, RuntimeError):
            pass  # drop a frame rather than build up latency

    # This specific Pi's audio hardware doesn't release a just-closed device
    # instantly or consistently — confirmed 2026-09-16: reopening after a
    # resume() succeeded on the first try once, but needed two failed
    # attempts (~5-6s total) another time. A single fixed delay can't be
    # tuned to cover both cases, so retry quickly and repeatedly instead —
    # cheap, and converges faster than one long guessed wait whenever the
    # device happens to free up sooner.
    stream = None
    last_exc: Exception | None = None
    for attempt in range(8):
        try:
            stream = sd.RawInputStream(
                samplerate=_SAMPLE_RATE,
                blocksize=_CHUNK_SAMPLES,
                dtype="int16",
                channels=1,
                callback=_on_audio,
            )
            break
        except Exception as exc:
            last_exc = exc
            await asyncio.sleep(0.4)
    if stream is None:
        logger.warning("Wake word: failed to open microphone after retrying: %s", last_exc)
        return False

    cooldown_until = 0.0
    # TEMPORARY diagnostic (remove once "Hey XP" reliability is confirmed):
    # tests whether a REOPENED stream (after any pause/resume) is actually
    # receiving real audio at all, independent of what the wake-word model
    # makes of it — a silently degraded/near-silent stream after reopening
    # would explain "detected once cleanly on the very first listen, never
    # again after that" without the model itself being at fault.
    last_level_log = time.monotonic()
    rolling_max_abs = 0
    with stream:
        logger.info(
            "Wake word: listening (keyword=%s, threshold=%s)",
            keyword_arg, settings.wake_word_threshold,
        )
        while not _pause_requested.is_set():
            chunk = await queue.get()
            pcm = np.frombuffer(chunk, dtype=np.int16)
            rolling_max_abs = max(rolling_max_abs, int(np.abs(pcm).max()))
            now_ = time.monotonic()
            if now_ - last_level_log >= 2.0:
                logger.info("Wake word: raw mic level (max abs sample) = %d", rolling_max_abs)
                rolling_max_abs = 0
                last_level_log = now_
            model.predict(pcm)
            # Exactly one model is loaded, so there's exactly one key —
            # read it by position rather than hardcoding a name, since
            # openWakeWord keys prediction_buffer by the model's full
            # versioned filename (e.g. "hey_jarvis_v0.1"), not the bare
            # keyword string passed into the constructor.
            label, scores = next(iter(model.prediction_buffer.items()))
            score = float(scores[-1])
            now = time.monotonic()
            # TEMPORARY diagnostic (remove once "Hey XP" accuracy is
            # confirmed): the only other logging here fires on a confirmed
            # detection, so a non-firing wake word gives zero visibility
            # into WHY — near-threshold-but-missing (real accuracy issue)
            # looks identical in the logs to structurally-broken (near-zero
            # always) without this.
            if score > 0.1:
                logger.info(
                    "Wake word: score=%.3f (threshold=%.2f)",
                    score, settings.wake_word_threshold,
                )
            if score >= settings.wake_word_threshold and now >= cooldown_until:
                logger.info("Wake word detected: %s (score=%.2f)", label, score)
                cooldown_until = now + _COOLDOWN_SEC
                await _broadcast(label, score)
    # `with stream` has released the mic by this point.
    return True
