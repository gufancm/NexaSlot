from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.schemas import ErrorCode


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp for business logic."""
    return datetime.now(UTC)


def db_now() -> datetime:
    """Naive UTC timestamp for storage in MySQL DATETIME columns."""
    return datetime.now(UTC).replace(tzinfo=None)


def _raise_timezone_error(name: str) -> None:
    from app.core.errors import api_error

    raise api_error(
        422,
        ErrorCode.INVALID_REQUEST,
        f"Unknown timezone: {name}",
    )


def get_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError, ValueError:
        _raise_timezone_error(name)
        raise  # pragma: no cover - _raise_timezone_error always raises


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_db(value: datetime) -> datetime:
    """Convert an aware timestamp into the naive UTC form stored in MySQL."""
    return as_utc(value).replace(tzinfo=None)


def from_db(value: datetime | None) -> datetime | None:
    """Attach UTC tzinfo to a naive datetime read back from MySQL."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def local_now(tz: ZoneInfo) -> datetime:
    return datetime.now(tz)


def day_bounds_utc(tz: ZoneInfo, day: date) -> tuple[datetime, datetime]:
    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def combine_local(tz: ZoneInfo, day: date, at: time) -> datetime:
    return datetime.combine(day, at, tzinfo=tz)
