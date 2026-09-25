"""audience_metrics table for Phase 2 face analysis

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audience_metrics",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("minute_number", sa.Integer(), nullable=False),
        sa.Column("faces_detected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attention_pct", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("hand_raises", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audience_metrics_session_minute", "audience_metrics", ["session_id", "minute_number"])


def downgrade() -> None:
    op.drop_index("ix_audience_metrics_session_minute", table_name="audience_metrics")
    op.drop_table("audience_metrics")
