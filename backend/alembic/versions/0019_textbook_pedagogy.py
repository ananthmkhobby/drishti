"""Add textbooks.content_type + textbook_chapters.pedagogy

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("textbooks") as batch_op:
        batch_op.add_column(sa.Column("content_type", sa.String(20), nullable=False, server_default="textbook"))
    with op.batch_alter_table("textbook_chapters") as batch_op:
        batch_op.add_column(sa.Column("pedagogy", sa.String(20), nullable=False, server_default="standard"))


def downgrade() -> None:
    with op.batch_alter_table("textbook_chapters") as batch_op:
        batch_op.drop_column("pedagogy")
    with op.batch_alter_table("textbooks") as batch_op:
        batch_op.drop_column("content_type")
