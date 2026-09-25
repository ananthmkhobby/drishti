"""Add textbooks.language_code + language_name

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("textbooks") as batch_op:
        batch_op.add_column(sa.Column("language_code", sa.String(5), nullable=True))
        batch_op.add_column(sa.Column("language_name", sa.String(50), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("textbooks") as batch_op:
        batch_op.drop_column("language_name")
        batch_op.drop_column("language_code")
