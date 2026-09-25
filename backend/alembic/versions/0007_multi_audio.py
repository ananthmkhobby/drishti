"""allow multiple audio recordings per session

Revision ID: 0007_multi_audio
Revises: 0006_session_audio
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_multi_audio"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite cannot DROP UNIQUE constraints directly.
    # Recreate the table without the UNIQUE(session_id) constraint,
    # and add a recording_number column.
    with op.batch_alter_table("session_audios") as batch_op:
        batch_op.add_column(sa.Column("recording_number", sa.Integer(), nullable=False, server_default="1"))
        batch_op.drop_constraint("uq_session_audios_session_id", type_="unique")


def downgrade() -> None:
    with op.batch_alter_table("session_audios") as batch_op:
        batch_op.drop_column("recording_number")
        batch_op.create_unique_constraint("uq_session_audios_session_id", ["session_id"])
