"""Add misconceptions — curated, versioned library the grader picks codes from

Replaces per-question, LLM-invented free-form misconception codes with a
controlled vocabulary (subject, grade range, topic, typical student work,
source, review status) so the same real misconception gets one stable code
and can be aggregated, checked and teacher-reviewed.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "misconceptions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("subject_key", sa.String(20), nullable=False),
        sa.Column("grade_min", sa.Integer(), nullable=False),
        sa.Column("grade_max", sa.Integer(), nullable=False),
        sa.Column("topic", sa.String(80), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("typical_work", sa.Text(), nullable=False),
        sa.Column("source_citation", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(12), nullable=False, server_default="research"),
        sa.Column("review_status", sa.String(20), nullable=False, server_default="unreviewed"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_misconceptions_code", "misconceptions", ["code"], unique=True)
    op.create_index("ix_misconceptions_subject_key", "misconceptions", ["subject_key"])


def downgrade() -> None:
    op.drop_index("ix_misconceptions_subject_key", table_name="misconceptions")
    op.drop_index("ix_misconceptions_code", table_name="misconceptions")
    op.drop_table("misconceptions")
