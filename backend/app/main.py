import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.exceptions import ACIError, aci_error_handler, generic_exception_handler, validation_error_handler
from app.routers import (
    absorption,
    audience_metrics,
    audio,
    cross_session,
    dashboard,
    frames,
    health,
    jobs,
    lesson_plans,
    outputs,
    practice,
    sessions,
    sync,
    textbooks,
    translate,
    video,
    voice,
    wake_word,
)
from app.services import wake_word_service

# Without this, the root logger defaults to WARNING and every logger.info(...)
# call across the app (OCR pipeline, audience analysis, etc.) is silently
# dropped — only warnings/errors reach the console/journal.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

logger = logging.getLogger(__name__)


async def _auto_complete_stale_sessions() -> None:
    """
    On startup: mark any session that has been 'active' for longer than
    session_timeout_hours as 'completed'.  This handles teachers who left
    a session running overnight or walked away mid-class.
    """
    from sqlalchemy import update as sa_update

    from app.database import _get_session_factory
    from app.models.session import Session

    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.session_timeout_hours)
    factory = _get_session_factory()
    async with factory() as db:
        try:
            result = await db.execute(
                sa_update(Session)
                .where(Session.status == "active")
                .where(Session.created_at < cutoff)
                .values(status="completed", completed_at=datetime.now(timezone.utc))
            )
            count = result.rowcount
            if count:
                logger.info(
                    "Auto-completed %d stale session(s) (active > %dh)",
                    count, settings.session_timeout_hours,
                )
            await db.commit()
        except Exception as exc:
            logger.warning("Stale session cleanup failed (non-fatal): %s", exc)


async def _recover_stuck_processing() -> None:
    """
    On startup: re-queue any Frame.ocr_status or PracticeAttempt.status left
    at 'processing'.

    Both OCR and ThinkStep attempts run via FastAPI's BackgroundTasks —
    in-process, no persistence. A backend restart (a redeploy, a config
    change, anything that runs `systemctl restart aci-backend`) kills
    whatever task was mid-flight with no way for it to ever mark itself
    done/failed, leaving that frame or attempt stuck at "processing"
    forever with nothing left to finish it (confirmed 2026-09-15: several
    redeploys in one session each happened to land mid-OCR, and the
    frontend was left showing an indefinite "Scanning…" for the orphaned
    frame). Nothing can legitimately still be "processing" from a PREVIOUS
    process at the moment this NEW process starts, so every such row here
    is unconditionally re-queued — no time threshold needed, unlike
    _auto_complete_stale_sessions above (which has to distinguish a
    genuinely still-active session from an abandoned one).
    """
    from sqlalchemy import select as sa_select

    from app.database import _get_session_factory
    from app.models.frame import Frame
    from app.models.practice_attempt import PracticeAttempt

    factory = _get_session_factory()
    async with factory() as db:
        try:
            stuck_frame_ids = (
                await db.execute(sa_select(Frame.id).where(Frame.ocr_status == "processing"))
            ).scalars().all()
            stuck_attempt_ids = (
                await db.execute(
                    sa_select(PracticeAttempt.id).where(PracticeAttempt.status == "processing")
                )
            ).scalars().all()
        except Exception as exc:
            logger.warning("Stuck-processing recovery scan failed (non-fatal): %s", exc)
            return

    if stuck_frame_ids:
        logger.info(
            "Recovering %d frame(s) stuck at ocr_status='processing' from a prior process",
            len(stuck_frame_ids),
        )
        from app.routers.frames import _run_ocr_background
        for frame_id in stuck_frame_ids:
            asyncio.create_task(_run_ocr_background(frame_id))

    if stuck_attempt_ids:
        logger.info(
            "Recovering %d practice attempt(s) stuck at status='processing' from a prior process",
            len(stuck_attempt_ids),
        )
        from app.routers.practice import _run_attempt_background
        for attempt_id in stuck_attempt_ids:
            asyncio.create_task(_run_attempt_background(attempt_id))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    import pathlib
    pathlib.Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    await _auto_complete_stale_sessions()
    await _recover_stuck_processing()
    await wake_word_service.start()
    yield
    await wake_word_service.stop()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Drishti Backend",
        description="Drishti – Offline-First Classroom Intelligence Platform",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(ACIError, aci_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    prefix = settings.api_prefix

    app.include_router(health.router)
    app.include_router(sessions.router, prefix=prefix)
    app.include_router(frames.router, prefix=prefix)
    app.include_router(outputs.router, prefix=prefix)
    app.include_router(sync.router, prefix=prefix)
    app.include_router(dashboard.router, prefix=prefix)
    app.include_router(jobs.router, prefix=prefix)
    app.include_router(lesson_plans.router, prefix=prefix)
    app.include_router(audio.router, prefix=prefix)
    app.include_router(video.router, prefix=prefix)
    app.include_router(audience_metrics.router, prefix=prefix)
    app.include_router(translate.router, prefix=prefix)
    app.include_router(absorption.router, prefix=prefix)
    app.include_router(voice.router, prefix=prefix)
    app.include_router(cross_session.router, prefix=prefix)
    app.include_router(practice.router, prefix=prefix)
    app.include_router(wake_word.router, prefix=prefix)
    app.include_router(textbooks.router, prefix=prefix)

    return app


app = create_app()
