from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TypeVar

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from ..util.errors import ProviderUnavailable

T = TypeVar("T")


def _is_transient(exc: BaseException) -> bool:
    """Retry only on connection errors and HTTP 5xx, never on 4xx.

    ``_OpenAICompatibleClient`` wraps both connection failures and HTTP 5xx
    into :class:`ProviderUnavailable` before this decorator sees them, so we
    must treat that as transient too – otherwise nothing would ever retry and
    the mode-level ``fallback_stt`` path (which only catches
    ``ProviderUnavailable``) would never trigger on 5xx.
    """
    if isinstance(exc, ProviderUnavailable):
        return True
    if isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.RemoteProtocolError,
            httpx.NetworkError,
        ),
    ):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return 500 <= exc.response.status_code < 600
    return False


def with_retry(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    """Decorator: retry async ``func`` up to 3 times with 1/2/4 s backoff.

    Retries are limited to connection errors and HTTP 5xx. 4xx errors and any
    other exception propagate immediately, so authentication failures and
    invalid-request bugs surface fast.
    """

    @wraps(func)
    async def wrapper(*args: object, **kwargs: object) -> T:
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=1, max=4),
                retry=retry_if_exception(_is_transient),
                reraise=True,
            ):
                with attempt:
                    return await func(*args, **kwargs)
        except RetryError as exc:  # safety net; reraise=True usually unwraps
            raise exc.last_attempt.exception() from exc
        raise RuntimeError("unreachable")  # pragma: no cover

    return wrapper
