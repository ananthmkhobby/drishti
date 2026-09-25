"""Add practice_stations table + practice_attempts.station_id

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "practice_stations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("active_question_id", sa.Uuid(), nullable=True),
        sa.Column("capture_interval_sec", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("status", sa.String(20), nullable=False, server_default="idle"),
        sa.Column("last_capture_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("teacher_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["active_question_id"], ["practice_questions.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_practice_stations_session_id", "practice_stations", ["session_id"])

    # batch mode: SQLite can't ALTER a constraint onto an existing table
    # directly (copy-and-move strategy instead); on Postgres this compiles
    # down to the same plain ADD COLUMN + ADD CONSTRAINT either way.
    with op.batch_alter_table("practice_attempts") as batch_op:
        batch_op.add_column(sa.Column("station_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_practice_attempts_station_id", "practice_stations",
            ["station_id"], ["id"], ondelete="SET NULL",
        )
    op.create_index("ix_practice_attempts_station_id", "practice_attempts", ["station_id"])


def downgrade() -> None:
    op.drop_index("ix_practice_attempts_station_id", table_name="practice_attempts")
    with op.batch_alter_table("practice_attempts") as batch_op:
        batch_op.drop_constraint("fk_practice_attempts_station_id", type_="foreignkey")
        batch_op.drop_column("station_id")

    op.drop_index("ix_practice_stations_session_id", table_name="practice_stations")
    op.drop_table("practice_stations")
