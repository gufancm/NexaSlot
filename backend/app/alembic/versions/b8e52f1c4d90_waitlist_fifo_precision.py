"""waitlist FIFO timestamp precision

Revision ID: b8e52f1c4d90
Revises: a7c41d9e2b10
Create Date: 2026-10-28 11:00:00.000000

MySQL DATETIME defaults to whole seconds. FIFO ordering is defined by
``created_at, id``; whole-second timestamps would make two entries created in
the same second fall back to random UUID order. Store microseconds so the
insertion order is preserved.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "b8e52f1c4d90"
down_revision = "a7c41d9e2b10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table, column in (
        ("waitlist_entries", "created_at"),
        ("waitlist_entries", "updated_at"),
        ("booking_holds", "created_at"),
        ("booking_holds", "updated_at"),
        ("booking_holds", "expires_at"),
    ):
        op.alter_column(
            table,
            column,
            type_=mysql.DATETIME(fsp=6),
            existing_type=sa.DateTime(),
            existing_nullable=False,
        )


def downgrade() -> None:
    for table, column in (
        ("waitlist_entries", "created_at"),
        ("waitlist_entries", "updated_at"),
        ("booking_holds", "created_at"),
        ("booking_holds", "updated_at"),
        ("booking_holds", "expires_at"),
    ):
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(),
            existing_type=mysql.DATETIME(fsp=6),
            existing_nullable=False,
        )
