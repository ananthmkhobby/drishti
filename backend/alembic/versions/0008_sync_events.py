"""sync_events table for Phase 2 offline event polling

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007_multi_audio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_sync_events_session_id", "sync_events", ["session_id"])
    op.create_index("ix_sync_events_created_at", "sync_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_sync_events_created_at", "sync_events")
    op.drop_index("ix_sync_events_session_id", "sync_events")
    op.drop_table("sync_events")
