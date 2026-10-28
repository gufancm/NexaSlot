"""v2 waitlist, holds, notifications and outbox

Revision ID: a7c41d9e2b10
Revises: c143587f8700
Create Date: 2026-10-28 10:00:00.000000

Incremental migration: existing V1 tables and rows are preserved.
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes

revision = "a7c41d9e2b10"
down_revision = "c143587f8700"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "booking_holds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column(
            "status", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reservation_id"], ["reservations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_holds_status_expires", "booking_holds", ["status", "expires_at"]
    )
    op.create_index(
        "ix_holds_resource_start", "booking_holds", ["resource_id", "start_at"]
    )

    op.create_table(
        "waitlist_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column(
            "status", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False
        ),
        sa.Column("hold_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["hold_id"], ["booking_holds.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_waitlist_queue",
        "waitlist_entries",
        ["resource_id", "start_at", "end_at", "status", "created_at", "id"],
    )
    op.create_index(
        "ix_waitlist_user_created", "waitlist_entries", ["user_id", "created_at"]
    )

    op.add_column("resource_slots", sa.Column("current_hold_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_resource_slots_current_hold",
        "resource_slots",
        "booking_holds",
        ["current_hold_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # MySQL forbids a CHECK constraint that references a column whose foreign
    # key uses SET NULL. V1 created this FK with SET NULL; reservations are
    # never physically deleted, so RESTRICT is the correct V2 behaviour.
    op.execute(
        "SET @fk_name := (SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'resource_slots' "
        "AND COLUMN_NAME = 'current_reservation_id' "
        "AND REFERENCED_TABLE_NAME = 'reservations' LIMIT 1)"
    )
    op.execute(
        "SET @drop_sql := IF(@fk_name IS NULL, 'SELECT 1', "
        "CONCAT('ALTER TABLE resource_slots DROP FOREIGN KEY `', @fk_name, '`'))"
    )
    op.execute("PREPARE drop_fk_stmt FROM @drop_sql")
    op.execute("EXECUTE drop_fk_stmt")
    op.execute("DEALLOCATE PREPARE drop_fk_stmt")
    op.execute(
        "ALTER TABLE resource_slots ADD CONSTRAINT fk_resource_slots_current_reservation "
        "FOREIGN KEY (current_reservation_id) REFERENCES reservations(id) "
        "ON DELETE RESTRICT"
    )
    op.create_check_constraint(
        "ck_slot_single_owner",
        "resource_slots",
        "current_reservation_id IS NULL OR current_hold_id IS NULL",
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("type", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "user_id", name="uq_notification_event_user"),
    )
    op.create_index(
        "ix_notifications_user_created", "notifications", ["user_id", "created_at"]
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("aggregate_id", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_outbox_status_available", "outbox_events", ["status", "available_at"]
    )

    # At most one active waitlist entry per (resource, user, exact window).
    # A generated column keeps MySQL's unique index portable without using
    # functional key parts; terminal rows get NULL and are therefore ignored.
    op.execute(
        "ALTER TABLE waitlist_entries ADD COLUMN active_flag TINYINT "
        "GENERATED ALWAYS AS (CASE WHEN status IN ('WAITING','OFFERED') "
        "THEN 1 ELSE NULL END) STORED"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_waitlist_active ON waitlist_entries "
        "(resource_id, user_id, start_at, end_at, active_flag)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX uq_waitlist_active ON waitlist_entries")
    op.execute("ALTER TABLE waitlist_entries DROP COLUMN active_flag")

    op.drop_table("outbox_events")
    op.drop_table("notifications")

    op.drop_constraint("ck_slot_single_owner", "resource_slots", type_="check")
    op.drop_constraint("fk_resource_slots_current_hold", "resource_slots", type_="foreignkey")
    op.drop_column("resource_slots", "current_hold_id")

    # Restore the V1 SET NULL behaviour so a downgrade leaves the schema as it
    # was before V2, even though V2 itself relies on RESTRICT.
    op.drop_constraint(
        "fk_resource_slots_current_reservation",
        "resource_slots",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_resource_slots_current_reservation_v1",
        "resource_slots",
        "reservations",
        ["current_reservation_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_table("waitlist_entries")
    op.drop_table("booking_holds")
