import json
import time
import uuid
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.deps import CurrentUser, SessionDep, require_org, require_resource
from app.cache.availability import (
    availability_key,
    get_availability,
    get_resource,
    invalidate_resource,
    lock_key,
    resource_key,
    set_availability,
    set_resource,
)
from app.core.config import settings
from app.core.errors import api_error
from app.core.redis_sync import acquire_lock, cache_delete
from app.core.time import from_db, get_timezone, local_now, to_db, utcnow
from app.models import (
    OpeningRule,
    OrgRole,
    Reservation,
    ReservationStatus,
    Resource,
    ResourceBlackout,
    ResourceSlot,
    Site,
    SlotStatus,
)
from app.schemas import (
    AvailabilityPublic,
    BlackoutCreate,
    BlackoutPublic,
    ErrorCode,
    OpeningRulePublic,
    OpeningRulesPublic,
    OpeningRulesReplace,
    ResourceCreate,
    ResourcePublic,
    ResourcesPublic,
    ResourceUpdate,
)
from app.services.audit import record_audit
from app.services.catalog import resource_public, resource_public_list
from app.services.orgs import OrgAccess, ResourceAccess, ensure_publishable_site
from app.services.slots import build_availability

router = APIRouter(tags=["resources"])

OrgManagerDep = Annotated[OrgAccess, Depends(require_org(OrgRole.RESOURCE_MANAGER))]
ResourceManagerDep = Annotated[
    ResourceAccess, Depends(require_resource(OrgRole.RESOURCE_MANAGER))
]


def _site_in_org(session: Session, org_id: uuid.UUID, site_id: uuid.UUID) -> Site:
    site = session.get(Site, site_id)
    if site is None or site.organization_id != org_id:
        raise api_error(404, ErrorCode.NOT_FOUND, "Site not found in this organization")
    return site


def _validate_rules(rules: OpeningRulesReplace) -> None:
    by_weekday: dict[int, list[tuple[object, object]]] = {}
    for rule in rules.rules:
        by_weekday.setdefault(rule.weekday, []).append((rule.start_time, rule.end_time))
    for weekday, ranges in by_weekday.items():
        ranges.sort()
        for (_, previous_end), (next_start, _) in zip(ranges, ranges[1:], strict=False):
            if next_start < previous_end:
                raise api_error(
                    422,
                    ErrorCode.INVALID_REQUEST,
                    f"Opening rules overlap on weekday {weekday}",
                )


