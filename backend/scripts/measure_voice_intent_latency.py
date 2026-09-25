"""
One-off diagnostic — NOT part of the app. Measures how long the real local
Ollama intent-classification call (voice_intent_service._classify_local)
actually takes on THIS machine, using the exact system prompt and model the
deployed app uses. config.py's own comment recommends measuring this
directly before assuming local_llm_enabled is worth it on a given machine
(a Raspberry Pi's CPU-only inference may not finish inside
voice_intent_timeout_sec at all, silently costing the full timeout on every
voice command before falling back to cloud anyway).

Usage (run on the machine actually running the backend, e.g. the Pi):
  .venv/bin/python scripts/measure_voice_intent_latency.py
"""
import asyncio
import time


async def main():
    from app.config import get_settings
    from app.services.voice_intent_service import _classify_local

    settings = get_settings()
    print(f"ollama_base_url={settings.ollama_base_url}  model={settings.ollama_intent_model}")
    print(f"voice_intent_timeout_sec={settings.voice_intent_timeout_sec}  local_llm_enabled={settings.local_llm_enabled}")
    print()

    samples = [
        "generate my notes for this session",
        "start recording",
        "what's the difference between mitosis and meiosis",
    ]

    for transcript in samples:
        t0 = time.monotonic()
        result = await _classify_local(
            transcript, settings.ollama_base_url, settings.ollama_intent_model,
            settings.voice_intent_timeout_sec,
        )
        elapsed = time.monotonic() - t0
        status = "OK" if result else "FAILED/TIMED OUT (fell back to cloud in production)"
        print(f"[{elapsed:5.2f}s] {status:45s} — \"{transcript}\" -> {result}")

    print()
    print("If these are consistently close to or over voice_intent_timeout_sec")
    print(f"({settings.voice_intent_timeout_sec}s), set LOCAL_LLM_ENABLED=false in .env and restart")
    print("aci-backend — cloud (gpt-4o-mini) will be faster on this hardware.")


if __name__ == "__main__":
    asyncio.run(main())
