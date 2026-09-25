"""Add emotion percentage columns to audience_metrics

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audience_metrics", sa.Column("happy_pct",      sa.Float(), nullable=False, server_default="0.0"))
    op.add_column("audience_metrics", sa.Column("confused_pct",   sa.Float(), nullable=False, server_default="0.0"))
    op.add_column("audience_metrics", sa.Column("surprised_pct",  sa.Float(), nullable=False, server_default="0.0"))
    op.add_column("audience_metrics", sa.Column("disengaged_pct", sa.Float(), nullable=False, server_default="0.0"))


def downgrade() -> None:
    op.drop_column("audience_metrics", "disengaged_pct")
    op.drop_column("audience_metrics", "surprised_pct")
    op.drop_column("audience_metrics", "confused_pct")
    op.drop_column("audience_metrics", "happy_pct")
