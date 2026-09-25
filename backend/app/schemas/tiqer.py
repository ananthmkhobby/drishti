"""
TiQer-compatible question export schemas.

These are the external-facing shapes that TiQer (or any downstream consumer)
expects to receive.  Keep them stable — changes here are a breaking API change.

Schema version: 1.0
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ── Per-option inside an MCQ ──────────────────────────────────────────────────

class TiQerOption(BaseModel):
    """Single answer option for an MCQ question."""
    key: Literal["A", "B", "C", "D"]
    text: str


# ── Individual question ───────────────────────────────────────────────────────

class TiQerQuestion(BaseModel):
    """
    Canonical TiQer question format.

    Rules:
    - MCQ: options = list[TiQerOption]; correct_answer = "A" | "B" | "C" | "D"
    - T/F: options = None;              correct_answer = "true" | "false"
    - difficulty is derived from bloom_level (not stored separately in DB)
    """

    question_id: str = Field(description="ACI question UUID — stable across re-exports")
    sequence: int = Field(description="1-based display order in the question set")
    type: Literal["mcq", "true_false"]
    text: str

    # MCQ: lettered options. null for true_false.
    options: list[TiQerOption] | None = None

    # MCQ: "A"-"D". T/F: "true" or "false"
    correct_answer: str

    bloom_level: str = Field(description="Bloom taxonomy level")
    skill_tag: str = Field(description="Skill identifier for learning analytics")
    topic: str = Field(description="Topic or concept the question tests")
    grade: str
    subject: str
    difficulty: Literal["easy", "medium", "hard"] = Field(
        description="Derived from bloom_level: remember/understand→easy, apply/analyze→medium, evaluate/create→hard"
    )


# ── Metadata block inside the export envelope ─────────────────────────────────

class TiQerExportMetadata(BaseModel):
    generated_by: str = "ACI – AI Chalkboard Intelligence"
    aci_version: str = "1.0.0"
    bloom_distribution: dict[str, int] = Field(
        description="Question count per Bloom level"
    )
    mcq_count: int
    true_false_count: int


# ── Full export envelope ──────────────────────────────────────────────────────

class TiQerExportPayload(BaseModel):
    """
    Complete TiQer export envelope.  This is the JSON structure written to the
    export log and returned to the client on download.
    """
    export_id: str = Field(description="Unique ID for this export run")
    schema_version: str = "1.0"
    tiqer_class_id: str
    session_id: str
    exported_at: datetime
    teacher_id: str
    subject: str
    grade: str
    question_count: int
    questions: list[TiQerQuestion]
    metadata: TiQerExportMetadata

    # datetime fields are serialised as ISO-8601 strings by Pydantic v2 by default


# ── API response ──────────────────────────────────────────────────────────────

class TiQerExportAPIResponse(BaseModel):
    """Response body for POST .../export-tiqer."""
    tiqer_session_id: str
    status: str
    question_count: int
    exported_at: datetime
    payload: TiQerExportPayload
