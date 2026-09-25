"""Add textbook_figures table

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "textbook_figures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("textbook_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("image_path", sa.String(500), nullable=False),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["textbook_id"], ["textbooks.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_textbook_figures_textbook_id", "textbook_figures", ["textbook_id"])


def downgrade() -> None:
    op.drop_index("ix_textbook_figures_textbook_id", table_name="textbook_figures")
    op.drop_table("textbook_figures")
