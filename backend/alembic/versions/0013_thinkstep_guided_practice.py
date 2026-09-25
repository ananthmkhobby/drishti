"""Add ThinkStep guided-practice tables: practice_questions, practice_attempts

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

_JsonType = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "practice_questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("ai_output_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("subject", sa.String(100), nullable=True),
        sa.Column("topic", sa.String(255), nullable=True),
        sa.Column("skill_tag", sa.String(255), nullable=True),
        sa.Column("difficulty", sa.String(20), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("answer_domain", sa.String(20), nullable=False, server_default="other"),
        sa.Column("expected_solution_graph", _JsonType, nullable=True),
        sa.Column("final_answer", _JsonType, nullable=True),
        sa.Column("known_misconceptions", _JsonType, nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="ai_generated"),
        sa.Column("generated_from_ocr_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending_review"),
        sa.Column("teacher_edited", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ai_output_id"], ["ai_outputs.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_practice_questions_session_id", "practice_questions", ["session_id"])

    op.create_table(
        "practice_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("student_label", sa.String(200), nullable=True),
        sa.Column("image_path", sa.String(500), nullable=True),
        sa.Column("image_size_kb", sa.Integer(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("capture_quality_status", sa.String(30), nullable=True),
        sa.Column("capture_quality_reason", sa.Text(), nullable=True),
        sa.Column("recognized_steps", _JsonType, nullable=True),
        sa.Column("recognition_confidence", sa.Float(), nullable=True),
        sa.Column("normalized_step", _JsonType, nullable=True),
        sa.Column("gate_d_result", _JsonType, nullable=True),
        sa.Column("validation_status", sa.String(30), nullable=True),
        sa.Column("validation_reason_code", sa.String(50), nullable=True),
        sa.Column("misconception_code", sa.String(50), nullable=True),
        sa.Column("student_state", sa.String(30), nullable=True),
        sa.Column("hint_level", sa.Integer(), nullable=True),
        sa.Column("hint_text", sa.Text(), nullable=True),
        sa.Column("hint_hash", sa.String(64), nullable=True),
        sa.Column("post_hint_outcome", sa.String(30), nullable=True),
        sa.Column("latency_ms_breakdown", _JsonType, nullable=True),
        sa.Column("teacher_override", _JsonType, nullable=True),
        sa.Column("teacher_feedback", sa.String(20), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="processing"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["question_id"], ["practice_questions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_practice_attempts_question_id", "practice_attempts", ["question_id"])
    op.create_index("ix_practice_attempts_session_id", "practice_attempts", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_practice_attempts_session_id", table_name="practice_attempts")
    op.drop_index("ix_practice_attempts_question_id", table_name="practice_attempts")
    op.drop_table("practice_attempts")
    op.drop_index("ix_practice_questions_session_id", table_name="practice_questions")
    op.drop_table("practice_questions")
