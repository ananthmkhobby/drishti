"""full entity schema

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-27

Creates the full entity graph:
  programs → schools → teachers → classrooms → (sessions already exist)
  teachers → devices
  sessions → sync_queue (device-level sync tracking)
  sessions/ai_outputs → experiment_suggestions, missing_concepts

Also retrofits FK constraints onto existing tables:
  sessions.teacher_id     → teachers.id
  sessions.classroom_id   → classrooms.id
  classroom_memory.teacher_id → teachers.id
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # programs                                                             #
    # ------------------------------------------------------------------ #
    op.create_table(
        "programs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(50), nullable=False, server_default="ngo"),
        sa.Column("org_name", sa.String(255), nullable=True),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------------------ #
    # schools                                                              #
    # ------------------------------------------------------------------ #
    op.create_table(
        "schools",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("district", sa.String(255), nullable=True),
        sa.Column("state", sa.String(100), nullable=True),
        sa.Column("pincode", sa.String(10), nullable=True),
        sa.Column("address", sa.String(500), nullable=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_schools_program", "schools", ["program_id"])

    # ------------------------------------------------------------------ #
    # teachers                                                             #
    # ------------------------------------------------------------------ #
    op.create_table(
        "teachers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("role", sa.String(50), nullable=False, server_default="teacher"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("phone"),
    )
    op.create_index("idx_teachers_school", "teachers", ["school_id"])

    # ------------------------------------------------------------------ #
    # classrooms                                                           #
    # ------------------------------------------------------------------ #
    op.create_table(
        "classrooms",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("grade", sa.String(50), nullable=True),
        sa.Column("section", sa.String(20), nullable=True),
        sa.Column("board_type", sa.String(50), nullable=False, server_default="chalkboard"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_classrooms_school", "classrooms", ["school_id"])

    # ------------------------------------------------------------------ #
    # Retrofit FK constraints on pre-existing tables                       #
    # ------------------------------------------------------------------ #
    op.create_foreign_key(
        "fk_sessions_teacher_id",
        "sessions",
        "teachers",
        ["teacher_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_sessions_classroom_id",
        "sessions",
        "classrooms",
        ["classroom_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_classroom_memory_teacher_id",
        "classroom_memory",
        "teachers",
        ["teacher_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ------------------------------------------------------------------ #
    # devices                                                              #
    # ------------------------------------------------------------------ #
    op.create_table(
        "devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("teacher_id", sa.Uuid(), nullable=False),
        sa.Column("device_fingerprint", sa.String(255), nullable=False),
        sa.Column("platform", sa.String(30), nullable=False),
        sa.Column("os_version", sa.String(50), nullable=True),
        sa.Column("model_name", sa.String(100), nullable=True),
        sa.Column("app_version", sa.String(20), nullable=True),
        sa.Column("push_token", sa.String(500), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_fingerprint"),
    )
    op.create_index("idx_devices_teacher", "devices", ["teacher_id"])

    # ------------------------------------------------------------------ #
    # sync_queue                                                           #
    # ------------------------------------------------------------------ #
    op.create_table(
        "sync_queue",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("device_fingerprint", sa.String(255), nullable=True),
        sa.Column("teacher_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("local_entity_id", sa.String(100), nullable=True),
        sa.Column("remote_entity_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_sync_queue_device", "sync_queue", ["device_id"])
    op.create_index("idx_sync_queue_teacher", "sync_queue", ["teacher_id"])
    op.create_index("idx_sync_queue_session", "sync_queue", ["session_id"])
    op.create_index("idx_sync_queue_status", "sync_queue", ["status"])

    # ------------------------------------------------------------------ #
    # experiment_suggestions                                               #
    # ------------------------------------------------------------------ #
    op.create_table(
        "experiment_suggestions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("ai_output_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("topic", sa.String(255), nullable=True),
        sa.Column("difficulty", sa.String(30), nullable=True),
        sa.Column("materials", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("steps", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expected_outcome", sa.Text(), nullable=True),
        sa.Column("safety_note", sa.Text(), nullable=True),
        sa.Column("teacher_approved", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ai_output_id"], ["ai_outputs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_exp_suggestions_session", "experiment_suggestions", ["session_id"])

    # ------------------------------------------------------------------ #
    # missing_concepts                                                     #
    # ------------------------------------------------------------------ #
    op.create_table(
        "missing_concepts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("ai_output_id", sa.Uuid(), nullable=True),
        sa.Column("concept", sa.String(500), nullable=False),
        sa.Column("concept_type", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("suggested_remediation", sa.Text(), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("resolved_in_session_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ai_output_id"], ["ai_outputs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["resolved_in_session_id"], ["sessions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_missing_concepts_session", "missing_concepts", ["session_id"])
    op.create_index(
        "idx_missing_concepts_unresolved",
        "missing_concepts",
        ["session_id"],
        postgresql_where=sa.text("resolved = false"),
    )


def downgrade() -> None:
    op.drop_table("missing_concepts")
    op.drop_table("experiment_suggestions")
    op.drop_table("sync_queue")
    op.drop_table("devices")

    op.drop_constraint("fk_classroom_memory_teacher_id", "classroom_memory", type_="foreignkey")
    op.drop_constraint("fk_sessions_classroom_id", "sessions", type_="foreignkey")
    op.drop_constraint("fk_sessions_teacher_id", "sessions", type_="foreignkey")

    op.drop_table("classrooms")
    op.drop_table("teachers")
    op.drop_table("schools")
    op.drop_table("programs")
