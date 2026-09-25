"""Add practice_stations.camera_mount — front-facing vs overhead desk mount

"desk" mount reliably comes out rotated 90 degrees and mirrored left-right
relative to the page (camera looking straight down has a different "up"
than the page does) — this lets a teacher fix that once per station instead
of the student fighting a fixed physical mount every capture.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "practice_stations",
        sa.Column("camera_mount", sa.String(20), nullable=False, server_default="front"),
    )


def downgrade() -> None:
    op.drop_column("practice_stations", "camera_mount")
