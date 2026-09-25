"""Add title column to sessions

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("title", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "title")
