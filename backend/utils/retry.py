"""Async retry helper with the spec's 1s / 2s / 5s backoff schedule."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from backend.utils.logger import get_logger

log = get_logger(__name__)
T = TypeVar("T")

BACKOFF_SCHEDULE = (1.0, 2.0, 5.0)


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    retriable: tuple[type[BaseException], ...] = (Exception,),
    should_retry: Callable[[BaseException], bool] | None = None,
    label: str = "operation",
) -> T:
    """Run `fn`, retrying on failure with 1s/2s/5s delays. Raises the last error.

    `should_retry` lets callers fail fast on permanent errors (bad API key,
    server not running) instead of burning seconds on pointless backoff.
    """
    last: BaseException | None = None
    for i in range(max(1, attempts)):
        try:
            return await fn()
        except retriable as exc:  # noqa: PERF203 — retry loop by design
            last = exc
            if should_retry is not None and not should_retry(exc):
                log.info("%s failed permanently (%s) — not retrying", label, exc)
                raise
            if i < attempts - 1:
                delay = BACKOFF_SCHEDULE[min(i, len(BACKOFF_SCHEDULE) - 1)]
                log.warning("%s failed (attempt %d/%d): %s — retrying in %.0fs",
                            label, i + 1, attempts, exc, delay)
                await asyncio.sleep(delay)
    assert last is not None
    raise last
