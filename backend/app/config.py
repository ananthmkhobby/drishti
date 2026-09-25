import uuid
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


def _normalise_db_url(url: str) -> str:
    """
    Map bare postgres:// / postgresql:// connection strings (as returned by
    Supabase, Railway, Render, Heroku, etc.) to the asyncpg driver URL that
    SQLAlchemy requires.  Also handles the sqlite+aiosqlite dev case.
    """
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "Drishti Backend"
    environment: str = "development"
    debug: bool = False
    api_prefix: str = "/v1"

    # CORS — comma-separated list of allowed origins for production.
    # Defaults to "*" in development; set explicitly in staging/prod.
    # Example: ALLOWED_ORIGINS=https://app.example.com,https://www.example.com
    allowed_origins: str = ""

    # Database — supports postgres://, postgresql://, postgresql+asyncpg://, sqlite+aiosqlite://
    database_url: str = "postgresql+asyncpg://aci:aci@localhost:5432/aci"

    @field_validator("database_url", mode="before")
    @classmethod
    def normalise_database_url(cls, v: str) -> str:
        return _normalise_db_url(v)

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_secret_key: str = "change-me-before-production"
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 1440

    # Auth
    skip_auth: bool = False
    dev_teacher_id: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")

    # Storage
    use_s3: bool = False
    upload_dir: str = "./uploads"
    max_frame_size_mb: int = 10
    max_frames_per_session: int = 200

    # AWS S3
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "ap-south-1"
    s3_bucket: str = "aci-uploads"

    # Celery
    celery_always_eager: bool = False

    # OpenAI — set OPENAI_API_KEY in .env to enable real AI generation.
    # When empty the service falls back to placeholder outputs.
    openai_api_key: str = ""
    openai_model_default: str = "gpt-4o"
    openai_model_mini: str = "gpt-4o-mini"
    # Per-call retry / timeout
    ai_max_retries: int = 3
    ai_request_timeout_sec: int = 60
    # OCR text fed to AI is truncated to this many estimated tokens (chars / 4)
    ai_max_ocr_tokens: int = 4000
    # Whisper language hint (ISO-639-1, e.g. "en", "hi", "ta"). Empty = auto-detect.
    # Auto-detect misreads Indian-accented English as Hindi and transcribes it in
    # Devanagari, so classrooms teaching in English should set WHISPER_LANGUAGE=en.
    whisper_language: str = ""

    # Sessions idle (active status) for longer than this are auto-completed on startup
    session_timeout_hours: int = 4

    # Voice assistant — local intent parsing via Ollama, OpenAI as fallback.
    # Only used for turning a transcribed voice command into a structured
    # action (e.g. "create a new session" -> {"intent": "create_session"}).
    # OCR/vision is unaffected by this and always uses OpenAI vision first.
    ollama_base_url: str = "http://localhost:11434"
    # Separate from the intent model — decoupled so a bigger/better model can
    # be swapped in for open-ended Q&A later without touching intent parsing.
    ollama_brain_model: str = "qwen2.5:3b"
    # 0.5b is fast but unreliable for this (misclassified "start a physics
    # class" as "start recording", and a nonsense query as a real intent
    # instead of "unknown" — 6/8 on a basic accuracy test). 3b scored 8/8 in
    # the same test; a few extra seconds of latency is worth getting the
    # right action.
    ollama_intent_model: str = "qwen2.5:3b"
    voice_intent_timeout_sec: int = 15
    # Local Qwen needs real prefill throughput to be worth it — the system
    # prompt (with all its few-shot examples) is ~2.7k tokens, which a Mac
    # processes in ~1-2s but a Raspberry Pi's CPU-only inference can't
    # finish inside voice_intent_timeout_sec at all, so every call there
    # silently eats the full timeout before falling back to cloud anyway.
    # Set false on hardware too slow for this (measure with a direct
    # `time curl .../api/generate` call before assuming) to skip straight
    # to cloud — OCR/generation/STT/TTS already require internet regardless,
    # so this doesn't meaningfully change the app's real offline capability.
    local_llm_enabled: bool = True

    # ThinkStep guided-practice Gates E-H (solution-path validation,
    # misconception classification, hint generation, answer-leakage guard)
    # are a harder reasoning task than intent classification or Q&A — a
    # controlled test (12 real attempts across calculus/physics/chemistry,
    # 2026-09-10) found qwen2.5:3b produced 3/3 false "you have a
    # misconception" accusations on fully correct work, each of which came
    # back correct when the SAME input was re-run against gpt-4o. The PRD's
    # own accuracy bar treats a false accusation as far worse than a missed
    # one, so this defaults to cloud-only unless proven otherwise on
    # specific hardware — flip to true only after re-running that same kind
    # of test against the model actually deployed.
    practice_local_llm_enabled: bool = False

    # Local Whisper (whisper.cpp's whisper-server, kept warm as its own
    # process — same "don't pay model-load cost per request" fix as
    # local_llm_enabled/Ollama's keep-alive) for the VOICE COMMAND path
    # only (/voice/transcribe, /voice/command). Measured on a Mac: ~40ms
    # per short command with a warm server vs 5-8s round-tripping to
    # OpenAI's Whisper API from a Pi. Falls back to the OpenAI path
    # automatically if the local server is unreachable.
    #
    # Deliberately NOT used for the long-form lecture-recording pipeline
    # (POST /sessions/{id}/audio in audio.py) — that path leans on
    # OpenAI's per-segment no_speech_prob/avg_logprob confidence scores
    # for hallucination filtering, which whisper.cpp's basic /inference
    # response doesn't provide. Short, deliberate command utterances
    # don't need that same guard; long recordings still do.
    local_whisper_enabled: bool = True
    local_whisper_url: str = "http://localhost:8080"

    # Wake word ("Hey XP") — on-device detection via openWakeWord
    # (ONNX, CPU-only), running as a background task in THIS backend
    # process against its own microphone; detections push to any connected
    # frontend over WebSocket (see app/services/wake_word_service.py,
    # app/routers/wake_word.py). Replaced two earlier approaches: Chrome's
    # SpeechRecognition (not actually local — streams to Google's speech
    # service, the real source of a multi-second detection delay) and then
    # Picovoice Porcupine (free tier gated custom keyword training behind
    # an account + review queue, 2026-09-11). openWakeWord needs neither —
    # it's free/open-source and a custom model is trained locally via its
    # own notebook.
    #
    # Off by default: only makes sense on the machine with the actual mic
    # attached (the Pi, not necessarily a dev laptop) and needs the
    # optional dependency group installed (`pip install -e ".[wake-word]"`).
    # Fails soft either way — missing deps/mic/model just log a warning and
    # leave the rest of the backend unaffected, same as local_llm_enabled/
    # local_whisper_enabled falling back to their cloud paths above.
    wake_word_enabled: bool = False
    # Path to the custom-trained "Hey XP" openWakeWord model (.onnx),
    # trained via openWakeWord's own notebook and committed at this path
    # (small classifier-head file, same as the bundled face/emotion ONNX
    # models already in this directory). Until a file exists at this path,
    # wake_word_service falls back to a pretrained stock keyword ("hey
    # jarvis") so the detection -> push -> frontend-opens pipeline stays
    # testable even without it.
    wake_word_model_path: str = "./models/hey_xp.onnx"
    # Detection confidence (0-1) — openWakeWord's own suggested default.
    wake_word_threshold: float = 0.5

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def is_test(self) -> bool:
        return self.environment == "test"

    @property
    def cors_origins(self) -> list[str]:
        """Parsed list of allowed CORS origins."""
        if self.allowed_origins:
            return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]
        if self.is_development:
            return ["*"]
        return []  # deny all in production unless ALLOWED_ORIGINS is set


def get_settings() -> Settings:
    return Settings()
