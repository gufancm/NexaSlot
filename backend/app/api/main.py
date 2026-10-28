from fastapi import APIRouter

from app.api.routes import (
    login,
    organizations,
    private,
    reservations,
    resources,
    sites,
    users,
    utils,
)
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(organizations.router)
api_router.include_router(sites.router)
api_router.include_router(resources.router)
api_router.include_router(reservations.router)


if settings.FASTAPI_ENV == "development":
    api_router.include_router(private.router)
