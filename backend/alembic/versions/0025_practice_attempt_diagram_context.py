"""Add practice_attempts.diagram_context — a factual description of the
question's own labeled figure (circuit, geometric diagram, graph, ...),
read off the photo alongside recognized_steps

validate_step only ever sees transcribed text, never the photo itself, so
a diagram's own labeled values were invisible to grading whenever the
question's own text/metadata didn't happen to restate them. Confirmed live
(2026-09-30 eval): with sparse question metadata, grading correctly caught
a wrong final answer but lost the ability to say WHY once nothing in its
context mentioned the diagram value actually being ignored.

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "practice_attempts",
        sa.Column("diagram_context", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("practice_attempts", "diagram_context")
