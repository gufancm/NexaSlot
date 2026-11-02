import uuid

from app.models import Resource, Site
from app.services.matching import _score


def _resource(capacity: int, site_id: uuid.UUID) -> Resource:
    return Resource(site_id=site_id, name="测试会议室", capacity=capacity)


def _site() -> Site:
    return Site(organization_id=uuid.uuid4(), name="A 座")


def test_exact_capacity_has_highest_capacity_score() -> None:
    site = _site()
    exact = _resource(8, site.id)
    oversized = _resource(20, site.id)

    exact_score, _reasons, exact_parts = _score(
        resource=exact,
        party_size=8,
        preferred_site_id=site.id,
        window_requested=True,
        start=None,
        site=site,
    )
    oversized_score, _reasons, oversized_parts = _score(
        resource=oversized,
        party_size=8,
        preferred_site_id=site.id,
        window_requested=True,
        start=None,
        site=site,
    )

    assert exact_parts["capacity_score"] == 1.0
    assert exact_parts["total_score"] == 1.0
    assert exact_score == 100.0
    assert oversized_parts["capacity_score"] == 0.4
    assert oversized_score < exact_score


def test_unknown_site_and_window_get_neutral_scores() -> None:
    site = _site()
    resource = _resource(8, site.id)

    score, _reasons, parts = _score(
        resource=resource,
        party_size=8,
        preferred_site_id=None,
        window_requested=False,
        start=None,
        site=site,
    )

    assert parts == {
        "capacity_score": 1.0,
        "site_score": 0.5,
        "time_score": 0.5,
        "total_score": 0.75,
    }
    assert score == 75.0
