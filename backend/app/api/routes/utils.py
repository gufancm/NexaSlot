from fastapi import APIRouter, Depends
from pydantic.networks import EmailStr
from sqlalchemy import text

from app.api.deps import SessionDep, get_current_active_superuser
from app.core.errors import api_error
from app.core.redis import ping_redis
from app.models import Message
from app.schemas import ErrorCode
from app.utils import generate_test_email, send_email

router = APIRouter(prefix="/utils", tags=["utils"])


@router.post(
    "/test-email/",
    dependencies=[Depends(get_current_active_superuser)],
    status_code=201,
)
def test_email(email_to: EmailStr) -> Message:
    """
    Test emails.
    """
    email_data = generate_test_email(email_to=email_to)
    send_email(
        email_to=email_to,
        subject=email_data.subject,
        html_content=email_data.html_content,
    )
    return Message(message="Test email sent")


@router.get("/health-check/")
async def health_check(session: SessionDep) -> dict[str, object]:
    """Liveness probe: MySQL is required, Redis status is reported as degraded."""
    try:
        session.exec(text("SELECT 1"))
    except Exception:
        raise api_error(503, ErrorCode.CONFLICT, "Database is unavailable")

    redis_ok = await ping_redis()
    return {
        "status": "ok",
        "database": True,
        "redis": redis_ok,
    }
