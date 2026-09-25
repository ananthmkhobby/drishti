"""Catch up migration history with models — voice_events table, session_audios.source,
sessions.instructor_name/board_roi/deleted_at

Confirmed live 2026-09-21, verifying this project's first-ever real run of
`alembic upgrade head` against Postgres (every prior deploy only ever used
scripts/create_db.py's create_all() against SQLite): several model changes
made it into create_db.py's auto-add-missing-columns path over time without
a matching Alembic migration ever being written, so the migration history
silently fell behind the models. Found by diffing live Postgres schema
against Base.metadata after a from-scratch `alembic upgrade head` — this is
everything that diff turned up.

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

_JsonType = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "voice_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("teacher_id", sa.Uuid(), sa.ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False, server_default=""),
        sa.Column("intent", sa.String(50), nullable=False, server_default="unknown"),
        sa.Column("params", _JsonType, nullable=True),
        sa.Column("intent_source", sa.String(20), nullable=False, server_default="none"),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("answer_source", sa.String(20), nullable=True),
        sa.Column("needs_clarification", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("processing_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_voice_events_teacher_id", "voice_events", ["teacher_id"])
    op.create_index("ix_voice_events_created_at", "voice_events", ["created_at"])

    with op.batch_alter_table("session_audios") as batch_op:
        batch_op.add_column(sa.Column("source", sa.String(10), nullable=False, server_default="audio"))

    with op.batch_alter_table("sessions") as batch_op:
        batch_op.add_column(sa.Column("instructor_name", sa.String(200), nullable=True))
        batch_op.add_column(sa.Column("board_roi", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_sessions_deleted_at", "sessions", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_sessions_deleted_at", table_name="sessions")
    with op.batch_alter_table("sessions") as batch_op:
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("board_roi")
        batch_op.drop_column("instructor_name")

    with op.batch_alter_table("session_audios") as batch_op:
        batch_op.drop_column("source")

    op.drop_index("ix_voice_events_created_at", table_name="voice_events")
    op.drop_index("ix_voice_events_teacher_id", table_name="voice_events")
    op.drop_table("voice_events")
