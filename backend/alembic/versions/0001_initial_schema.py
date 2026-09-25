"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-27

Notes:
- teacher_id / classroom_id in sessions are plain UUID columns (no FK).
  FK constraints will be added in Phase 2 when the teachers/classrooms
  tables are created with the auth module.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("teacher_id", sa.Uuid(), nullable=False),
        sa.Column("classroom_id", sa.Uuid(), nullable=True),
        sa.Column("local_session_id", sa.String(100), nullable=True),
        sa.Column("subject", sa.String(100), nullable=True),
        sa.Column("grade", sa.String(50), nullable=True),
        sa.Column("board_type", sa.String(50), nullable=False, server_default="chalkboard"),
        sa.Column("capture_mode", sa.String(50), nullable=False, server_default="time_based"),
        sa.Column("capture_interval_sec", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("frame_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sync_status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("local_session_id"),
    )
    op.create_index("idx_sessions_teacher", "sessions", ["teacher_id"])
    op.create_index("idx_sessions_classroom", "sessions", ["classroom_id"])
    op.create_index(
        "idx_sessions_sync_status",
        "sessions",
        ["sync_status"],
        postgresql_where=sa.text("sync_status != 'synced'"),
    )

    op.create_table(
        "frames",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("local_frame_id", sa.String(100), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("image_path", sa.String(500), nullable=True),
        sa.Column("image_size_kb", sa.Integer(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ocr_status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("ai_status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "local_frame_id", name="uq_frame_local_id"),
        sa.UniqueConstraint("session_id", "sequence_no", name="uq_frame_seq"),
    )
    op.create_index("idx_frames_session", "frames", ["session_id"])

    op.create_table(
        "ocr_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("frame_id", sa.Uuid(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("structured_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("engine_used", sa.String(50), nullable=True),
        sa.Column("processing_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["frame_id"], ["frames.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("frame_id"),
    )

    op.create_table(
        "ai_outputs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("output_type", sa.String(50), nullable=False),
        sa.Column("content_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("content_url", sa.String(500), nullable=True),
        sa.Column("model_used", sa.String(100), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("generation_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "output_type", name="uq_output_session_type"),
    )
    op.create_index("idx_ai_outputs_session", "ai_outputs", ["session_id"])

    op.create_table(
        "quiz_questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("ai_output_id", sa.Uuid(), nullable=True),
        sa.Column("question_type", sa.String(20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("correct_answer", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("bloom_level", sa.String(30), nullable=True),
        sa.Column("topic", sa.String(255), nullable=True),
        sa.Column("teacher_edited", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("tiqer_exported", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ai_output_id"], ["ai_outputs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_quiz_session", "quiz_questions", ["session_id"])

    op.create_table(
        "classroom_memory",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("teacher_id", sa.Uuid(), nullable=False),
        sa.Column("last_session_id", sa.Uuid(), nullable=True),
        sa.Column("topics_covered", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("pending_concepts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("suggested_next", sa.Text(), nullable=True),
        sa.Column(
            "last_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["last_session_id"], ["sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("teacher_id"),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_type", sa.String(50), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("frame_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_url", sa.String(500), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_jobs_session", "jobs", ["session_id"])


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("classroom_memory")
    op.drop_table("quiz_questions")
    op.drop_table("ai_outputs")
    op.drop_table("ocr_results")
    op.drop_table("frames")
    op.drop_table("sessions")
