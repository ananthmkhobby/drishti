"""Add practice_attempts.counter_question/student_explanation/
explanation_outcome — the "productive struggle" step before Gate G's hint

On a student's FIRST genuine mistake on a question, the system now asks a
targeted question about their own reasoning instead of immediately handing
them a hint, and waits for a spoken response before deciding what (if
anything) to say next. Implements the NBER field-experiment finding that
AI support is most effective when it intervenes with reflection prompts
after a mistake, not by immediately being more directive.

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("practice_attempts", sa.Column("counter_question", sa.Text(), nullable=True))
    op.add_column("practice_attempts", sa.Column("student_explanation", sa.Text(), nullable=True))
    op.add_column("practice_attempts", sa.Column("explanation_outcome", sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("practice_attempts", "explanation_outcome")
    op.drop_column("practice_attempts", "student_explanation")
    op.drop_column("practice_attempts", "counter_question")
