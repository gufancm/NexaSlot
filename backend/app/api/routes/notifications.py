import uuid

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, SessionDep
from app.models import Message
from app.schemas import NotificationPublic, NotificationsPublic
from app.services.notifications import (
    list_notifications,
    mark_all_read,
    mark_read,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationsPublic)
def read_notifications(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    unread_only: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> NotificationsPublic:
    return list_notifications(
        session=session,
        user=current_user,
        page=page,
        page_size=page_size,
        unread_only=unread_only,
    )


@router.post("/read-all", response_model=Message)
def mark_all_notifications_read(
    *, session: SessionDep, current_user: CurrentUser
) -> Message:
    count = mark_all_read(session=session, user=current_user)
    return Message(message=f"Marked {count} notification(s) as read")


@router.post("/{notification_id}/read", response_model=NotificationPublic)
def mark_notification_read(
    *, session: SessionDep, current_user: CurrentUser, notification_id: uuid.UUID
) -> NotificationPublic:
    return mark_read(
        session=session, user=current_user, notification_id=notification_id
    )
