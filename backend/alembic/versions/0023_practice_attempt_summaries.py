"""Add practice_attempt_summaries — consolidated record of pruned attempt batches

Keeps the raw practice_attempts/images history bounded to the most recent
10 per question (see practice_service.prune_old_attempts_with_summary) by
summarizing and then deleting the rest, rather than accumulating an
unattended auto-capture station's full history forever.

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

_JsonType = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "practice_attempt_summaries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("question_id", sa.Uuid(), sa.ForeignKey("practice_questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("station_id", sa.Uuid(), sa.ForeignKey("practice_stations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("attempts_summarized", sa.Integer(), nullable=False),
        sa.Column("first_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("solved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revision_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("misconception_codes", _JsonType, nullable=True),
        sa.Column("hint_levels_seen", _JsonType, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_practice_attempt_summaries_question_id", "practice_attempt_summaries", ["question_id"])
    op.create_index("ix_practice_attempt_summaries_station_id", "practice_attempt_summaries", ["station_id"])


def downgrade() -> None:
    op.drop_index("ix_practice_attempt_summaries_station_id", table_name="practice_attempt_summaries")
    op.drop_index("ix_practice_attempt_summaries_question_id", table_name="practice_attempt_summaries")
    op.drop_table("practice_attempt_summaries")
