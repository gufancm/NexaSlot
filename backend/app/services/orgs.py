import uuid
from dataclasses import dataclass

from sqlmodel import Session, select

from app.core.errors import api_error
from app.models import (
    ORG_ROLE_RANK,
    Organization,
    OrganizationMember,
    OrgRole,
    OrgStatus,
    Resource,
    ResourceStatus,
    Site,
    SiteStatus,
    User,
)
from app.schemas import ErrorCode


@dataclass(frozen=True)
class OrgAccess:
    organization: Organization
    role: str


def role_at_least(role: str, minimum: OrgRole) -> bool:
    return ORG_ROLE_RANK.get(role, 0) >= ORG_ROLE_RANK[minimum]


def get_organization(session: Session, org_id: uuid.UUID) -> Organization:
    organization = session.get(Organization, org_id)
    if organization is None:
        raise api_error(404, ErrorCode.NOT_FOUND, "Organization not found")
    return organization


def get_membership(
    session: Session, user: User, org_id: uuid.UUID
) -> OrganizationMember | None:
    return session.exec(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user.id,
        )
    ).first()


def require_org_access(
    session: Session,
    user: User,
    org_id: uuid.UUID,
    minimum: OrgRole = OrgRole.MEMBER,
) -> OrgAccess:
    """Resolve the caller's role inside an organization.

    Membership is always read on the server; a client supplied role or
    organization id is never trusted. Platform superusers bypass membership
    checks for operational support.
    """
    organization = get_organization(session, org_id)
    if organization.status != OrgStatus.ACTIVE:
        raise api_error(403, ErrorCode.FORBIDDEN, "Organization is suspended")

    if user.is_superuser:
        return OrgAccess(organization=organization, role=OrgRole.ORG_ADMIN)

    membership = get_membership(session, user, org_id)
    if membership is None:
        raise api_error(
            403, ErrorCode.FORBIDDEN, "You are not a member of this organization"
        )
    if not role_at_least(membership.role, minimum):
        raise api_error(
            403,
            ErrorCode.FORBIDDEN,
            f"This action requires the {minimum} role",
        )
    return OrgAccess(organization=organization, role=membership.role)


@dataclass(frozen=True)
class ResourceAccess:
    resource: Resource
    site: Site
    org: OrgAccess


def require_resource_access(
    session: Session,
    user: User,
    resource_id: uuid.UUID,
    minimum: OrgRole = OrgRole.MEMBER,
) -> ResourceAccess:
    resource = session.get(Resource, resource_id)
    if resource is None:
        raise api_error(404, ErrorCode.RESOURCE_NOT_FOUND, "Resource not found")
    site = session.get(Site, resource.site_id)
    if site is None:
        raise api_error(404, ErrorCode.RESOURCE_NOT_FOUND, "Resource site not found")
    org = require_org_access(session, user, site.organization_id, minimum)
    return ResourceAccess(resource=resource, site=site, org=org)


def ensure_publishable_site(site: Site) -> None:
    if site.status != SiteStatus.ACTIVE:
        raise api_error(
            400,
            ErrorCode.INVALID_REQUEST,
            "Site is inactive and cannot host resources",
        )


def ensure_active_resource(resource: Resource) -> None:
    if resource.status != ResourceStatus.ACTIVE:
        raise api_error(
            400, ErrorCode.RESOURCE_INACTIVE, "Resource is not open for booking"
        )
