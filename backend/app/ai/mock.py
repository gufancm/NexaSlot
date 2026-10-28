"""Deterministic Chinese rule parser used as the local LLM substitute.

It intentionally implements the same contract as a real provider: a single
sentence in, an untrusted ``BookingExtraction`` out. Business validation and
database lookups remain in ``app.ai.service``.
"""

import re
from datetime import date, datetime, time, timedelta

from app.ai.equipment import canonicalize_equipment
from app.ai.schemas import BookingExtraction

_TRANSLATION = str.maketrans(
    {
        "０": "0",
        "１": "1",
        "２": "2",
        "３": "3",
        "４": "4",
        "５": "5",
        "６": "6",
        "７": "7",
        "８": "8",
        "９": "9",
        "：": ":",
        "－": "-",
        "～": "~",
        "兩": "两",
        "個": "个",
        "帶": "带",
        "開": "开",
        "點": "点",
        "樓": "楼",
        "層": "层",
        "時": "时",
        "間": "间",
        "會": "会",
        "議": "议",
        "預": "预",
        "約": "约",
        "幫": "帮",
        "嗎": "吗",
        "鐘": "钟",
        "頭": "头",
        "腦": "脑",
    }
)

_CN_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CN_NUMBER = r"[0-9]+|[零一二两三四五六七八九十]+"

_PERIOD_WINDOWS: tuple[tuple[str, tuple[int, int, int, int]], ...] = (
    ("中午", (11, 30, 14, 0)),
    ("上午", (9, 0, 12, 0)),
    ("早上", (9, 0, 12, 0)),
    ("清晨", (8, 0, 10, 0)),
    ("下午", (13, 0, 18, 0)),
    ("傍晚", (17, 0, 20, 0)),
    ("晚上", (18, 0, 21, 0)),
)

_NON_BOOKING_MARKERS = (
    "取消",
    "查订单",
    "订单状态",
    "我的预约",
    "天气",
    "密码",
    "你是谁",
    "翻译",
    "写代码",
    "笑话",
)
_BOOKING_MARKERS = (
    "预约",
    "预订",
    "订",
    "会议室",
    "开会",
    "会议",
    "上午",
    "下午",
    "中午",
    "傍晚",
    "晚上",
    "早上",
    "明天",
    "今天",
    "后天",
    "周",
    "星期",
    "点",
    "小时",
    "分钟",
    "人",
)
_UNSUPPORTED_TYPES = ("工位", "车位", "教室", "直播间", "球场", "餐厅")


def normalize_text(value: str) -> str:
    text = value.translate(_TRANSLATION).replace("\u200b", "").lower()
    return re.sub(r"[ \t\r\n]+", " ", text).strip()


def _strip_identifiers(text: str) -> str:
    """Remove model-supplied ids before date/time parsing.

    A UUID can contain digit-hyphen-digit substrings (for example ``6-7``)
    that would otherwise look like a time range.
    """
    text = re.sub(r"\b(?:resource|org|site|user)_id\s*=\s*[0-9a-f-]{8,}", " ", text)
    text = re.sub(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        " ",
        text,
    )
    return text


