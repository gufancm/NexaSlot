import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session, func, select

from app import crud
from app.api.deps import CurrentUser, SessionDep, require_org
from app.core.errors import api_error
from app.core.time import to_db, utcnow
from app.models import (
    ORG_ROLE_RANK,
    Organization,
    OrganizationMember,
    OrgRole,
    Reservation,
    ReservationStatus,
    Resource,
    ResourceSlot,
    Site,
    User,
)
from app.schemas import (
    DashboardPublic,
    ErrorCode,
    MemberAdd,
    MemberPublic,
    MembersPublic,
    MemberUpdate,
    OrganizationCreate,
    OrganizationPublic,
    OrganizationsPublic,
)
from app.services.audit import record_audit
from app.services.orgs import OrgAccess

router = APIRouter(prefix="/organizations", tags=["organizations"])

OrgMemberDep = Annotated[OrgAccess, Depends(require_org(OrgRole.MEMBER))]
OrgAdminDep = Annotated[OrgAccess, Depends(require_org(OrgRole.ORG_ADMIN))]


def _organization_public(organization: Organization, role: str) -> OrganizationPublic:
    return OrganizationPublic(
        id=organization.id,
        name=organization.name,
        status=organization.status,
        role=role,
        created_at=organization.created_at,
    )


@router.get("/me", response_model=OrganizationsPublic)
def read_my_organizations(
    session: SessionDep, current_user: CurrentUser
) -> OrganizationsPublic:
    """Organizations the caller can access, with the caller's role."""
    if current_user.is_superuser:
        organizations = session.exec(
            select(Organization).order_by(Organization.name)
        ).all()
        return OrganizationsPublic(
            data=[
                _organization_public(item, OrgRole.ORG_ADMIN.value)
                for item in organizations
            ]
        )

    memberships = session.exec(
        select(OrganizationMember).where(OrganizationMember.user_id == current_user.id)
    ).all()
    if not memberships:
        return OrganizationsPublic(data=[])

    organization_ids = {item.organization_id for item in memberships}
    organizations = {
        item.id: item
        for item in session.exec(
            select(Organization).where(Organization.id.in_(organization_ids))
        ).all()
    }
    data = [
        _organization_public(organizations[membership.organization_id], membership.role)
        for membership in memberships
        if membership.organization_id in organizations
    ]
    data.sort(key=lambda item: item.name)
    return OrganizationsPublic(data=data)


@router.post("", response_model=OrganizationPublic, status_code=201)
def create_organization(
    *, session: SessionDep, current_user: CurrentUser, payload: OrganizationCreate
) -> OrganizationPublic:
    organization = Organization(name=payload.name.strip())
    session.add(organization)
    session.flush()
    session.add(
        OrganizationMember(
            organization_id=organization.id,
            user_id=current_user.id,
            role=OrgRole.ORG_ADMIN.value,
        )
    )
    record_audit(
        session,
        actor_id=current_user.id,
        organization_id=organization.id,
        action="organization.create",
        target_type="organization",
        target_id=organization.id,
        detail={"name": organization.name},
    )
    session.commit()
    session.refresh(organization)
    return _organization_public(organization, OrgRole.ORG_ADMIN.value)


@router.get("/{org_id}/members", response_model=MembersPublic)
def read_members(*, session: SessionDep, org: OrgAdminDep) -> MembersPublic:
    memberships = session.exec(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org.organization.id
        )
    ).all()
    user_ids = {item.user_id for item in memberships}
    users = {
        item.id: item
        for item in session.exec(select(User).where(User.id.in_(user_ids))).all()
    }
    data = [
        MemberPublic(
            user_id=item.user_id,
            email=users[item.user_id].email,
            full_name=users[item.user_id].full_name,
            role=item.role,
            created_at=item.created_at,
        )
        for item in memberships
        if item.user_id in users
    ]
    data.sort(key=lambda item: ORG_ROLE_RANK.get(item.role, 0), reverse=True)
    return MembersPublic(data=data, count=len(data))


@router.post("/{org_id}/members", response_model=MemberPublic, status_code=201)
def add_member(
    *,
    session: SessionDep,
    org: OrgAdminDep,
    current_user: CurrentUser,
    payload: MemberAdd,
) -> MemberPublic:
    if payload.role not in {role.value for role in OrgRole}:
        raise api_error(422, ErrorCode.INVALID_REQUEST, "Unknown organization role")

    user = crud.get_user_by_email(session=session, email=payload.email)
    if user is None:
        raise api_error(
            404,
            ErrorCode.MEMBER_NOT_FOUND,
            "No registered user with this email, ask them to sign up first",
        )

    existing = session.exec(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org.organization.id,
            OrganizationMember.user_id == user.id,
        )
    ).first()
    if existing is not None:
        raise api_error(
            409, ErrorCode.DUPLICATE_MEMBER, "This user is already a member"
        )

    membership = OrganizationMember(
        organization_id=org.organization.id,
        user_id=user.id,
        role=payload.role,
    )
    session.add(membership)
    record_audit(
        session,
        actor_id=current_user.id,
        organization_id=org.organization.id,
        action="member.add",
        target_type="user",
        target_id=user.id,
        detail={"role": payload.role},
    )
    session.commit()
    session.refresh(membership)
    return MemberPublic(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=membership.role,
        created_at=membership.created_at,
    )


