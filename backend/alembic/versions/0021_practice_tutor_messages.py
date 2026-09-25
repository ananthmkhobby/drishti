"""Add practice_tutor_messages — Guided Practice "Ask AI Tutor" conversation log

Append-only log of tutor/student turns (see PracticeTutorMessage docstring) —
built ahead of the revision-mode/report features that will read it, same
reasoning already used for TextbookChapter.taught_log.

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "practice_tutor_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("station_id", sa.Uuid(), sa.ForeignKey("practice_stations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", sa.Uuid(), sa.ForeignKey("practice_questions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("image_path", sa.String(500), nullable=True),
        sa.Column("had_image", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_practice_tutor_messages_station_id", "practice_tutor_messages", ["station_id"])
    op.create_index("ix_practice_tutor_messages_question_id", "practice_tutor_messages", ["question_id"])


def downgrade() -> None:
    op.drop_index("ix_practice_tutor_messages_question_id", table_name="practice_tutor_messages")
    op.drop_index("ix_practice_tutor_messages_station_id", table_name="practice_tutor_messages")
    op.drop_table("practice_tutor_messages")
