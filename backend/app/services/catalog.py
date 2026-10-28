from sqlmodel import Session, select

from app.models import Resource, Site
from app.schemas import ResourcePublic


def resource_public(
    session: Session, resource: Resource, site: Site | None = None
) -> ResourcePublic:
    if site is None:
        site = session.get(Site, resource.site_id)
    assert site is not None
    return ResourcePublic(
        id=resource.id,
        organization_id=site.organization_id,
        site_id=resource.site_id,
        site_name=site.name,
        timezone=site.timezone,
        name=resource.name,
        description=resource.description,
        capacity=resource.capacity,
        features=list(resource.features or []),
        status=resource.status,
        created_at=resource.created_at,
    )


def resource_public_list(
    session: Session, resources: list[Resource]
) -> list[ResourcePublic]:
    if not resources:
        return []
    site_ids = {item.site_id for item in resources}
    sites = {
        item.id: item
        for item in session.exec(select(Site).where(Site.id.in_(site_ids))).all()
    }
    return [
        resource_public(session, item, sites.get(item.site_id)) for item in resources
    ]
