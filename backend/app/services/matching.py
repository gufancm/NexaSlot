"""Deterministic resource matching: hard filters first, explainable soft score."""

import uuid
from datetime import datetime, timedelta

from sqlmodel import Session, select

from app.core.config import settings
from app.core.time import as_utc, get_timezone, to_db
from app.models import (
    Resource,
    ResourceSlot,
    ResourceStatus,
    Site,
    SiteStatus,
    SlotStatus,
)
from app.schemas import (
    AlternativesPublic,
    ResourceMatchCandidate,
    ResourceMatchPublic,
    ResourceMatchRequest,
    SlotRange,
)
from app.services.catalog import resource_public
from app.services.orgs import OrgAccess, ResourceAccess
from app.services.slots import ensure_range_slots


def _window_is_free(
    session: Session,
    resource: Resource,
    site: Site,
    start: datetime,
    end: datetime,
) -> bool:
    ensure_range_slots(session, resource, site, start, end)
    slots = list(
        session.exec(
            select(ResourceSlot).where(
                ResourceSlot.resource_id == resource.id,
                ResourceSlot.start_at >= to_db(start),
                ResourceSlot.start_at < to_db(end),
            )
        ).all()
    )
    expected = int((end - start).total_seconds() // 60 // settings.BOOKING_SLOT_MINUTES)
    if len(slots) != expected or not slots:
        return False
    return all(
        slot.status == SlotStatus.OPEN.value
        and slot.current_reservation_id is None
        and slot.current_hold_id is None
        for slot in slots
    )


def _site_of(session: Session, resource: Resource) -> Site | None:
    return session.get(Site, resource.site_id)


def _score(
    *,
    resource: Resource,
    party_size: int,
    preferred_site_id: uuid.UUID | None,
    window_requested: bool,
    start: datetime | None,
    site: Site,
) -> tuple[float, list[str]]:
    capacity_fit = 1.0 - min(
        1.0, max(0.0, (resource.capacity - party_size) / max(resource.capacity, 1))
    )
    if preferred_site_id is None:
        site_fit = 0.5
    else:
        site_fit = 1.0 if resource.site_id == preferred_site_id else 0.0
    window_fit = 1.0 if window_requested else 0.5

    score = (
        settings.MATCH_WEIGHT_CAPACITY * capacity_fit
        + settings.MATCH_WEIGHT_SITE * site_fit
        + settings.MATCH_WEIGHT_WINDOW * window_fit
    ) * 100

    reasons = [f"容量 {resource.capacity} 人，满足 {party_size} 人需求"]
    if preferred_site_id is not None and resource.site_id == preferred_site_id:
        reasons.append(f"位于偏好场地 {site.name}")
    if window_requested and start is not None:
        reasons.append("所选时段完全空闲")
    else:
        reasons.append("未指定时间，仅按条件推荐")
    return round(score, 2), reasons


def match_resources(
    *, session: Session, org: OrgAccess, request: ResourceMatchRequest
) -> ResourceMatchPublic:
    site_ids = list(
        session.exec(
            select(Site.id).where(
                Site.organization_id == org.organization.id,
                Site.status == SiteStatus.ACTIVE.value,
            )
        ).all()
    )
    if not site_ids:
        return ResourceMatchPublic(data=[], count=0, window_requested=False)

    statement = select(Resource).where(
        Resource.site_id.in_(site_ids),
        Resource.status == ResourceStatus.ACTIVE.value,
        Resource.capacity >= request.party_size,
    )
    resources = list(session.exec(statement).all())

    required = [item.strip() for item in request.required_features if item.strip()]
    candidates: list[ResourceMatchCandidate] = []
    window_requested = request.start_at is not None and request.end_at is not None
    start = as_utc(request.start_at) if request.start_at else None
    end = as_utc(request.end_at) if request.end_at else None
    if start and end and request.duration_minutes is not None:
        actual = int((end - start).total_seconds() // 60)
        if actual != request.duration_minutes:
            start = None
            end = None
            window_requested = False

    for resource in resources:
        if required and not set(required).issubset(set(resource.features or [])):
            continue
        site = _site_of(session, resource)
        if site is None:
            continue
        if window_requested and start and end:
            if not _window_is_free(session, resource, site, start, end):
                continue
        score, reasons = _score(
            resource=resource,
            party_size=request.party_size,
            preferred_site_id=request.preferred_site_id,
            window_requested=window_requested,
            start=start,
            site=site,
        )
        if required:
            reasons.append("满足必需设备：" + "、".join(required))
        candidates.append(
            ResourceMatchCandidate(
                resource=resource_public(session, resource, site),
                score=score,
                reasons=reasons,
                available=True,
            )
        )

    candidates.sort(
        key=lambda item: (-item.score, item.resource.name, str(item.resource.id))
    )
    limited = candidates[: request.limit]
    return ResourceMatchPublic(
        data=limited, count=len(limited), window_requested=window_requested
    )


def alternatives_for_resource(
    *, session: Session, access: ResourceAccess, start: datetime, end: datetime
) -> AlternativesPublic:
    resource = access.resource
    site = access.site
    tz = get_timezone(site.timezone)
    local_start = start.astimezone(tz)
    duration = end - start

    windows: list[SlotRange] = []
    for offset in range(1, settings.BOOKING_WINDOW_DAYS + 1):
        candidate_start = (local_start + timedelta(days=offset)).astimezone(tz)
        candidate_end = candidate_start + duration
        candidate_start_utc = candidate_start.astimezone(tz)
        candidate_end_utc = candidate_end.astimezone(tz)
        if _window_is_free(
            session, resource, site, candidate_start_utc, candidate_end_utc
        ):
            windows.append(
                SlotRange(start_at=candidate_start_utc, end_at=candidate_end_utc)
            )
        if len(windows) >= 3:
            break

    site_ids = list(
        session.exec(
            select(Site.id).where(
                Site.organization_id == site.organization_id,
                Site.status == SiteStatus.ACTIVE.value,
            )
        ).all()
    )
    others: list[ResourceMatchCandidate] = []
    if site_ids:
        rows = session.exec(
            select(Resource).where(
                Resource.site_id.in_(site_ids),
                Resource.status == ResourceStatus.ACTIVE.value,
                Resource.id != resource.id,
            )
        ).all()
        for item in rows:
            other_site = _site_of(session, item)
            if other_site is None:
                continue
            if not _window_is_free(session, item, other_site, start, end):
                continue
            similarity = 1.0 - abs(item.capacity - resource.capacity) / max(
                item.capacity, resource.capacity, 1
            )
            others.append(
                ResourceMatchCandidate(
                    resource=resource_public(session, item, other_site),
                    score=round(similarity * 100, 2),
                    reasons=[
                        f"同一组织内可用，容量 {item.capacity} 人"
                        + (
                            f"，设备：{'、'.join(item.features)}"
                            if item.features
                            else ""
                        )
                    ],
                    available=True,
                )
            )
    others.sort(
        key=lambda item: (-item.score, item.resource.name, str(item.resource.id))
    )
    return AlternativesPublic(
        resource_id=resource.id,
        same_resource_windows=windows,
        other_resources=others[:5],
    )