@router.get("/organizations/{org_id}/resources", response_model=ResourcesPublic)
def read_resources(
    *,
    session: SessionDep,
    org: Annotated[OrgAccess, Depends(require_org(OrgRole.MEMBER))],
    site_id: uuid.UUID | None = None,
    q: str | None = None,
    min_capacity: int | None = Query(default=None, ge=1),
    feature: str | None = None,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=12, ge=1, le=100),
) -> ResourcesPublic:
    site_ids = list(
        session.exec(
            select(Site.id).where(Site.organization_id == org.organization.id)
        ).all()
    )
    if not site_ids:
        return ResourcesPublic(data=[], count=0)

    statement = select(Resource).where(Resource.site_id.in_(site_ids))
    if site_id is not None:
        if site_id not in site_ids:
            raise api_error(404, ErrorCode.NOT_FOUND, "Site not found")
        statement = statement.where(Resource.site_id == site_id)
    if q:
        statement = statement.where(Resource.name.like(f"%{q.strip()}%"))
    if min_capacity is not None:
        statement = statement.where(Resource.capacity >= min_capacity)
    if feature:
        statement = statement.where(
            func.json_contains(
                Resource.features, json.dumps(feature, ensure_ascii=False)
            )
        )
    if status:
        statement = statement.where(Resource.status == status)

    count_statement = select(func.count()).select_from(statement.subquery())
    total = int(session.exec(count_statement).one())

    rows = session.exec(
        statement.order_by(Resource.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ResourcesPublic(data=resource_public_list(session, list(rows)), count=total)


@router.post(
    "/organizations/{org_id}/resources",
    response_model=ResourcePublic,
    status_code=201,
)
def create_resource(
    *,
    session: SessionDep,
    org: OrgManagerDep,
    current_user: CurrentUser,
    payload: ResourceCreate,
) -> ResourcePublic:
    site = _site_in_org(session, org.organization.id, payload.site_id)
    ensure_publishable_site(site)
    resource = Resource(
        site_id=site.id,
        name=payload.name.strip(),
        description=payload.description,
        capacity=payload.capacity,
        features=[item.strip() for item in payload.features if item.strip()],
    )
    session.add(resource)
    record_audit(
        session,
        actor_id=current_user.id,
        organization_id=org.organization.id,
        action="resource.create",
        target_type="resource",
        target_id=resource.id,
        detail={"name": resource.name, "site_id": str(site.id)},
    )
    session.commit()
    session.refresh(resource)
    return resource_public(session, resource, site)


@router.get("/resources/{resource_id}", response_model=ResourcePublic)
def read_resource(
    *,
    session: SessionDep,
    access: Annotated[ResourceAccess, Depends(require_resource())],
) -> ResourcePublic:
    key = resource_key(access.org.organization.id, access.resource.id)
    cached = get_resource(key)
    if cached is not None:
        return ResourcePublic.model_validate(cached)

    lock = lock_key(
        "resource", access.org.organization.id, access.resource.id, "detail"
    )
    if acquire_lock(lock, ttl_seconds=5):
        try:
            public = resource_public(session, access.resource, access.site)
            set_resource(key, public.model_dump(mode="json"))
            return public
        finally:
            cache_delete(lock)

    # Another request is rebuilding this key. Give it a brief chance before
    # falling back to MySQL instead of sending every waiter to the database.
    time.sleep(0.05)
    cached = get_resource(key)
    if cached is not None:
        return ResourcePublic.model_validate(cached)
    return resource_public(session, access.resource, access.site)


@router.patch("/resources/{resource_id}", response_model=ResourcePublic)
def update_resource(
    *,
    session: SessionDep,
    access: ResourceManagerDep,
    current_user: CurrentUser,
    payload: ResourceUpdate,
) -> ResourcePublic:
    resource = access.resource
    data = payload.model_dump(exclude_unset=True)

    if "site_id" in data and data["site_id"] != resource.site_id:
        site = _site_in_org(session, access.org.organization.id, data["site_id"])
        ensure_publishable_site(site)
        access = ResourceAccess(resource=resource, site=site, org=access.org)

    if data.get("status") == "INACTIVE":
        conflicting = session.exec(
            select(func.count())
            .select_from(Reservation)
            .where(
                Reservation.resource_id == resource.id,
                Reservation.status == ReservationStatus.CONFIRMED.value,
                Reservation.end_at > to_db(utcnow()),
            )
        ).one()
        if int(conflicting) > 0:
            raise api_error(
                409,
                ErrorCode.CONFLICT,
                f"This resource still has {int(conflicting)} upcoming reservation(s)",
            )

    for key, value in data.items():
        setattr(resource, key, value)
    if "features" in data and data["features"] is not None:
        resource.features = [item.strip() for item in data["features"] if item.strip()]

    record_audit(
        session,
        actor_id=current_user.id,
        organization_id=access.org.organization.id,
        action="resource.update",
        target_type="resource",
        target_id=resource.id,
        detail={key: str(value) for key, value in data.items()},
    )
    session.commit()
    session.refresh(resource)
    invalidate_resource(resource.id)
    return resource_public(session, resource, access.site)


@router.get("/resources/{resource_id}/opening-rules", response_model=OpeningRulesPublic)
def read_opening_rules(
    *,
    session: SessionDep,
    access: Annotated[ResourceAccess, Depends(require_resource())],
) -> OpeningRulesPublic:
    rules = session.exec(
        select(OpeningRule)
        .where(OpeningRule.resource_id == access.resource.id)
        .order_by(OpeningRule.weekday, OpeningRule.start_time)
    ).all()
    return OpeningRulesPublic(
        data=[
            OpeningRulePublic(
                id=rule.id,
                resource_id=rule.resource_id,
                weekday=rule.weekday,
                start_time=rule.start_time,
                end_time=rule.end_time,
            )
            for rule in rules
        ]
    )


@router.post(
    "/resources/{resource_id}/opening-rules",
    response_model=OpeningRulesPublic,
)
def replace_opening_rules(
    *,
    session: SessionDep,
    access: ResourceManagerDep,
    current_user: CurrentUser,
    payload: OpeningRulesReplace,
) -> OpeningRulesPublic:
    _validate_rules(payload)
    resource_id = access.resource.id

    existing = session.exec(
        select(OpeningRule).where(OpeningRule.resource_id == resource_id)
    ).all()
    for rule in existing:
        session.delete(rule)
    session.flush()

    created: list[OpeningRule] = []
    for item in payload.rules:
        rule = OpeningRule(
            resource_id=resource_id,
            weekday=item.weekday,
            start_time=item.start_time,
            end_time=item.end_time,
        )
        session.add(rule)
        created.append(rule)

    record_audit(
        session,
        actor_id=current_user.id,
        organization_id=access.org.organization.id,
        action="resource.replace_opening_rules",
        target_type="resource",
        target_id=resource_id,
        detail={"rule_count": len(created)},
    )
    session.commit()
    invalidate_resource(resource_id)
    for rule in created:
        session.refresh(rule)
    return OpeningRulesPublic(
        data=[
            OpeningRulePublic(
                id=rule.id,
                resource_id=rule.resource_id,
                weekday=rule.weekday,
                start_time=rule.start_time,
                end_time=rule.end_time,
            )
            for rule in created
        ]
    )


@router.get("/resources/{resource_id}/blackouts", response_model=list[BlackoutPublic])
def read_blackouts(
    *,
    session: SessionDep,
    access: Annotated[ResourceAccess, Depends(require_resource())],
) -> list[BlackoutPublic]:
    rows = session.exec(
        select(ResourceBlackout)
        .where(ResourceBlackout.resource_id == access.resource.id)
        .order_by(ResourceBlackout.start_at)
    ).all()
    return [
        BlackoutPublic(
            id=item.id,
            resource_id=item.resource_id,
            start_at=from_db(item.start_at),
            end_at=from_db(item.end_at),
            reason=item.reason,
        )
        for item in rows
    ]


@router.post(
    "/resources/{resource_id}/blackouts",
    response_model=BlackoutPublic,
    status_code=201,
)
def create_blackout(
    *,
    session: SessionDep,
    access: ResourceManagerDep,
    current_user: CurrentUser,
    payload: BlackoutCreate,
) -> BlackoutPublic:
    start_db = to_db(payload.start_at)
    end_db = to_db(payload.end_at)
    conflicting = int(
        session.exec(
            select(func.count())
            .select_from(Reservation)
            .where(
                Reservation.resource_id == access.resource.id,
                Reservation.status == ReservationStatus.CONFIRMED.value,
                Reservation.start_at < end_db,
                Reservation.end_at > start_db,
            )
        ).one()
    )
    if conflicting > 0:
        raise api_error(
            409,
            ErrorCode.CONFLICT,
            f"There are {conflicting} reservation(s) in this window, cancel them first",
        )

    blackout = ResourceBlackout(
        resource_id=access.resource.id,
        start_at=start_db,
        end_at=end_db,
        reason=payload.reason,
    )
    session.add(blackout)

    affected = session.exec(
        select(ResourceSlot).where(
            ResourceSlot.resource_id == access.resource.id,
            ResourceSlot.start_at < end_db,
            ResourceSlot.start_at >= start_db,
        )
    ).all()
    for slot in affected:
        if slot.current_reservation_id is None:
            slot.status = SlotStatus.CLOSED.value

    record_audit(
        session,
        actor_id=current_user.id,
        organization_id=access.org.organization.id,
        action="resource.create_blackout",
        target_type="resource",
        target_id=access.resource.id,
        detail={"start_at": start_db.isoformat(), "end_at": end_db.isoformat()},
    )
    session.commit()
    session.refresh(blackout)
    invalidate_resource(access.resource.id)
    return BlackoutPublic(
        id=blackout.id,
        resource_id=blackout.resource_id,
        start_at=from_db(blackout.start_at),
        end_at=from_db(blackout.end_at),
        reason=blackout.reason,
    )


@router.get("/resources/{resource_id}/availability", response_model=AvailabilityPublic)
def read_availability(
    *,
    session: SessionDep,
    access: Annotated[ResourceAccess, Depends(require_resource())],
    on_date: date | None = Query(default=None, alias="date"),
) -> AvailabilityPublic:
    tz = get_timezone(access.site.timezone)
    day = on_date or local_now(tz).date()
    today_local = local_now(tz).date()
    last_allowed = today_local + timedelta(days=settings.BOOKING_WINDOW_DAYS)
    if day < today_local or day > last_allowed:
        raise api_error(
            422,
            ErrorCode.INVALID_REQUEST,
            "Only dates within the booking window can be queried",
        )

    key = availability_key(access.org.organization.id, access.resource.id, day)
    cached = get_availability(key)
    if cached is not None:
        return AvailabilityPublic.model_validate(cached)

    lock = lock_key(
        "availability", access.org.organization.id, access.resource.id, day.isoformat()
    )
    if acquire_lock(lock, ttl_seconds=5):
        try:
            public = build_availability(session, access.resource, access.site, day)
            set_availability(key, public.model_dump(mode="json"))
            return public
        finally:
            cache_delete(lock)

    time.sleep(0.05)
    cached = get_availability(key)
    if cached is not None:
        return AvailabilityPublic.model_validate(cached)
    return build_availability(session, access.resource, access.site, day)
