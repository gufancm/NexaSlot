import json
from datetime import datetime
from pathlib import Path

import pytest

from app.ai.mock import parse_booking_message
from app.ai.schemas import BookingExtraction

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "ai_booking_cases.json").read_text(
        encoding="utf-8"
    )
)


def _normalized(field: str, value: object) -> object:
    if field == "date":
        return value.isoformat() if value is not None else None
    if field in {"time_window_start", "time_window_end"}:
        return value.strftime("%H:%M") if value is not None else None
    return value


def test_fixture_set_has_forty_frozen_cases() -> None:
    assert len(FIXTURES) == 40
    assert len({case["id"] for case in FIXTURES}) == 40


@pytest.mark.parametrize("case", FIXTURES, ids=[case["id"] for case in FIXTURES])
def test_mock_parser_matches_frozen_expectation(case: dict) -> None:
    reference_now = datetime.fromisoformat(case["reference_now"])
    extraction = parse_booking_message(
        case["message"],
        reference_now=reference_now,
        timezone="Asia/Shanghai",
    )
    for field, expected in case["expect"].items():
        actual = _normalized(field, getattr(extraction, field))
        assert actual == expected, (
            f"{case['id']} field {field}: {actual!r} != {expected!r}"
        )

    # The same object must remain valid after serialization, as it would be
    # after a real provider JSON response.
    BookingExtraction.model_validate(extraction.model_dump())
