"""Add textbooks + textbook_chapters tables

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "textbooks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(300), nullable=True),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("raw_pages", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_textbooks_session_id", "textbooks", ["session_id"])

    op.create_table(
        "textbook_chapters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("textbook_id", sa.Uuid(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("start_page", sa.Integer(), nullable=False),
        sa.Column("end_page", sa.Integer(), nullable=False),
        sa.Column("current_segment_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("segments", sa.JSON(), nullable=True),
        sa.Column("taught_log", sa.JSON(), nullable=True),
        sa.Column("last_taught_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["textbook_id"], ["textbooks.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_textbook_chapters_textbook_id", "textbook_chapters", ["textbook_id"])


def downgrade() -> None:
    op.drop_index("ix_textbook_chapters_textbook_id", table_name="textbook_chapters")
    op.drop_table("textbook_chapters")

    op.drop_index("ix_textbooks_session_id", table_name="textbooks")
    op.drop_table("textbooks")
