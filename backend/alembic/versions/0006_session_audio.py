"""Add session_audios table

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-12
"""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "session_audios",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("file_type", sa.String(20), nullable=False, server_default="webm"),
        sa.Column("duration_sec", sa.Float(), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("segments", sa.JSON(), nullable=True),
        sa.Column("whisper_language", sa.String(10), nullable=True),
        sa.Column("whisper_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        # Named explicitly (not the column-level `unique=True` shorthand) so
        # migration 0007 can drop it by an exact, deterministic name later —
        # an inline `unique=True` gets an auto-generated name that Postgres
        # and SQLite don't agree on, which 0007's drop_constraint relied on
        # matching. Confirmed live 2026-09-21: this migration chain had only
        # ever been run against SQLite (where batch_alter_table sidesteps
        # needing the real name) until this fix — 0007 failed outright
        # against real Postgres with "constraint ... does not exist".
        sa.UniqueConstraint("session_id", name="uq_session_audios_session_id"),
    )
    op.create_index("idx_session_audios_session", "session_audios", ["session_id"])


def downgrade() -> None:
    op.drop_table("session_audios")
