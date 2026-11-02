import uuid

import pytest

from app.cache import availability


def test_cache_hit_does_not_build() -> None:
    built = 0

    def build() -> dict[str, str]:
        nonlocal built
        built += 1
        return {"value": "db"}

    result = availability.read_cached_or_build(
        key="k",
        get_cached=lambda _key: {"value": "cached"},
        set_cached=lambda _key, _value: None,
        lock="lock",
        fallback_lock="fallback",
        build=build,
    )

    assert result == {"value": "cached"}
    assert built == 0


def test_lock_owner_builds_and_populates_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    stored: dict[str, dict[str, str]] = {}
    deleted: list[str] = []
    monkeypatch.setattr(availability, "acquire_lock", lambda *_, **__: True)
    monkeypatch.setattr(availability, "cache_delete", deleted.append)

    result = availability.read_cached_or_build(
        key="k",
        get_cached=lambda _key: None,
        set_cached=lambda key, value: stored.update({key: value}),
        lock="lock",
        fallback_lock="fallback",
        build=lambda: {"value": "db"},
    )

    assert result == {"value": "db"}
    assert stored == {"k": {"value": "db"}}
    assert deleted == ["lock"]


def test_waiter_retries_cache_after_owner_fills(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    monkeypatch.setattr(availability, "acquire_lock", lambda *_, **__: False)
    monkeypatch.setattr(availability.time, "sleep", lambda _: None)

    def get_cached(_key: str) -> dict[str, str] | None:
        nonlocal calls
        calls += 1
        return {"value": "filled"} if calls >= 2 else None

    result = availability.read_cached_or_build(
        key="k",
        get_cached=get_cached,
        set_cached=lambda _key, _value: None,
        lock="lock",
        fallback_lock="fallback",
        build=lambda: {"value": "db"},
    )

    assert result == {"value": "filled"}
    assert calls == 2


def test_fallback_builds_when_both_locks_are_contended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(availability, "acquire_lock", lambda *_, **__: False)
    monkeypatch.setattr(availability.time, "sleep", lambda _: None)
    monkeypatch.setattr(availability, "cache_delete", lambda _key: None)

    result = availability.read_cached_or_build(
        key="k",
        get_cached=lambda _key: None,
        set_cached=lambda _key, _value: None,
        lock="lock",
        fallback_lock="fallback",
        build=lambda: {"value": "last-resort"},
    )

    assert result == {"value": "last-resort"}


def test_ttl_jitter_stays_in_configured_range() -> None:
    assert 60 <= availability._ttl_with_jitter(60, 15) <= 75
    assert 300 <= availability._ttl_with_jitter(300, 60) <= 360


def test_strict_invalidation_raises_for_outbox_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(availability.settings, "CACHE_ENABLED", True)

    def fail(*_args, **_kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(availability, "cache_incr", fail)

    with pytest.raises(ConnectionError):
        availability.invalidate_resource(uuid.uuid4(), strict=True)

    assert availability.invalidate_resource(uuid.uuid4(), strict=False) is False
