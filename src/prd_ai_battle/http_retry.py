"""Retry policy for production HTTP Chat Completions (429 / 5xx / timeout)."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import TypeVar

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
DEFAULT_BACKOFF_S = (0.4, 0.8, 1.6)
DEFAULT_ATTEMPTS = 4

T = TypeVar("T")


def backoff_seconds(attempt: int, schedule: Sequence[float] = DEFAULT_BACKOFF_S) -> float:
    """attempt is 0-based (sleep after that failed try)."""
    if attempt < 0:
        return 0.0
    if attempt < len(schedule):
        return schedule[attempt]
    return schedule[-1]


def should_retry_status(status: int) -> bool:
    return status in RETRYABLE_STATUS


def retry_call(
    fn: Callable[[], T],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    schedule: Sequence[float] = DEFAULT_BACKOFF_S,
    sleeper: Callable[[float], None] = time.sleep,
    retryable: Callable[[BaseException], bool] | None = None,
) -> T:
    """Call fn up to `attempts` times. Last exception is raised."""
    last: BaseException | None = None
    for i in range(max(1, attempts)):
        try:
            return fn()
        except BaseException as exc:  # noqa: BLE001 — caller decides retryable
            last = exc
            if i >= attempts - 1:
                break
            if retryable is not None and not retryable(exc):
                break
            sleeper(backoff_seconds(i, schedule))
    assert last is not None
    raise last
