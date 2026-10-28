"""Remove local test data while keeping the demo organization and superuser.

This is a development-only maintenance tool. It deletes every organization
except the one named by ``--keep-org`` and every user except the superuser
named by ``--keep-email``, together with their bookings, waitlists, holds,
slots, notifications and audit records.

Always take a database backup before running it with ``--yes``:

    cd backend
    uv run python scripts/cleanup_test_data.py          # dry run
    uv run python scripts/cleanup_test_data.py --yes    # execute
"""

import argparse

from sqlalchemy import text
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine


def _one(db: Session, sql: str, **params: str) -> str | None:
    row = db.execute(text(sql), params).first()
    return str(row[0]) if row else None


def _count(db: Session, sql: str, **params: str) -> int:
    row = db.execute(text(sql), params).first()
    return int(row[0]) if row else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-org", default="NexaSlot 演示组织")
    parser.add_argument("--keep-email", default=settings.FIRST_SUPERUSER)
    parser.add_argument("--yes", action="store_true", help="execute the cleanup")
    args = parser.parse_args()

    with Session(engine) as db:
        keep_org = _one(
            db, "SELECT id FROM organizations WHERE name = :name", name=args.keep_org
        )
        keep_user = _one(
            db, "SELECT id FROM `user` WHERE email = :email", email=args.keep_email
        )
        if not keep_org:
            raise SystemExit(f"Keep organization not found: {args.keep_org}")
        if not keep_user:
            raise SystemExit(f"Keep user not found: {args.keep_email}")

        orgs = _count(db, "SELECT COUNT(*) FROM organizations")
        users = _count(db, "SELECT COUNT(*) FROM `user`")
        extra_orgs = _count(
            db, "SELECT COUNT(*) FROM organizations WHERE id <> :keep", keep=keep_org
        )
        extra_users = _count(
            db, "SELECT COUNT(*) FROM `user` WHERE id <> :keep", keep=keep_user
        )
        print(  # noqa: T201
            f"keep_org={keep_org} keep_user={keep_user}\n"
            f"current: {orgs} organizations, {users} users\n"
            f"would delete: {extra_orgs} organizations, {extra_users} users"
        )
        if not args.yes:
            print("dry run only; add --yes to execute")  # noqa: T201
            return

        statements = [
            "UPDATE resource_slots SET current_reservation_id = NULL, current_hold_id = NULL",
            "DELETE FROM reservation_slots",
            "DELETE FROM notifications",
            "DELETE FROM outbox_events",
            "DELETE FROM waitlist_entries",
            "DELETE FROM booking_holds",
            "DELETE FROM reservations",
            "DELETE FROM idempotency_records",
            "DELETE FROM audit_logs",
            "DELETE FROM resource_slots WHERE resource_id NOT IN (SELECT r.id FROM resources r JOIN sites s ON s.id = r.site_id WHERE s.organization_id = :keep_org)",
            "DELETE FROM resources WHERE site_id IN (SELECT id FROM sites WHERE organization_id <> :keep_org)",
            "DELETE FROM sites WHERE organization_id <> :keep_org",
            "DELETE FROM organization_members WHERE organization_id <> :keep_org",
            "DELETE FROM organizations WHERE id <> :keep_org",
            "DELETE FROM organization_members WHERE user_id <> :keep_user",
            "DELETE FROM `user` WHERE id <> :keep_user",
        ]
        for statement in statements:
            db.execute(text(statement), {"keep_org": keep_org, "keep_user": keep_user})
        db.commit()

        orgs_after = _count(db, "SELECT COUNT(*) FROM organizations")
        users_after = _count(db, "SELECT COUNT(*) FROM `user`")
        print(f"done: {orgs_after} organizations, {users_after} users remain")  # noqa: T201


if __name__ == "__main__":
    main()
