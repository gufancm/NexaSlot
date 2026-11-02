import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

from app.core.errors import api_error
from app.schemas import ErrorCode
from app.services.db_retry import retry_on_deadlock


def _operational_error(code: int) -> OperationalError:
    return OperationalError("statement", {}, Exception(code, "mysql error"))


def test_retries_mysql_deadlock(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    monkeypatch.setattr("app.services.db_retry.time.sleep", lambda _: None)

    @retry_on_deadlock(max_retries=2)
    def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise _operational_error(1213)
        return "ok"

    assert flaky() == "ok"
    assert calls == 3


def test_stops_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    monkeypatch.setattr("app.services.db_retry.time.sleep", lambda _: None)

    @retry_on_deadlock(max_retries=2)
    def always_deadlocks() -> None:
        nonlocal calls
        calls += 1
        raise _operational_error(1213)

    with pytest.raises(OperationalError):
        always_deadlocks()
    assert calls == 3


def test_does_not_retry_business_conflict() -> None:
    calls = 0

    @retry_on_deadlock()
    def conflict() -> None:
        nonlocal calls
        calls += 1
        raise api_error(409, ErrorCode.SLOT_UNAVAILABLE, "slot taken")

    with pytest.raises(HTTPException):
        conflict()
    assert calls == 1


def test_does_not_retry_unrelated_operational_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    monkeypatch.setattr("app.services.db_retry.time.sleep", lambda _: None)

    @retry_on_deadlock()
    def connection_lost() -> None:
        nonlocal calls
        calls += 1
        raise _operational_error(2006)

    with pytest.raises(OperationalError):
        connection_lost()
    assert calls == 1
