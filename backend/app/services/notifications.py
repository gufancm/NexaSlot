from datetime import datetime

from sqlmodel import Session, func, select

from app.core.errors import api_error
from app.core.time import db_now, from_db, utcnow
from app.models import Notification, User
from app.schemas import ErrorCode, NotificationPublic, NotificationsPublic


def _public(item: Notification) -> NotificationPublic:
    payload = item.payload or {}
    return NotificationPublic(
        id=item.id,
        type=item.type,
        title=str(payload.get("title", "NexaSlot")),
        message=str(payload.get("message", "")),
        read_at=from_db(item.read_at),
        created_at=from_db(item.created_at) or utcnow(),
    )


def unread_count(session: Session, user_id) -> int:
    return int(
        session.exec(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        ).one()
    )


def list_notifications(
    *, session: Session, user: User, page: int, page_size: int, unread_only: bool
) -> NotificationsPublic:
    statement = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        statement = statement.where(Notification.read_at.is_(None))
    total = int(
        session.exec(select(func.count()).select_from(statement.subquery())).one()
    )
    rows = session.exec(
        statement.order_by(Notification.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return NotificationsPublic(
        data=[_public(item) for item in rows],
        count=total,
        unread_count=unread_count(session, user.id),
    )


def mark_read(*, session: Session, user: User, notification_id) -> NotificationPublic:
    item = session.get(Notification, notification_id)
    if item is None or item.user_id != user.id:
        raise api_error(404, ErrorCode.NOT_FOUND, "Notification not found")
    if item.read_at is None:
        item.read_at = db_now()
        session.add(item)
        session.commit()
        session.refresh(item)
    return _public(item)


def mark_all_read(*, session: Session, user: User) -> int:
    rows = session.exec(
        select(Notification).where(
            Notification.user_id == user.id, Notification.read_at.is_(None)
        )
    ).all()
    now: datetime = db_now()
    for item in rows:
        item.read_at = now
        session.add(item)
    session.commit()
    return len(rows)
