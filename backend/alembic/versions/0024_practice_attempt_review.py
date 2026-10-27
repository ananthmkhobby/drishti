"""Add practice_attempts.review — on-demand "conceptual error / perfect
answer / tip" correction panel

Generated lazily (not on every attempt) the first time a student/teacher
opens the full correction view, then cached here so re-opening it doesn't
re-call the LLM. Deliberately separate from hint_text (Gates G/H), which
is guard-railed to never reveal the final answer while a student is still
actively working — this is the opposite intent, shown only for a finished
attempt review.

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

_JsonType = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.add_column(
        "practice_attempts",
        sa.Column("review", _JsonType, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("practice_attempts", "review")
