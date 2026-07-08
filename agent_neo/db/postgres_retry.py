"""Django default-database (PostgreSQL) resilience helpers for retired compat paths."""


from __future__ import annotations

import logging
import time
from typing import Callable, LiteralString, TypeVar

from django.db import DatabaseError, InterfaceError, OperationalError, close_old_connections, connection



__all__: tuple[LiteralString, ...] = (
    "POSTGRES_TRANSIENT_MAX_ATTEMPTS",
    "POSTGRES_TRANSIENT_RETRY_DELAY_SECONDS",
    "POSTGRES_TRANSIENT_BACKOFF_MULTIPLIER",
    "POSTGRES_TRANSIENT_MAX_RETRY_DELAY_SECONDS",
    "run_with_postgres_retries",
)

_T = TypeVar("_T")

POSTGRES_TRANSIENT_MAX_ATTEMPTS: int = 5
POSTGRES_TRANSIENT_RETRY_DELAY_SECONDS: float = 5.0
POSTGRES_TRANSIENT_BACKOFF_MULTIPLIER: float = 2.0
POSTGRES_TRANSIENT_MAX_RETRY_DELAY_SECONDS: float = 60.0

_TRANSIENT_POSTGRES_MESSAGE_MARKERS: tuple[str, ...] = (
    "server closed the connection unexpectedly",
    "connection already closed",
    "connection reset",
    "connection refused",
    "connection timed out",
    "could not connect to server",
    "terminating connection",
    "ssl connection has been closed unexpectedly",
    "broken pipe",
)

log = logging.getLogger(__name__)


def _retry_delay_for_attempt(attempt_index: int) -> float:
    if attempt_index <= 1:
        return POSTGRES_TRANSIENT_RETRY_DELAY_SECONDS
    grown_delay = POSTGRES_TRANSIENT_RETRY_DELAY_SECONDS * (
        POSTGRES_TRANSIENT_BACKOFF_MULTIPLIER ** (attempt_index - 1)
    )
    return min(grown_delay, POSTGRES_TRANSIENT_MAX_RETRY_DELAY_SECONDS)


def _is_transient_postgres_error(exc: BaseException) -> bool:
    if isinstance(exc, (OperationalError, InterfaceError)):
        return True
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    if not isinstance(exc, DatabaseError):
        return False

    message = str(exc).lower()
    return any(marker in message for marker in _TRANSIENT_POSTGRES_MESSAGE_MARKERS)


def _reset_django_db_connection() -> None:
    close_old_connections()
    connection.close()
    close_old_connections()


def run_with_postgres_retries(
    operation: Callable[[], _T],
    *,
    description: str,
) -> _T:
    last_error: BaseException | None = None
    for attempt_index in range(1, POSTGRES_TRANSIENT_MAX_ATTEMPTS + 1):
        try:
            close_old_connections()
            return operation()
        except BaseException as exc:
            last_error = exc
            attempts_exhausted = attempt_index >= POSTGRES_TRANSIENT_MAX_ATTEMPTS
            if attempts_exhausted or not _is_transient_postgres_error(exc):
                raise

            delay_seconds = _retry_delay_for_attempt(attempt_index)
            log.warning(
                "%s: transient PostgreSQL error on attempt %s/%s (%s); "
                "resetting connection and retrying in %ss",
                description,
                attempt_index,
                POSTGRES_TRANSIENT_MAX_ATTEMPTS,
                exc,
                delay_seconds,
            )
            _reset_django_db_connection()
            time.sleep(delay_seconds)

    raise RuntimeError(f"{description}: retry loop exited without result") from last_error