def _cn_to_int(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    if not value:
        return None
    if "十" in value:
        left, _, right = value.partition("十")
        tens = _CN_DIGITS.get(left, 1) if left else 1
        ones = _CN_DIGITS.get(right, 0) if right else 0
        if left and left not in _CN_DIGITS:
            return None
        if right and right not in _CN_DIGITS:
            return None
        return tens * 10 + ones
    if len(value) == 1:
        return _CN_DIGITS.get(value)
    return None


def _strip_date_fragments(text: str) -> str:
    patterns = (
        r"\d{4}\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2}\s*[日号]?",
        r"\d{1,2}\s*月\s*\d{1,2}\s*[日号]",
    )
    for pattern in patterns:
        text = re.sub(pattern, " ", text)
    return text


def _extract_date(
    text: str, today: date
) -> tuple[date | None, tuple[int, int, int, int] | None]:
    iso = re.search(r"(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})", text)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3))), None
        except ValueError:
            return None, None

    month_day = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", text)
    if month_day:
        month, day = int(month_day.group(1)), int(month_day.group(2))
        for year in (today.year, today.year + 1):
            try:
                candidate = date(year, month, day)
            except ValueError:
                return None, None
            if candidate >= today:
                return candidate, None
        return None, None

    hint: tuple[int, int, int, int] | None = None
    if "大后天" in text:
        return today + timedelta(days=3), None
    if "后天" in text:
        return today + timedelta(days=2), None
    if "明早" in text or "明日早" in text:
        return today + timedelta(days=1), (9, 0, 12, 0)
    if "明晚" in text:
        return today + timedelta(days=1), (18, 0, 21, 0)
    if "明天" in text or "明日" in text:
        return today + timedelta(days=1), None
    if "今晚" in text:
        return today, (18, 0, 21, 0)
    if "今天" in text or "今日" in text:
        return today, None

    weekday = re.search(r"(下|本|这)?\s*(?:周|星期)([一二三四五六日天])", text)
    if weekday:
        qualifier = weekday.group(1) or ""
        target = "一二三四五六日".index(
            "日" if weekday.group(2) == "天" else weekday.group(2)
        )
        monday = today - timedelta(days=today.weekday())
        if qualifier == "下":
            return monday + timedelta(days=7 + target), hint
        if qualifier in ("本", "这"):
            candidate = monday + timedelta(days=target)
            if candidate < today:
                candidate += timedelta(days=7)
            return candidate, hint
        delta = (target - today.weekday()) % 7
        return today + timedelta(days=delta), hint

    return None, hint


def _extract_period(text: str) -> tuple[int, int, int, int] | None:
    if "上午" in text or "早上" in text:
        return (9, 0, 12, 0)
    for keyword, window in _PERIOD_WINDOWS:
        if keyword in text:
            return window
    return None


def _apply_period(hour: int, period: tuple[int, int, int, int] | None) -> int:
    if period is None:
        return hour
    if period[0] >= 12 and hour < 12:
        return hour + 12
    return hour


def _extract_range(
    text: str, period: tuple[int, int, int, int] | None
) -> tuple[int, int] | None:
    match = re.search(
        rf"(?<![\d:-])(?P<sh>{_CN_NUMBER})\s*"
        rf"(?:(?P<sc>[:：])(?P<sm>\d{{1,2}}))?\s*(?:点|时)?\s*"
        rf"(?P<shalf>半)?\s*(?:到|至|-|~)\s*"
        rf"(?P<eh>{_CN_NUMBER})\s*"
        rf"(?:(?P<ec>[:：])(?P<em>\d{{1,2}}))?\s*(?:点|时)?\s*"
        rf"(?P<ehalf>半)?",
        text,
    )
    if not match:
        return None
    start_hour = _cn_to_int(match.group("sh"))
    end_hour = _cn_to_int(match.group("eh"))
    if start_hour is None or end_hour is None:
        return None
    start_minute = 30 if match.group("shalf") else 0
    end_minute = 30 if match.group("ehalf") else 0
    if match.group("sm"):
        start_minute = int(match.group("sm"))
    if match.group("em"):
        end_minute = int(match.group("em"))
    start_hour = _apply_period(start_hour, period)
    end_hour = _apply_period(end_hour, period)
    if start_hour > 23 or end_hour > 23 or start_minute > 59 or end_minute > 59:
        return None
    return start_hour * 60 + start_minute, end_hour * 60 + end_minute


