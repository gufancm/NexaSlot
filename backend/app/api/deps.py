import uuid
from collections.abc import Callable, Generator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session

from app.core import security
from app.core.config import settings
from app.core.db import engine
from app.models import OrgRole, TokenPayload, User
from app.services.orgs import (
    OrgAccess,
    ResourceAccess,
    require_org_access,
    require_resource_access,
)

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)


def get_db() -> Generator[Session]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]
TokenDep = Annotated[str, Depends(reusable_oauth2)]


def get_current_user(session: SessionDep, token: TokenDep) -> User:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except InvalidTokenError, ValidationError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    try:
        user_id = uuid.UUID(token_data.sub) if token_data.sub else None
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_active_superuser(current_user: CurrentUser) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return current_user


def require_org(
    minimum: OrgRole = OrgRole.MEMBER,
) -> Callable[..., OrgAccess]:
    """Dependency factory enforcing the caller's role inside ``{org_id}``."""

    def dependency(
        org_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
    ) -> OrgAccess:
        return require_org_access(session, current_user, org_id, minimum)

    return dependency


def require_resource(
    minimum: OrgRole = OrgRole.MEMBER,
) -> Callable[..., ResourceAccess]:
    """Dependency factory enforcing access to ``{resource_id}``."""

    def dependency(
        resource_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
    ) -> ResourceAccess:
        return require_resource_access(session, current_user, resource_id, minimum)

    return dependency
