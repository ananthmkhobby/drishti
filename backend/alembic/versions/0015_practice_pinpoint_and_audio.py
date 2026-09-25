"""Add practice_attempts.error_step_index, audio_path, input_type

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("practice_attempts") as batch_op:
        # Gates D/E-F: which recognized step (0-based index) the error was
        # first pinpointed at — null when there is no error (valid_progress/
        # incomplete/alternative_valid_method) or the classification itself
        # was ambiguous. Lets the frontend highlight the specific line
        # instead of only reporting an aggregate verdict.
        batch_op.add_column(sa.Column("error_step_index", sa.Integer(), nullable=True))
        # A spoken answer instead of a photographed one — for theory/
        # conceptual subjects where there's no handwritten work to
        # photograph. image_path was already nullable; this mirrors it.
        batch_op.add_column(sa.Column("audio_path", sa.String(500), nullable=True))
        batch_op.add_column(
            sa.Column("input_type", sa.String(10), nullable=False, server_default="image")
        )


def downgrade() -> None:
    with op.batch_alter_table("practice_attempts") as batch_op:
        batch_op.drop_column("input_type")
        batch_op.drop_column("audio_path")
        batch_op.drop_column("error_step_index")
