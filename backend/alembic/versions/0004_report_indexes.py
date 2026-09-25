"""Add indexes to support report queries

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-27

Changes:
  - idx_sessions_created_at        — order-by in time-series queries
  - idx_sessions_teacher_created   — (teacher_id, created_at) composite — hot report path
  - idx_sessions_teacher_sync      — sync breakdown per teacher
  - idx_quiz_topic                 — GROUP BY topic in topic coverage report
  - idx_quiz_bloom                 — GROUP BY bloom_level in bloom distribution
  - idx_missing_concepts_resolved  — WHERE resolved = FALSE filter
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("idx_sessions_created_at",      "sessions",         ["created_at"])
    op.create_index("idx_sessions_teacher_created",  "sessions",         ["teacher_id", "created_at"])
    op.create_index("idx_sessions_teacher_sync",     "sessions",         ["teacher_id", "sync_status"])
    op.create_index("idx_quiz_topic",                "quiz_questions",   ["topic"])
    op.create_index("idx_quiz_bloom",                "quiz_questions",   ["bloom_level"])
    op.create_index("idx_missing_concepts_resolved", "missing_concepts", ["resolved"])


def downgrade() -> None:
    op.drop_index("idx_missing_concepts_resolved", "missing_concepts")
    op.drop_index("idx_quiz_bloom",                "quiz_questions")
    op.drop_index("idx_quiz_topic",                "quiz_questions")
    op.drop_index("idx_sessions_teacher_sync",     "sessions")
    op.drop_index("idx_sessions_teacher_created",  "sessions")
    op.drop_index("idx_sessions_created_at",       "sessions")
