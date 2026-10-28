"""Dedicated outbox and hold-expiry worker.

Run with ``python -m app.worker``. The worker only performs queue-style scans
and state transitions; it never fabricates availability. Multiple workers are
safe because outbox claims use SKIP LOCKED + leases and hold transitions lock
the resource, slots and hold rows in a fixed order.
"""

import logging
import signal
import threading

from app.core.config import settings
from app.services.outbox import run_once
from app.services.waitlist import expire_due_holds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("nexaslot.worker")

_stop = threading.Event()


def _handle_signal(signum: int, _frame: object) -> None:
    logger.info("received signal %s, stopping after current batch", signum)
    _stop.set()


def tick() -> dict[str, int]:
    expired = expire_due_holds()
    result = run_once()
    result["expired_holds"] = expired
    return result


def run_forever() -> None:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    logger.info("worker started, poll interval %.1fs", settings.WORKER_POLL_SECONDS)
    while not _stop.is_set():
        try:
            result = tick()
            if any(result.values()):
                logger.info("worker tick %s", result)
        except Exception:
            logger.exception("worker tick failed; retrying after poll interval")
        _stop.wait(settings.WORKER_POLL_SECONDS)
    logger.info("worker stopped")


def main() -> None:
    run_forever()


if __name__ == "__main__":  # pragma: no cover
    main()
