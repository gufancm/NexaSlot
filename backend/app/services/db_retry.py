"""Bounded retry for MySQL lock-wait and deadlock errors.

Business conflicts are represented as ``HTTPException`` and are never retried
here. Only MySQL 1205 (lock wait timeout) and 1213 (deadlock) are retried,
because each retry starts from a fresh Session/transaction.
"""

import random
import time
from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from sqlalchemy.exc import OperationalError

P = ParamSpec("P")
R = TypeVar("R")

MYSQL_RETRYABLE_ERRORS = frozenset({1205, 1213})
DEFAULT_MAX_RETRIES = 2


def mysql_error_code(exc: OperationalError) -> int | None:
    args = getattr(getattr(exc, "orig", None), "args", None) or ()
    if not args:
        return None
    try:
        return int(args[0])
    except TypeError, ValueError:
        return None


def retry_on_deadlock(
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Retry a whole service call with a new Session and jittered backoff."""

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except OperationalError as exc:
                    if (
                        mysql_error_code(exc) not in MYSQL_RETRYABLE_ERRORS
                        or attempt >= max_retries
                    ):
                        raise
                    # The service's `with Session` block rolls back before the
                    # exception reaches this wrapper, so the retry is fresh.
                    time.sleep(random.uniform(0.02, 0.08) * (attempt + 1))
            raise AssertionError("unreachable")

        return wrapper

    return decorator
