from datetime import datetime
from zoneinfo import ZoneInfo

from app.ai.mock import parse_booking_message
from app.ai.schemas import BookingOverrides
from app.ai.service import _merge_overrides, _prepare

TZ = ZoneInfo("Asia/Shanghai")


def _prepare_message(message: str, *, now: datetime | None = None):
    reference = now or datetime(2026, 10, 28, 9, 0, tzinfo=TZ)
    extraction = parse_booking_message(
        message, reference_now=reference, timezone="Asia/Shanghai"
    )
    return _prepare(
        extraction,
        now_local=reference,
        timezone="Asia/Shanghai",
        site_id=None,
    )


def test_complete_request_is_prepared_with_floor_assumption() -> None:
    result = _prepare_message(
        "帮我找明天下午能容纳8人、带投影仪的会议室，最好在二楼，开两个小时。"
    )
    assert result.response is None
    prepared = result.prepared
    assert prepared is not None
    assert prepared.party_size == 8
    assert prepared.duration_minutes == 120
    assert prepared.required_equipment == ["投影仪"]
    assert prepared.start_times[0].strftime("%H:%M") == "13:00"
    assert prepared.start_times[-1].strftime("%H:%M") == "16:00"
    assert any("楼层" in item for item in prepared.assumptions)


def test_missing_date_party_and_duration_are_reported_together() -> None:
    result = _prepare_message("帮我找会议室")
    assert result.response is not None
    assert result.response.status == "needs_clarification"
    assert set(result.response.missing_fields) == {
        "date",
        "party_size",
        "duration_minutes",
    }


def test_period_window_without_duration_needs_duration() -> None:
    result = _prepare_message("明天下午要个会议室，8个人")
    assert result.response is not None
    assert result.response.status == "needs_clarification"
    assert result.response.missing_fields == ["duration_minutes"]


def test_duration_must_be_multiple_of_slot() -> None:
    result = _prepare_message("明天下午8人开45分钟")
    assert result.response is not None
    assert result.response.missing_fields == ["duration_minutes"]
    assert "整数倍" in result.response.message


def test_duration_cannot_exceed_maximum() -> None:
    result = _prepare_message("明天下午8人开5小时")
    assert result.response is not None
    assert result.response.missing_fields == ["duration_minutes"]


def test_reverse_range_is_rejected() -> None:
    result = _prepare_message("明天下午4点到2点 8人")
    assert result.response is not None
    assert result.response.missing_fields == ["time_window_end"]
    assert "晚于" in result.response.message


def test_beyond_booking_window_is_rejected() -> None:
    result = _prepare_message("2026-12-31 下午 8人 两小时")
    assert result.response is not None
    assert result.response.missing_fields == ["date"]
    assert "14" in result.response.message


def test_non_booking_request_is_not_executed() -> None:
    result = _prepare_message("帮我取消明天下午的预约")
    assert result.response is not None
    assert result.response.status == "needs_clarification"
    assert result.response.missing_fields == ["booking_request"]


def test_default_window_is_used_when_time_is_omitted() -> None:
    result = _prepare_message("明天8个人开三小时")
    assert result.response is None
    assert result.prepared is not None
    assert result.prepared.start_times[0].strftime("%H:%M") == "09:00"
    assert any("09:00–21:00" in item for item in result.prepared.assumptions)


def test_today_window_skips_booking_lead_time() -> None:
    result = _prepare_message(
        "今天上午，4人，一小时",
        now=datetime(2026, 10, 28, 9, 0, tzinfo=TZ),
    )
    assert result.response is None
    assert result.prepared is not None
    assert result.prepared.start_times[0].strftime("%H:%M") == "09:30"
    assert any("提前量" in item for item in result.prepared.assumptions)


def test_today_past_window_is_rejected() -> None:
    result = _prepare_message(
        "今天上午9点到10点，4人",
        now=datetime(2026, 10, 28, 15, 0, tzinfo=TZ),
    )
    assert result.response is not None
    assert result.response.status == "needs_clarification"
    assert "已过" in result.response.message


def test_unsupported_resource_type_is_rejected() -> None:
    result = _prepare_message("明天下午8个人开两小时，要个工位")
    assert result.response is not None
    assert result.response.missing_fields == ["resource_type"]
    assert "仅支持会议室" in result.response.message


def test_overrides_replace_untrusted_extraction_fields() -> None:
    reference = datetime(2026, 10, 28, 9, 0, tzinfo=TZ)
    extraction = parse_booking_message(
        "明天下午8个人开两小时", reference_now=reference, timezone="Asia/Shanghai"
    )
    merged = _merge_overrides(
        extraction,
        BookingOverrides(party_size=12, required_equipment=["投影"]),
    )
    assert merged.party_size == 12
    assert merged.required_equipment == ["投影仪"]
