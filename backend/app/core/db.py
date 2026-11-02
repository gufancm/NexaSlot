import logging
import time

from sqlalchemy import event
from sqlmodel import Session, create_engine, select

from app import crud
from app.core.config import settings
from app.models import User, UserCreate

logger = logging.getLogger("nexaslot.db")

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
    pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
    pool_use_lifo=True,
    echo=settings.DB_ECHO,
    isolation_level="READ COMMITTED",
)


@event.listens_for(engine, "checkout")
def _record_checkout(
    _dbapi_connection: object, connection_record: object, _connection_proxy: object
) -> None:
    connection_record.info["checkout_started"] = time.perf_counter()


@event.listens_for(engine, "checkin")
def _log_slow_checkin(_dbapi_connection: object, connection_record: object) -> None:
    started = connection_record.info.pop("checkout_started", None)
    if started is None:
        return
    held_seconds = time.perf_counter() - started
    if held_seconds >= 2.0:
        logger.warning("database connection held for %.2fs", held_seconds)


# make sure all SQLModel models are imported (app.models) before initializing DB
# otherwise, SQLModel might fail to initialize relationships properly
# for more details: https://github.com/fastapi/full-stack-fastapi-template/issues/28


def init_db(session: Session) -> None:
    # Tables are created with Alembic migrations (`alembic upgrade head`).
    user = session.exec(
        select(User).where(User.email == settings.FIRST_SUPERUSER)
    ).first()
    if not user:
        user_in = UserCreate(
            email=settings.FIRST_SUPERUSER,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            is_superuser=True,
        )
        user = crud.create_user(session=session, user_create=user_in)
