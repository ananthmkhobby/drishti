import uuid
from fastapi import APIRouter

from app.dependencies import CurrentTeacher, DB
from app.exceptions import ACIError
from app.models.job import Job
from app.schemas.ai_output import JobResponse

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: uuid.UUID, db: DB, _: CurrentTeacher):
    job = await db.get(Job, job_id)
    if not job:
        raise ACIError("JOB_NOT_FOUND", f"No job found with ID {job_id}", 404)
    return JobResponse.from_orm(job)
