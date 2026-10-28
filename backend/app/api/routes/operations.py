import uuid

from fastapi import APIRouter, Depends, Query

from app.api.deps import SessionDep, get_current_active_superuser
from app.schemas import OperationsMetricsPublic, OutboxEventPublic, OutboxEventsPublic
from app.services.operations import failed_events, metrics, retry_event

router = APIRouter(
    prefix="/operations",
    tags=["operations"],
    dependencies=[Depends(get_current_active_superuser)],
)


@router.get("/metrics", response_model=OperationsMetricsPublic)
def read_operations_metrics(*, session: SessionDep) -> OperationsMetricsPublic:
    return metrics(session)


@router.get("/outbox/failed", response_model=OutboxEventsPublic)
def read_failed_outbox_events(
    *,
    session: SessionDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> OutboxEventsPublic:
    return failed_events(session, page=page, page_size=page_size)


@router.post("/outbox/{event_id}/retry", response_model=OutboxEventPublic)
def retry_failed_outbox_event(
    *, session: SessionDep, event_id: uuid.UUID
) -> OutboxEventPublic:
    return retry_event(session, event_id)
