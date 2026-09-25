"""
Celery task stubs.

These tasks will contain real OCR and AI logic in Phase 2.
Currently the routes use FastAPI BackgroundTasks with the placeholder
services instead of dispatching to Celery — this file is wired and ready.

To switch to Celery:
1. Start Redis: docker compose up -d redis
2. Start worker: make worker
3. In routers, replace `background_tasks.add_task(...)` with `task.delay(...)`
"""
import uuid
import asyncio
from app.workers.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def process_ocr_task(self, frame_id: str, image_path: str):
    """
    Phase 2: run PaddleOCR + Tesseract on the given frame.
    See /skills/ocr_skill.md for the full algorithm.
    """
    try:
        # Placeholder — real implementation: call PaddleOCR, update DB
        asyncio.run(_placeholder_ocr_async(uuid.UUID(frame_id)))
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def process_ai_generation_task(self, session_id: str, output_types: list[str], job_id: str):
    """
    Phase 2: call OpenAI API for each requested output type.
    See /skills/ai_generation_skill.md for the full algorithm.
    """
    try:
        asyncio.run(
            _placeholder_ai_async(
                uuid.UUID(session_id), output_types, uuid.UUID(job_id)
            )
        )
    except Exception as exc:
        raise self.retry(exc=exc)


async def _placeholder_ocr_async(frame_id: uuid.UUID):
    from app.database import _get_session_factory
    from app.services.ocr_service import run_placeholder_ocr
    factory = _get_session_factory()
    async with factory() as db:
        await run_placeholder_ocr(frame_id, db)


async def _placeholder_ai_async(
    session_id: uuid.UUID, output_types: list[str], job_id: uuid.UUID
):
    from app.database import _get_session_factory
    from app.services.ai_service import run_placeholder_generation
    factory = _get_session_factory()
    async with factory() as db:
        await run_placeholder_generation(session_id, output_types, job_id, db)
