from fastapi import APIRouter

from app.api.routes import (
    ai,
    login,
    notifications,
    operations,
    organizations,
    private,
    reservations,
    resources,
    scheduling,
    sites,
    users,
    utils,
    waitlist,
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
api_router.include_router(waitlist.router)
api_router.include_router(scheduling.router)
api_router.include_router(notifications.router)
api_router.include_router(operations.router)
api_router.include_router(ai.router)


if settings.FASTAPI_ENV == "development":
    api_router.include_router(private.router)
