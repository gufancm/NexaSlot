import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.errors import api_error
from app.core.ratelimit import rate_limit
from app.models import OrgRole
from app.schemas import (
    ErrorCode,
    OfferPublic,
    ReservationPublic,
    WaitlistCreate,
    WaitlistEntryPublic,
    WaitlistPublic,
)
from app.services.orgs import ensure_active_resource, require_resource_access
from app.services.waitlist import (
    confirm_offer,
    decline_offer,
    get_offer,
    join_waitlist,
    leave_waitlist,
    list_my_entries,
    list_org_entries,
)

router = APIRouter(tags=["waitlist"])


@router.post(
    "/waitlist",
    response_model=WaitlistEntryPublic,
    status_code=201,
    dependencies=[
        Depends(
            rate_limit(
                "waitlist-join",
                settings.RATE_LIMIT_WAITLIST_CAPACITY,
                settings.RATE_LIMIT_WAITLIST_REFILL_PER_MINUTE,
                fail_closed=True,
            )
        )
    ],
)
def join_waitlist_endpoint(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    payload: WaitlistCreate,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> WaitlistEntryPublic:
    if not idempotency_key or not idempotency_key.strip():
        raise api_error(
            400,
            ErrorCode.IDEMPOTENCY_KEY_REQUIRED,
            "The Idempotency-Key header is required for joining the waitlist",
        )
    if len(idempotency_key) > 128:
        raise api_error(422, ErrorCode.INVALID_REQUEST, "Idempotency-Key is too long")

    access = require_resource_access(
        session, current_user, payload.resource_id, OrgRole.MEMBER
    )
    ensure_active_resource(access.resource)
    if access.site.status != "ACTIVE":
        raise api_error(
            400, ErrorCode.INVALID_REQUEST, "This site is not open for booking"
        )
    entry, _replayed = join_waitlist(
        user=current_user,
        resource=access.resource,
        site=access.site,
        payload=payload,
        idem_key=idempotency_key.strip(),
    )
    return entry


@router.get("/waitlist/me", response_model=WaitlistPublic)
def read_my_waitlist(
    *,
    current_user: CurrentUser,
    status: str | None = Query(
        default=None,
        pattern="^(WAITING|OFFERED|CONFIRMED|EXPIRED|DECLINED|CANCELLED)$",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> WaitlistPublic:
    rows, total = list_my_entries(
        user=current_user, status=status, page=page, page_size=page_size
    )
    return WaitlistPublic(data=rows, count=total)


@router.delete("/waitlist/{entry_id}", response_model=WaitlistEntryPublic)
def leave_waitlist_endpoint(
    *, current_user: CurrentUser, entry_id: uuid.UUID
) -> WaitlistEntryPublic:
    return leave_waitlist(user=current_user, entry_id=entry_id)


@router.get("/waitlist/offers/{hold_id}", response_model=OfferPublic)
def read_offer(*, current_user: CurrentUser, hold_id: uuid.UUID) -> OfferPublic:
    return get_offer(user=current_user, hold_id=hold_id)


@router.post(
    "/waitlist/offers/{hold_id}/confirm",
    response_model=ReservationPublic,
    status_code=201,
)
def confirm_offer_endpoint(
    *, current_user: CurrentUser, hold_id: uuid.UUID
) -> ReservationPublic:
    return confirm_offer(user=current_user, hold_id=hold_id)


@router.post("/waitlist/offers/{hold_id}/decline", response_model=WaitlistEntryPublic)
def decline_offer_endpoint(
    *, current_user: CurrentUser, hold_id: uuid.UUID
) -> WaitlistEntryPublic:
    return decline_offer(user=current_user, hold_id=hold_id)


@router.get("/admin/waitlist", response_model=WaitlistPublic)
def read_organization_waitlist(
    *,
    current_user: CurrentUser,
    org_id: uuid.UUID,
    status: str | None = Query(
        default=None,
        pattern="^(WAITING|OFFERED|CONFIRMED|EXPIRED|DECLINED|CANCELLED)$",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> WaitlistPublic:
    rows, total = list_org_entries(
        user=current_user,
        org_id=org_id,
        status=status,
        page=page,
        page_size=page_size,
    )
    return WaitlistPublic(data=rows, count=total)
