"""Add zone_data JSON column to audience_metrics

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-03
"""

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audience_metrics", sa.Column("zone_data", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("audience_metrics", "zone_data")
