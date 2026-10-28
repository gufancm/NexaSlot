"""V3 Lite orchestration: parse -> validate -> reuse V2 matching.

The LLM never touches the database. This service resolves trusted tenant and
site context, validates the untrusted extraction, asks the deterministic V2
matcher for concrete free windows, and returns read-only suggestions.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlmodel import Session, select

from app.ai.client import LLMClient, LLMUnavailableError
from app.ai.equipment import canonicalize_equipment, resource_satisfies
from app.ai.schemas import (
    AIRecommendPublic,
    AIRecommendRequest,
    BookingExtraction,
    BookingOverrides,
    BookingSuggestion,
    InterpretedBooking,
)
from app.core.config import settings
from app.core.errors import api_error
from app.core.time import get_timezone, utcnow
from app.models import Site, SiteStatus
from app.schemas import ErrorCode, ResourceMatchRequest
from app.services.matching import match_resources
from app.services.orgs import OrgAccess

MAX_SUGGESTIONS = 6
MAX_WINDOWS_PER_RESOURCE = 2
MAX_WINDOW_STARTS = 48

FIELD_LABELS = {
    "booking_request": "预约需求",
    "resource_type": "资源类型",
    "date": "日期",
    "party_size": "人数",
    "duration_minutes": "时长",
    "time_window_start": "开始时间",
    "time_window_end": "结束时间",
    "site_id": "场地",
}

PERIOD_WINDOW_HINTS = {
    (8, 0, 10, 0),
    (9, 0, 12, 0),
    (11, 30, 14, 0),
    (13, 0, 18, 0),
    (17, 0, 20, 0),
    (18, 0, 21, 0),
}


@dataclass
class PreparedBooking:
    booking_date: date
    window_start: time
    window_end: time
    duration_minutes: int
    party_size: int
    required_equipment: list[str]
    preferred_floor: int | None
    site_id: uuid.UUID | None
    timezone: str
    start_times: list[datetime]
    assumptions: list[str]


@dataclass
class Preparation:
    prepared: PreparedBooking | None = None
    response: AIRecommendPublic | None = None


def _clarification(
    interpreted: InterpretedBooking,
    missing: list[str],
    message: str | None = None,
    assumptions: list[str] | None = None,
) -> AIRecommendPublic:
    labels = [FIELD_LABELS.get(item, item) for item in missing]
    text = message or ("我还需要了解：" + "、".join(labels) + "。")
    return AIRecommendPublic(
        status="needs_clarification",
        message=text,
        interpreted=interpreted,
        missing_fields=missing,
        assumptions=assumptions or [],
    )


def _unavailable(
    interpreted: InterpretedBooking | None = None,
    message: str = "智能助手暂时不可用，请使用手动预约入口，原有预约功能不受影响。",
) -> AIRecommendPublic:
    return AIRecommendPublic(
        status="unavailable",
        message=message,
        interpreted=interpreted or InterpretedBooking(),
    )


def _normalize_equipment(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        canonical = canonicalize_equipment(value)
        candidates = canonical or ([value.strip()] if value.strip() else [])
        for item in candidates:
            if item not in normalized:
                normalized.append(item)
    return normalized[:10]


def _merge_overrides(
    extraction: BookingExtraction, overrides: BookingOverrides | None
) -> BookingExtraction:
    if overrides is None:
        return extraction.model_copy(
            update={
                "required_equipment": _normalize_equipment(
                    extraction.required_equipment
                )
            }
        )
    updates: dict[str, object] = {}
    for field in (
        "date",
        "time_window_start",
        "time_window_end",
        "duration_minutes",
        "party_size",
        "preferred_floor",
    ):
        value = getattr(overrides, field)
        if value is not None:
            updates[field] = value
    if overrides.required_equipment is not None:
        updates["required_equipment"] = _normalize_equipment(
            overrides.required_equipment
        )
    else:
        updates["required_equipment"] = _normalize_equipment(
            extraction.required_equipment
        )
    return extraction.model_copy(update=updates)


def _interpreted(
    extraction: BookingExtraction,
    *,
    site_id: uuid.UUID | None,
    timezone: str | None,
) -> InterpretedBooking:
    return InterpretedBooking(
        resource_type=extraction.resource_type,
        date=extraction.date,
        time_window_start=extraction.time_window_start,
        time_window_end=extraction.time_window_end,
        duration_minutes=extraction.duration_minutes,
        party_size=extraction.party_size,
        required_equipment=extraction.required_equipment,
        preferred_floor=extraction.preferred_floor,
        site_id=site_id,
        timezone=timezone,
    )


def _prepare(
    extraction: BookingExtraction,
    *,
    now_local: datetime,
    timezone: str,
    site_id: uuid.UUID | None,
) -> Preparation:
    assumptions: list[str] = []
    interpreted = _interpreted(extraction, site_id=site_id, timezone=timezone)

    if not extraction.is_booking_request:
        return Preparation(
            response=_clarification(
                interpreted,
                ["booking_request"],
                message="这看起来不是资源预约需求。我可以帮你查找并预约会议室，取消或查询订单请使用对应页面。",
            )
        )

    resource_type = extraction.resource_type
    if resource_type is None:
        resource_type = "MEETING_ROOM"
        assumptions.append("当前版本默认按会议室类型搜索。")
    elif resource_type.upper() in {"MEETING_ROOM", "MEETINGROOM", "会议室"}:
        resource_type = "MEETING_ROOM"
    else:
        return Preparation(
            response=_clarification(
                interpreted,
                ["resource_type"],
                message=f"当前版本仅支持会议室预约，暂不支持“{resource_type}”。",
            )
        )
    interpreted.resource_type = resource_type

    missing: list[str] = []
    if extraction.date is None:
        missing.append("date")
    if extraction.party_size is None:
        missing.append("party_size")
    if (
        extraction.duration_minutes is None
        and extraction.time_window_start is None
        and extraction.time_window_end is None
    ):
        missing.append("duration_minutes")
    if missing:
        return Preparation(response=_clarification(interpreted, missing))

    if extraction.date is None:
        interpreted.date = None
        return Preparation(response=_clarification(interpreted, ["date"]))

    today = now_local.date()
    if extraction.date < today:
        return Preparation(
            response=_clarification(
                interpreted,
                ["date"],
                message="预约日期已经过去，请提供今天或未来的日期。",
            )
        )
    if (extraction.date - today).days > settings.BOOKING_WINDOW_DAYS:
        return Preparation(
            response=_clarification(
                interpreted,
                ["date"],
                message=f"只能预约未来 {settings.BOOKING_WINDOW_DAYS} 天内的时段，请调整日期。",
            )
        )

    if extraction.party_size is None:
        return Preparation(response=_clarification(interpreted, ["party_size"]))
    if extraction.party_size < 1 or extraction.party_size > 10000:
        return Preparation(
            response=_clarification(
                interpreted,
                ["party_size"],
                message="人数需在 1–10000 之间，请重新填写。",
            )
        )

    duration = extraction.duration_minutes
    if duration is not None and (
        duration < settings.BOOKING_SLOT_MINUTES
        or duration > settings.BOOKING_MAX_DURATION_MINUTES
        or duration % settings.BOOKING_SLOT_MINUTES != 0
    ):
        return Preparation(
            response=_clarification(
                interpreted,
                ["duration_minutes"],
                message=(
                    f"时长需在 {settings.BOOKING_SLOT_MINUTES}–"
                    f"{settings.BOOKING_MAX_DURATION_MINUTES} 分钟之间，"
                    f"且为 {settings.BOOKING_SLOT_MINUTES} 分钟的整数倍。"
                ),
            )
        )

    start = extraction.time_window_start
    end = extraction.time_window_end
    if start is None and end is None:
        if duration is None:
            assumptions.append("未指定时段，搜索范围默认为 09:00–21:00。")
            return Preparation(
                response=_clarification(interpreted, ["duration_minutes"])
            )
        start = time(9, 0)
        end = time(21, 0)
        assumptions.append("未指定时段，已按 09:00–21:00 搜索。")
    elif start is not None and end is None:
        if duration is None:
            return Preparation(
                response=_clarification(interpreted, ["duration_minutes"])
            )
        total = start.hour * 60 + start.minute + duration
        if total >= 24 * 60:
            return Preparation(
                response=_clarification(
                    interpreted,
                    ["time_window_end"],
                    message="当前版本不支持跨日预约，请调整开始时间或时长。",
                )
            )
        end = time(total // 60, total % 60)
    elif start is None and end is not None:
        return Preparation(response=_clarification(interpreted, ["time_window_start"]))

    assert start is not None and end is not None
    start_minutes = start.hour * 60 + start.minute
    end_minutes = end.hour * 60 + end.minute
    if end_minutes <= start_minutes:
        return Preparation(
            response=_clarification(
                interpreted,
                ["time_window_end"],
                message="结束时间必须晚于开始时间，请重新填写时间窗口。",
            )
        )

    window_minutes = end_minutes - start_minutes
    if duration is None:
        if (start.hour, start.minute, end.hour, end.minute) in PERIOD_WINDOW_HINTS:
            assumptions.append("已将口语时段转换为明确的搜索窗口。")
            return Preparation(
                response=_clarification(interpreted, ["duration_minutes"])
            )
        duration = window_minutes
    if duration > window_minutes:
        return Preparation(
            response=_clarification(
                interpreted,
                ["duration_minutes"],
                message="预约时长超过了所选时间窗口，请调整时长或时间范围。",
            )
        )
    if duration > settings.BOOKING_MAX_DURATION_MINUTES:
        return Preparation(
            response=_clarification(
                interpreted,
                ["duration_minutes"],
                message=f"单次预约最长 {settings.BOOKING_MAX_DURATION_MINUTES} 分钟。",
            )
        )
    if (
        start.second != 0
        or end.second != 0
        or start.minute % settings.BOOKING_SLOT_MINUTES != 0
        or end.minute % settings.BOOKING_SLOT_MINUTES != 0
    ):
        return Preparation(
            response=_clarification(
                interpreted,
                ["time_window_start", "time_window_end"],
                message=f"时间范围需对齐到 {settings.BOOKING_SLOT_MINUTES} 分钟。",
            )
        )

    interpreted.time_window_start = start
    interpreted.time_window_end = end
    interpreted.duration_minutes = duration
    if extraction.preferred_floor is not None:
        assumptions.append(
            f"当前资源未记录楼层，{extraction.preferred_floor} 楼偏好未参与筛选。"
        )

    tz = get_timezone(timezone)
    first_local = datetime.combine(extraction.date, start, tzinfo=tz)
    last_local = datetime.combine(extraction.date, end, tzinfo=tz) - timedelta(
        minutes=duration
    )
    now_utc = utcnow()
    horizon_utc = now_utc + timedelta(days=settings.BOOKING_WINDOW_DAYS)
    cutoff = now_local + timedelta(minutes=settings.BOOKING_MIN_LEAD_MINUTES)

    starts: list[datetime] = []
    skipped_for_lead = False
    current = first_local
    while current <= last_local and len(starts) < MAX_WINDOW_STARTS:
        if current < cutoff:
            skipped_for_lead = True
        else:
            start_utc = current.astimezone(UTC)
            end_utc = start_utc + timedelta(minutes=duration)
            if end_utc <= horizon_utc:
                starts.append(current)
        current += timedelta(minutes=settings.BOOKING_SLOT_MINUTES)

    if skipped_for_lead:
        assumptions.append(
            f"今天的开始时间已跳过 {settings.BOOKING_MIN_LEAD_MINUTES} 分钟预约提前量。"
        )
    if not starts:
        if extraction.date == today and last_local < cutoff:
            message = "今天的可选时段已过，请选择明天或更晚的日期。"
        else:
            message = "该时间窗口内没有足够的可预约开始时间，请调整时间或时长。"
        return Preparation(
            response=_clarification(
                interpreted, [], message=message, assumptions=assumptions
            )
        )

    return Preparation(
        prepared=PreparedBooking(
            booking_date=extraction.date,
            window_start=start,
            window_end=end,
            duration_minutes=duration,
            party_size=extraction.party_size,
            required_equipment=extraction.required_equipment,
            preferred_floor=extraction.preferred_floor,
            site_id=site_id,
            timezone=timezone,
            start_times=starts,
            assumptions=assumptions,
        )
    )


def _search_suggestions(
    *,
    session: Session,
    org: OrgAccess,
    prepared: PreparedBooking,
    sites: list[Site],
) -> list[BookingSuggestion]:
    sites_by_id = {site.id: site for site in sites}
    inferred_duration = timedelta(minutes=prepared.duration_minutes)
    per_resource: dict[uuid.UUID, list[BookingSuggestion]] = {}

    for start_local in prepared.start_times:
        start_utc = start_local.astimezone(UTC)
        end_utc = start_utc + inferred_duration
        request = ResourceMatchRequest(
            org_id=org.organization.id,
            party_size=prepared.party_size,
            start_at=start_utc,
            end_at=end_utc,
            duration_minutes=prepared.duration_minutes,
            required_features=[],
            preferred_site_id=prepared.site_id,
            limit=20,
        )
        result = match_resources(session=session, org=org, request=request)
        for candidate in result.data:
            resource = candidate.resource
            if not resource_satisfies(resource.features, prepared.required_equipment):
                continue
            entries = per_resource.setdefault(resource.id, [])
            if len(entries) >= MAX_WINDOWS_PER_RESOURCE:
                continue
            if any(item.start_at == start_utc for item in entries):
                continue
            site = sites_by_id.get(resource.site_id)
            location = resource.site_name
            if site is not None:
                location = site.name
                if site.address:
                    location = f"{site.name} · {site.address}"

            reasons = [
                f"容量 {resource.capacity} 人，满足 {prepared.party_size} 人需求"
            ]
            if prepared.required_equipment:
                reasons.append(
                    "满足设备要求：" + "、".join(prepared.required_equipment)
                )
            if prepared.site_id == resource.site_id:
                reasons.append(f"位于所选场地 {resource.site_name}")
            reasons.append(
                "该时段当前空闲（"
                + start_local.strftime("%H:%M")
                + "–"
                + (start_local + inferred_duration).strftime("%H:%M")
                + "）"
            )
            entries.append(
                BookingSuggestion(
                    resource_id=resource.id,
                    resource_name=resource.name,
                    start_at=start_utc,
                    end_at=end_utc,
                    capacity=resource.capacity,
                    equipment=list(resource.features),
                    location=location,
                    timezone=prepared.timezone,
                    score=candidate.score,
                    reason="；".join(reasons),
                )
            )

    flattened = [item for entries in per_resource.values() for item in entries]
    flattened.sort(
        key=lambda item: (
            -item.score,
            item.start_at,
            item.resource_name,
            str(item.resource_id),
        )
    )
    return flattened[:MAX_SUGGESTIONS]


def recommend_booking(
    *,
    session: Session,
    org: OrgAccess,
    request: AIRecommendRequest,
    client: LLMClient | None,
) -> AIRecommendPublic:
    sites = list(
        session.exec(
            select(Site).where(
                Site.organization_id == org.organization.id,
                Site.status == SiteStatus.ACTIVE.value,
            )
        ).all()
    )
    selected_site: Site | None = None
    if request.site_id is not None:
        selected_site = next(
            (site for site in sites if site.id == request.site_id), None
        )
        if selected_site is None:
            raise api_error(
                403,
                ErrorCode.FORBIDDEN,
                "The selected site is not available in this organization",
            )

    if not sites:
        return AIRecommendPublic(
            status="no_results",
            message="组织中还没有可用场地，请先让管理员创建场地与资源。",
        )

    if selected_site is not None:
        timezone = selected_site.timezone
    else:
        timezones = {site.timezone for site in sites}
        if len(timezones) > 1:
            return _clarification(
                InterpretedBooking(),
                ["site_id"],
                message="组织内存在多个时区，请先选择场地后再使用智能预约。",
            )
        timezone = next(iter(timezones))

    if client is None:
        return _unavailable()

    tz = get_timezone(timezone)
    now_local = utcnow().astimezone(tz)
    try:
        extraction = client.extract(
            request.message, reference_now=now_local, timezone=timezone
        )
    except LLMUnavailableError:
        return _unavailable()

    extraction = _merge_overrides(extraction, request.overrides)
    preparation = _prepare(
        extraction,
        now_local=now_local,
        timezone=timezone,
        site_id=request.site_id,
    )
    if preparation.response is not None:
        return preparation.response
    assert preparation.prepared is not None
    prepared = preparation.prepared

    suggestions = _search_suggestions(
        session=session, org=org, prepared=prepared, sites=sites
    )
    interpreted = InterpretedBooking(
        resource_type="MEETING_ROOM",
        date=prepared.booking_date,
        time_window_start=prepared.window_start,
        time_window_end=prepared.window_end,
        duration_minutes=prepared.duration_minutes,
        party_size=prepared.party_size,
        required_equipment=prepared.required_equipment,
        preferred_floor=prepared.preferred_floor,
        site_id=prepared.site_id,
        timezone=prepared.timezone,
    )
    if not suggestions:
        return AIRecommendPublic(
            status="no_results",
            message="没有找到同时满足人数、设备且在该时段空闲的资源，请放宽条件或使用手动预约。",
            interpreted=interpreted,
            assumptions=prepared.assumptions,
        )

    return AIRecommendPublic(
        status="suggestions",
        message=(
            f"找到 {len(suggestions)} 个可用方案。查询时可用，最终以提交结果为准。"
        ),
        interpreted=interpreted,
        assumptions=prepared.assumptions,
        suggestions=suggestions,
    )