@router.patch("/{org_id}/members/{user_id}", response_model=MemberPublic)
def update_member_role(
    *,
    session: SessionDep,
    org: OrgAdminDep,
    current_user: CurrentUser,
    user_id: uuid.UUID,
    payload: MemberUpdate,
) -> MemberPublic:
    if payload.role not in {role.value for role in OrgRole}:
        raise api_error(422, ErrorCode.INVALID_REQUEST, "Unknown organization role")

    membership = session.exec(
        select(OrganizationMember)
        .where(
            OrganizationMember.organization_id == org.organization.id,
            OrganizationMember.user_id == user_id,
        )
        .with_for_update()
    ).first()
    if membership is None:
        raise api_error(404, ErrorCode.MEMBER_NOT_FOUND, "Member not found")

    if (
        membership.role == OrgRole.ORG_ADMIN.value
        and payload.role != OrgRole.ORG_ADMIN.value
        and _count_admins(session, org.organization.id) <= 1
    ):
        raise api_error(
            409, ErrorCode.CONFLICT, "An organization must keep at least one admin"
        )

    membership.role = payload.role
    record_audit(
        session,
        actor_id=current_user.id,
        organization_id=org.organization.id,
        action="member.update_role",
        target_type="user",
        target_id=user_id,
        detail={"role": payload.role},
    )
    session.commit()
    session.refresh(membership)

    user = session.get(User, user_id)
    assert user is not None
    return MemberPublic(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=membership.role,
        created_at=membership.created_at,
    )


@router.delete("/{org_id}/members/{user_id}", status_code=204)
def remove_member(
    *,
    session: SessionDep,
    org: OrgAdminDep,
    current_user: CurrentUser,
    user_id: uuid.UUID,
) -> None:
    membership = session.exec(
        select(OrganizationMember)
        .where(
            OrganizationMember.organization_id == org.organization.id,
            OrganizationMember.user_id == user_id,
        )
        .with_for_update()
    ).first()
    if membership is None:
        raise api_error(404, ErrorCode.MEMBER_NOT_FOUND, "Member not found")

    if (
        membership.role == OrgRole.ORG_ADMIN.value
        and _count_admins(session, org.organization.id) <= 1
    ):
        raise api_error(
            409, ErrorCode.CONFLICT, "An organization must keep at least one admin"
        )

    session.delete(membership)
    record_audit(
        session,
        actor_id=current_user.id,
        organization_id=org.organization.id,
        action="member.remove",
        target_type="user",
        target_id=user_id,
    )
    session.commit()


def _count_admins(session: Session, organization_id: uuid.UUID) -> int:
    return int(
        session.exec(
            select(func.count())
            .select_from(OrganizationMember)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.role == OrgRole.ORG_ADMIN.value,
            )
        ).one()
    )


@router.get("/{org_id}/dashboard", response_model=DashboardPublic)
def read_dashboard(*, session: SessionDep, org: OrgAdminDep) -> DashboardPublic:
    organization_id = org.organization.id
    now = utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    site_ids = list(
        session.exec(
            select(Site.id).where(Site.organization_id == organization_id)
        ).all()
    )
    resource_ids = (
        list(
            session.exec(
                select(Resource.id).where(Resource.site_id.in_(site_ids))
            ).all()
        )
        if site_ids
        else []
    )

    total_reservations = 0
    upcoming = 0
    today = 0
    if resource_ids:
        total_reservations = int(
            session.exec(
                select(func.count())
                .select_from(Reservation)
                .where(Reservation.organization_id == organization_id)
            ).one()
        )
        upcoming = int(
            session.exec(
                select(func.count())
                .select_from(Reservation)
                .where(
                    Reservation.organization_id == organization_id,
                    Reservation.status == ReservationStatus.CONFIRMED.value,
                    Reservation.start_at >= to_db(now),
                )
            ).one()
        )
        today = int(
            session.exec(
                select(func.count())
                .select_from(Reservation)
                .where(
                    Reservation.organization_id == organization_id,
                    Reservation.start_at >= to_db(today_start),
                    Reservation.start_at < to_db(today_start + timedelta(days=1)),
                )
            ).one()
        )

    occupied = 0
    slot_total = 0
    if resource_ids:
        slot_total = int(
            session.exec(
                select(func.count())
                .select_from(ResourceSlot)
                .where(
                    ResourceSlot.resource_id.in_(resource_ids),
                    ResourceSlot.start_at >= to_db(today_start),
                    ResourceSlot.start_at < to_db(today_start + timedelta(days=1)),
                )
            ).one()
        )
        occupied = int(
            session.exec(
                select(func.count())
                .select_from(ResourceSlot)
                .where(
                    ResourceSlot.resource_id.in_(resource_ids),
                    ResourceSlot.start_at >= to_db(today_start),
                    ResourceSlot.start_at < to_db(today_start + timedelta(days=1)),
                    ResourceSlot.current_reservation_id.is_not(None),
                )
            ).one()
        )

    return DashboardPublic(
        reservations_total=total_reservations,
        reservations_upcoming=upcoming,
        reservations_today=today,
        resources_total=len(resource_ids),
        sites_total=len(site_ids),
        occupied_slot_ratio=round(occupied / slot_total, 2) if slot_total else 0.0,
    )
