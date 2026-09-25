"""
One-off diagnostic — NOT part of the app. Measures how long the local
whisper-server (whisper.cpp) call actually takes on THIS machine for a
short, realistic voice-command-length clip, using the exact function the
deployed app calls (whisper_service.transcribe_local). Companion to
measure_voice_intent_latency.py — config.py's own comment on
local_whisper_enabled already documents one real case (2026-09-17) of this
timing out past 10s on this Pi's CPU-only hardware; this re-measures it
directly rather than guessing.

Generates a short synthetic WAV (a few seconds of a spoken-length tone) —
timing is what matters here, not transcript accuracy, since whisper.cpp's
processing time scales with audio duration regardless of content.

Usage (run on the machine actually running the backend, e.g. the Pi):
  .venv/bin/python scripts/measure_local_whisper_latency.py
"""
import asyncio
import io
import struct
import time
import wave


def _make_test_wav(seconds: float = 3.0, sample_rate: int = 16000) -> bytes:
    n_samples = int(seconds * sample_rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        # A quiet 220Hz tone, not silence — some local ASR servers treat
        # true silence as a fast-path/no-op, which wouldn't measure real
        # inference cost the way actual speech audio would.
        import math
        frames = bytearray()
        for i in range(n_samples):
            val = int(3000 * math.sin(2 * math.pi * 220 * i / sample_rate))
            frames += struct.pack("<h", val)
        w.writeframes(bytes(frames))
    return buf.getvalue()


async def main():
    from app.config import get_settings
    from app.services.whisper_service import transcribe_local

    settings = get_settings()
    print(f"local_whisper_enabled={settings.local_whisper_enabled}  local_whisper_url={settings.local_whisper_url}")
    print()

    for seconds in (2.0, 4.0, 6.0):
        wav_bytes = _make_test_wav(seconds)
        t0 = time.monotonic()
        result = await transcribe_local(wav_bytes, "test.wav", settings.local_whisper_url, "en")
        elapsed = time.monotonic() - t0
        status = "OK" if result is not None else "FAILED/UNREACHABLE (fell back to cloud in production)"
        print(f"[{elapsed:5.2f}s] {seconds:.0f}s clip  {status}")

    print()
    print("A real spoken command is usually 2-6s — if these times are")
    print("multiple seconds each (or failing), local whisper is a real cost")
    print("on this hardware. Set LOCAL_WHISPER_ENABLED=false in .env and")
    print("restart aci-backend to skip straight to cloud Whisper instead.")


if __name__ == "__main__":
    asyncio.run(main())
