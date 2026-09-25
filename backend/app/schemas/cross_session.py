import uuid
from pydantic import BaseModel, Field


class CrossSessionLinkRequest(BaseModel):
    session_ids: list[uuid.UUID] = Field(min_length=2, max_length=6)


class SessionSummaryEntry(BaseModel):
    session_id: uuid.UUID
    subject: str | None
    grade: str | None
    title: str | None
    instructor_name: str | None
    has_notes: bool


class ConceptConnection(BaseModel):
    concept_a: str
    concept_b: str
    shared_principle: str
    how_to_teach_it: str


class CrossSessionLinkResponse(BaseModel):
    sessions: list[SessionSummaryEntry]
    unifying_theme: str
    overall_summary: str
    connections: list[ConceptConnection]
    integrated_activity: str
