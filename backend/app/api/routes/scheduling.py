from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, SessionDep, require_resource
from app.core.errors import api_error
from app.core.time import as_utc
from app.models import OrgRole
from app.schemas import (
    AlternativesPublic,
    ErrorCode,
    ResourceMatchPublic,
    ResourceMatchRequest,
)
from app.services.matching import alternatives_for_resource, match_resources
from app.services.orgs import ResourceAccess, require_org_access
from app.services.reservations import validate_booking_rules

router = APIRouter(tags=["scheduling"])


@router.post("/scheduling/match", response_model=ResourceMatchPublic)
def match_resource_endpoint(
    *, session: SessionDep, current_user: CurrentUser, payload: ResourceMatchRequest
) -> ResourceMatchPublic:
    org = require_org_access(session, current_user, payload.org_id, OrgRole.MEMBER)
    return match_resources(session=session, org=org, request=payload)


@router.get("/resources/{resource_id}/alternatives", response_model=AlternativesPublic)
def resource_alternatives_endpoint(
    *,
    session: SessionDep,
    access: Annotated[ResourceAccess, Depends(require_resource())],
    start_at: datetime,
    end_at: datetime,
) -> AlternativesPublic:
    start = as_utc(start_at)
    end = as_utc(end_at)
    if end <= start:
        raise api_error(422, ErrorCode.INVALID_REQUEST, "end_at must be after start_at")
    validate_booking_rules(access.site, start, end)
    return alternatives_for_resource(
        session=session, access=access, start=start, end=end
    )
