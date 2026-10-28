from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlmodel import Session, select

from app.core.config import settings
from app.core.time import (
    combine_local,
    day_bounds_utc,
    from_db,
    get_timezone,
    to_db,
    utcnow,
)
from app.models import (
    OpeningRule,
    Resource,
    ResourceBlackout,
    ResourceSlot,
    Site,
    SlotStatus,
)
from app.schemas import AvailabilityPublic, SlotPublic

SLOT_MINUTES = settings.BOOKING_SLOT_MINUTES
SLOT_DELTA = timedelta(minutes=SLOT_MINUTES)


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _ceil_to_slot(minutes: int) -> int:
    remainder = minutes % SLOT_MINUTES
    return minutes if remainder == 0 else minutes + (SLOT_MINUTES - remainder)


def _floor_to_slot(minutes: int) -> int:
    return minutes - (minutes % SLOT_MINUTES)


def _slot_starts_for_rule(rule: OpeningRule) -> list[time]:
    start_min = _ceil_to_slot(_minutes(rule.start_time))
    end_min = _floor_to_slot(_minutes(rule.end_time))
    return [
        time(hour=minute // 60, minute=minute % 60)
        for minute in range(start_min, end_min, SLOT_MINUTES)
    ]


def _free_slots_for_day(
    session: Session, resource: Resource, site: Site, day: date
) -> list[tuple[datetime, datetime, str]]:
    """Return the expected (start_utc, end_utc, status) tuples for one local day."""
    tz = get_timezone(site.timezone)
    rules = session.exec(
        select(OpeningRule).where(
            OpeningRule.resource_id == resource.id,
            OpeningRule.weekday == day.weekday(),
        )
    ).all()
    if not rules:
        return []

    day_start_utc, day_end_utc = day_bounds_utc(tz, day)
    blackouts = session.exec(
        select(ResourceBlackout).where(
            ResourceBlackout.resource_id == resource.id,
            ResourceBlackout.start_at < to_db(day_end_utc),
            ResourceBlackout.end_at > to_db(day_start_utc),
        )
    ).all()
    blackout_ranges = [(to_db(item.start_at), to_db(item.end_at)) for item in blackouts]

    expected: dict[datetime, tuple[datetime, str]] = {}
    for rule in rules:
        for slot_time in _slot_starts_for_rule(rule):
            start_utc = combine_local(tz, day, slot_time).astimezone(UTC)
            end_utc = start_utc + SLOT_DELTA
            start_db, end_db = to_db(start_utc), to_db(end_utc)
            if end_db > to_db(day_end_utc):
                continue
            covered = any(
                start_db < blackout_end and blackout_start < end_db
                for blackout_start, blackout_end in blackout_ranges
            )
            status = SlotStatus.CLOSED if covered else SlotStatus.OPEN
            expected[start_db] = (end_db, status.value)

    return [
        (start_db.replace(tzinfo=UTC), end_db.replace(tzinfo=UTC), status)
        for start_db, (end_db, status) in sorted(expected.items())
    ]


def ensure_day_slots(
    session: Session, resource: Resource, site: Site, day: date
) -> list[ResourceSlot]:
    """Materialise time slots for a local day. Safe to call repeatedly."""
    expected = _free_slots_for_day(session, resource, site, day)
    tz = get_timezone(site.timezone)
    day_start_utc, day_end_utc = day_bounds_utc(tz, day)
    start_db, end_db = to_db(day_start_utc), to_db(day_end_utc)

    existing = session.exec(
        select(ResourceSlot).where(
            ResourceSlot.resource_id == resource.id,
            ResourceSlot.start_at >= start_db,
            ResourceSlot.start_at < end_db,
        )
    ).all()
    existing_by_start = {slot.start_at: slot for slot in existing}

    missing_rows: list[dict] = []
    for start_utc, end_utc, status in expected:
        start_db_value = to_db(start_utc)
        if start_db_value in existing_by_start:
            continue
        missing_rows.append(
            {
                "resource_id": resource.id,
                "start_at": start_db_value,
                "end_at": to_db(end_utc),
                "status": status,
                "current_reservation_id": None,
            }
        )

    if missing_rows:
        statement = (
            mysql_insert(ResourceSlot.__table__)
            .values(missing_rows)
            .prefix_with("IGNORE")
        )
        session.execute(statement)
        session.commit()
        existing = session.exec(
            select(ResourceSlot).where(
                ResourceSlot.resource_id == resource.id,
                ResourceSlot.start_at >= start_db,
                ResourceSlot.start_at < end_db,
            )
        ).all()
        existing_by_start = {slot.start_at: slot for slot in existing}

    expected_status = {to_db(start): status for start, _, status in expected}
    dirty = False
    for slot in existing:
        new_status = expected_status.get(slot.start_at, SlotStatus.CLOSED.value)
        if slot.current_reservation_id is None and slot.status != new_status:
            slot.status = new_status
            dirty = True
    if dirty:
        session.commit()

    return sorted(existing, key=lambda item: item.start_at)


def ensure_range_slots(
    session: Session,
    resource: Resource,
    site: Site,
    start_utc: datetime,
    end_utc: datetime,
) -> None:
    tz = get_timezone(site.timezone)
    current = start_utc.astimezone(tz).date()
    last = (end_utc - timedelta(seconds=1)).astimezone(tz).date()
    while current <= last:
        ensure_day_slots(session, resource, site, current)
        current += timedelta(days=1)


def build_availability(
    session: Session, resource: Resource, site: Site, day: date
) -> AvailabilityPublic:
    slots = ensure_day_slots(session, resource, site, day)
    now = utcnow()
    items: list[SlotPublic] = []
    for slot in slots:
        start_at = from_db(slot.start_at)
        end_at = from_db(slot.end_at)
        assert start_at is not None and end_at is not None
        if end_at <= now:
            state = "PAST"
        elif slot.current_reservation_id is not None:
            state = "BOOKED"
        elif slot.status != SlotStatus.OPEN.value:
            state = "CLOSED"
        else:
            state = "AVAILABLE"
        items.append(
            SlotPublic(
                start_at=start_at,
                end_at=end_at,
                state=state,
                reservation_id=slot.current_reservation_id,
            )
        )
    return AvailabilityPublic(
        resource_id=resource.id,
        date=day,
        timezone=site.timezone,
        slot_minutes=SLOT_MINUTES,
        slots=items,
    )
