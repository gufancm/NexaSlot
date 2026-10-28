import uuid

from sqlmodel import Session

from app.models import AuditLog


def record_audit(
    session: Session,
    *,
    actor_id: uuid.UUID | None,
    organization_id: uuid.UUID | None,
    action: str,
    target_type: str,
    target_id: str | uuid.UUID,
    detail: dict | None = None,
) -> None:
    """Append an audit entry to the current transaction (no token/password data)."""
    session.add(
        AuditLog(
            actor_id=actor_id,
            organization_id=organization_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            detail=detail,
        )
    )
