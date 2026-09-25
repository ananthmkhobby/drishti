"""Add skill_tag to quiz_questions; add tiqer_export_log table

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-27

Changes:
  - quiz_questions.skill_tag  (nullable VARCHAR 255) — AI-generated skill identifier
  - tiqer_export_log          — audit trail for every TiQer export
"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # quiz_questions — add skill_tag column                               #
    # ------------------------------------------------------------------ #
    op.add_column(
        "quiz_questions",
        sa.Column("skill_tag", sa.String(255), nullable=True),
    )

    # ------------------------------------------------------------------ #
    # tiqer_export_log                                                    #
    # ------------------------------------------------------------------ #
    op.create_table(
        "tiqer_export_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("teacher_id", sa.Uuid(), nullable=False),
        sa.Column("tiqer_class_id", sa.String(255), nullable=False),
        sa.Column("tiqer_session_id", sa.String(255), nullable=False),
        sa.Column("question_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("schedule_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),  # full export payload
        sa.Column(
            "exported_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_tiqer_log_session", "tiqer_export_log", ["session_id"])
    op.create_index("idx_tiqer_log_teacher", "tiqer_export_log", ["teacher_id"])


def downgrade() -> None:
    op.drop_index("idx_tiqer_log_teacher", "tiqer_export_log")
    op.drop_index("idx_tiqer_log_session", "tiqer_export_log")
    op.drop_table("tiqer_export_log")
    op.drop_column("quiz_questions", "skill_tag")
