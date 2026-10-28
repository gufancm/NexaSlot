import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep, require_org
from app.core.errors import api_error
from app.core.time import get_timezone
from app.models import OrgRole, Site, SiteStatus
from app.schemas import ErrorCode, SiteCreate, SitePublic, SitesPublic, SiteUpdate
from app.services.audit import record_audit
from app.services.orgs import OrgAccess

router = APIRouter(tags=["sites"])

OrgMemberDep = Annotated[OrgAccess, Depends(require_org(OrgRole.MEMBER))]
OrgAdminDep = Annotated[OrgAccess, Depends(require_org(OrgRole.ORG_ADMIN))]


@router.get("/organizations/{org_id}/sites", response_model=SitesPublic)
def read_sites(
    *, session: SessionDep, org: OrgMemberDep, include_inactive: bool = False
) -> SitesPublic:
    statement = select(Site).where(Site.organization_id == org.organization.id)
    if not include_inactive:
        statement = statement.where(Site.status == SiteStatus.ACTIVE.value)
    sites = session.exec(statement.order_by(Site.name)).all()
    data = [
        SitePublic(
            id=item.id,
            organization_id=item.organization_id,
            name=item.name,
            address=item.address,
            timezone=item.timezone,
            status=item.status,
            created_at=item.created_at,
        )
        for item in sites
    ]
    return SitesPublic(data=data, count=len(data))


@router.post(
    "/organizations/{org_id}/sites", response_model=SitePublic, status_code=201
)
def create_site(
    *,
    session: SessionDep,
    org: OrgAdminDep,
    current_user: CurrentUser,
    payload: SiteCreate,
) -> SitePublic:
    get_timezone(payload.timezone)
    site = Site(
        organization_id=org.organization.id,
        name=payload.name.strip(),
        address=payload.address,
        timezone=payload.timezone,
    )
    session.add(site)
    record_audit(
        session,
        actor_id=current_user.id,
        organization_id=org.organization.id,
        action="site.create",
        target_type="site",
        target_id=site.id,
        detail={"name": site.name},
    )
    session.commit()
    session.refresh(site)
    return SitePublic(
        id=site.id,
        organization_id=site.organization_id,
        name=site.name,
        address=site.address,
        timezone=site.timezone,
        status=site.status,
        created_at=site.created_at,
    )


@router.patch("/organizations/{org_id}/sites/{site_id}", response_model=SitePublic)
def update_site(
    *,
    session: SessionDep,
    org: OrgAdminDep,
    current_user: CurrentUser,
    site_id: uuid.UUID,
    payload: SiteUpdate,
) -> SitePublic:
    site = session.get(Site, site_id)
    if site is None or site.organization_id != org.organization.id:
        raise api_error(404, ErrorCode.NOT_FOUND, "Site not found")

    data = payload.model_dump(exclude_unset=True)
    if "timezone" in data:
        get_timezone(data["timezone"])
    if "status" in data and data["status"] not in {
        SiteStatus.ACTIVE.value,
        SiteStatus.INACTIVE.value,
    }:
        raise api_error(422, ErrorCode.INVALID_REQUEST, "Unknown site status")

    for key, value in data.items():
        setattr(site, key, value)
    record_audit(
        session,
        actor_id=current_user.id,
        organization_id=org.organization.id,
        action="site.update",
        target_type="site",
        target_id=site.id,
        detail={key: str(value) for key, value in data.items()},
    )
    session.commit()
    session.refresh(site)
    return SitePublic(
        id=site.id,
        organization_id=site.organization_id,
        name=site.name,
        address=site.address,
        timezone=site.timezone,
        status=site.status,
        created_at=site.created_at,
    )