def _extract_start(
    text: str, period: tuple[int, int, int, int] | None
) -> tuple[int, int] | None:
    match = re.search(
        rf"(?<![\d:-])(?P<hour>{_CN_NUMBER})\s*"
        rf"(?:(?P<colon>[:：])(?P<minute>\d{{1,2}})"
        rf"|(?:点|时(?!间|长|段|候))\s*(?P<half>半)?)",
        text,
    )
    if not match:
        return None
    hour = _cn_to_int(match.group("hour"))
    if hour is None:
        return None
    minute = 30 if match.group("half") else 0
    if match.group("minute"):
        minute = int(match.group("minute"))
    hour = _apply_period(hour, period)
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def _extract_duration(text: str) -> int | None:
    match = re.search(rf"({_CN_NUMBER})\s*个?\s*半\s*个?\s*(?:小时|钟头)", text)
    if match:
        value = _cn_to_int(match.group(1))
        if value is not None:
            return value * 60 + 30
    if re.search(r"半\s*个?\s*(?:小时|钟头)", text):
        return 30
    match = re.search(rf"({_CN_NUMBER})\s*个?\s*(?:小时|钟头)", text)
    if match:
        value = _cn_to_int(match.group(1))
        if value is not None:
            return value * 60
    match = re.search(r"(\d+)\s*分钟", text)
    if match:
        return int(match.group(1))
    decimal = re.search(r"(\d+(?:\.\d+)?)\s*个?\s*(?:小时|钟头)", text)
    if decimal:
        return round(float(decimal.group(1)) * 60)
    return None


def _extract_party_size(text: str) -> int | None:
    match = re.search(rf"(?<![\d])({_CN_NUMBER})\s*个?\s*(?:人|位)", text)
    if not match:
        return None
    return _cn_to_int(match.group(1))


def _extract_floor(text: str) -> int | None:
    match = re.search(rf"(?<![\d])({_CN_NUMBER})\s*(?:楼|层)", text)
    if not match:
        return None
    return _cn_to_int(match.group(1))


def _looks_like_booking(text: str) -> bool:
    if any(marker in text for marker in _NON_BOOKING_MARKERS):
        return False
    return any(marker in text for marker in _BOOKING_MARKERS)


def _resource_type(text: str) -> str | None:
    if any(label in text for label in _UNSUPPORTED_TYPES):
        for label in _UNSUPPORTED_TYPES:
            if label in text:
                return label
    if "会议室" in text or "开会" in text or "会议" in text:
        return "MEETING_ROOM"
    return None


def parse_booking_message(
    message: str, *, reference_now: datetime, timezone: str
) -> BookingExtraction:
    del timezone  # The caller already resolved the site timezone.
    text = _strip_identifiers(normalize_text(message))
    if not _looks_like_booking(text):
        return BookingExtraction(is_booking_request=False)

    today = reference_now.date()
    parsed_date, date_hint = _extract_date(text, today)
    period = _extract_period(text) or date_hint
    time_text = _strip_date_fragments(text)

    duration = _extract_duration(text)
    window_start: time | None = None
    window_end: time | None = None

    time_range = _extract_range(time_text, period)
    if time_range is not None:
        start_minutes, end_minutes = time_range
        window_start = time(start_minutes // 60, start_minutes % 60)
        window_end = time(end_minutes // 60, end_minutes % 60)
        if duration is None and end_minutes > start_minutes:
            duration = end_minutes - start_minutes
    else:
        start = _extract_start(time_text, period)
        if start is not None:
            window_start = time(start // 60, start % 60)
            if duration is not None:
                total = start + duration
                window_end = time((total // 60) % 24, total % 60)
        elif period is not None:
            window_start = time(period[0], period[1])
            window_end = time(period[2], period[3])

    return BookingExtraction(
        is_booking_request=True,
        resource_type=_resource_type(text),
        date=parsed_date,
        time_window_start=window_start,
        time_window_end=window_end,
        duration_minutes=duration,
        party_size=_extract_party_size(text),
        required_equipment=canonicalize_equipment(text),
        preferred_floor=_extract_floor(text),
    )
