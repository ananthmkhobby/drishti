"""Add practice_radar_alerts — cross-desk misconception alerts

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

_JsonType = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "practice_radar_alerts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", sa.Uuid(), sa.ForeignKey("practice_questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(60), nullable=False),
        sa.Column("desk_ids", _JsonType, nullable=False),
        sa.Column("desk_count", sa.Integer(), nullable=False),
        sa.Column("attempting_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="new"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("session_id", "question_id", "code", name="uq_radar_session_question_code"),
    )
    op.create_index("ix_practice_radar_alerts_session_id", "practice_radar_alerts", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_practice_radar_alerts_session_id", table_name="practice_radar_alerts")
    op.drop_table("practice_radar_alerts")
