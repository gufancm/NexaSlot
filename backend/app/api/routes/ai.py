"""V3 Lite smart booking recommendation endpoint."""

import logging
import time
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from redis.exceptions import RedisError

from app.ai.client import LLMClient, get_llm_client
from app.ai.schemas import AIRecommendPublic, AIRecommendRequest
from app.ai.service import recommend_booking
from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.ratelimit import check_rate_limit
from app.models import OrgRole
from app.schemas import ErrorCode
from app.services.orgs import require_org_access

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ai"])


def _ai_rate_limit(current_user: CurrentUser) -> None:
    if not settings.RATE_LIMIT_ENABLED:
        return
    try:
        allowed, retry_after = check_rate_limit(
            bucket="ai-recommend",
            identity=str(current_user.id),
            capacity=settings.RATE_LIMIT_AI_CAPACITY,
            refill_per_minute=settings.RATE_LIMIT_AI_REFILL_PER_MINUTE,
        )
    except RedisError as exc:
        logger.warning("AI rate limiter unavailable: %s", exc)
        return
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "code": ErrorCode.RATE_LIMITED.value,
                "message": "Too many AI requests, please slow down",
            },
            headers={"Retry-After": str(retry_after)},
        )


def get_llm_client_dependency() -> LLMClient | None:
    return get_llm_client()


LLMClientDep = Annotated[LLMClient | None, Depends(get_llm_client_dependency)]


@router.post(
    "/ai/recommend",
    response_model=AIRecommendPublic,
    dependencies=[Depends(_ai_rate_limit)],
)
def recommend_booking_endpoint(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    payload: AIRecommendRequest,
    client: LLMClientDep,
) -> AIRecommendPublic:
    trace_id = uuid4().hex[:12]
    started = time.perf_counter()
    org = require_org_access(session, current_user, payload.org_id, OrgRole.MEMBER)
    result = recommend_booking(session=session, org=org, request=payload, client=client)
    logger.info(
        "ai recommend trace_id=%s org_id=%s status=%s elapsed_ms=%.1f",
        trace_id,
        org.organization.id,
        result.status,
        (time.perf_counter() - started) * 1000,
    )
    return result
