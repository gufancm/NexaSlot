"""Create a deterministic demo organization for local UI exploration.

Usage (from the backend directory):

    uv run python scripts/seed_demo.py

The script is idempotent: running it twice will not duplicate data.
"""

from datetime import time

from sqlmodel import Session, select

from app.core.db import engine
from app.models import (
    OpeningRule,
    Organization,
    OrganizationMember,
    OrgRole,
    Resource,
    Site,
    SiteStatus,
    User,
)

DEMO_ORG = "NexaSlot 演示组织"
DEMO_SITE = "总部 A 座"

DEMO_RESOURCES = [
    {
        "name": "星河会议室",
        "capacity": 12,
        "features": ["投影仪", "视频会议", "白板"],
        "description": "12 人间，落地窗采光，适合跨团队评审。",
    },
    {
        "name": "云端会议室",
        "capacity": 6,
        "features": ["视频会议", "电视"],
        "description": "6 人间，适合周会与远程面试。",
    },
    {
        "name": "静思舱",
        "capacity": 2,
        "features": ["隔音", "白噪音"],
        "description": "2 人间专注空间，适合一对一沟通。",
    },
]


def main() -> None:
    with Session(engine) as session:
        owner = session.exec(
            select(User).where(User.email == "admin@example.com")
        ).first()
        if owner is None:
            raise SystemExit("Run `uv run python -m app.initial_data` first")

        organization = session.exec(
            select(Organization).where(Organization.name == DEMO_ORG)
        ).first()
        if organization is None:
            organization = Organization(name=DEMO_ORG)
            session.add(organization)
            session.flush()

        membership = session.exec(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == organization.id,
                OrganizationMember.user_id == owner.id,
            )
        ).first()
        if membership is None:
            session.add(
                OrganizationMember(
                    organization_id=organization.id,
                    user_id=owner.id,
                    role=OrgRole.ORG_ADMIN.value,
                )
            )

        site = session.exec(
            select(Site).where(
                Site.organization_id == organization.id, Site.name == DEMO_SITE
            )
        ).first()
        if site is None:
            site = Site(
                organization_id=organization.id,
                name=DEMO_SITE,
                address="上海市浦东新区世纪大道 100 号",
                timezone="Asia/Shanghai",
                status=SiteStatus.ACTIVE.value,
            )
            session.add(site)
            session.flush()

        for item in DEMO_RESOURCES:
            resource = session.exec(
                select(Resource).where(
                    Resource.site_id == site.id, Resource.name == item["name"]
                )
            ).first()
            if resource is None:
                resource = Resource(
                    site_id=site.id,
                    name=item["name"],
                    capacity=item["capacity"],
                    features=item["features"],
                    description=item["description"],
                )
                session.add(resource)
                session.flush()

            existing_rules = session.exec(
                select(OpeningRule).where(OpeningRule.resource_id == resource.id)
            ).all()
            if not existing_rules:
                for weekday in range(7):
                    session.add(
                        OpeningRule(
                            resource_id=resource.id,
                            weekday=weekday,
                            start_time=time(9, 0),
                            end_time=time(21, 0),
                        )
                    )

        session.commit()
        print(f"Seeded demo organization: {organization.name}")  # noqa: T201


if __name__ == "__main__":
    main()
