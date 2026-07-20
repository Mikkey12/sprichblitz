from __future__ import annotations

import httpx
import pytest

from sprichblitz_backend.providers.retry import _is_transient, with_retry


def _http_status(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(code, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_5xx_is_transient() -> None:
    assert _is_transient(_http_status(500)) is True
    assert _is_transient(_http_status(502)) is True
    assert _is_transient(_http_status(599)) is True


def test_4xx_is_not_transient() -> None:
    assert _is_transient(_http_status(400)) is False
    assert _is_transient(_http_status(401)) is False
    assert _is_transient(_http_status(404)) is False


def test_connection_error_is_transient() -> None:
    assert _is_transient(httpx.ConnectError("boom")) is True
    assert _is_transient(httpx.ReadTimeout("boom")) is True


def test_other_exception_not_transient() -> None:
    assert _is_transient(ValueError("boom")) is False


@pytest.mark.asyncio
async def test_with_retry_retries_5xx_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mit ungeduldigem Backoff: erste zwei Versuche schlagen 5xx, dritter klappt."""
    # Patch wait so the test does not actually sleep.
    from tenacity import wait_none

    monkeypatch.setattr(
        "sprichblitz_backend.providers.retry.wait_exponential",
        lambda *a, **k: wait_none(),
    )

    counter = {"n": 0}

    @with_retry
    async def fn() -> str:
        counter["n"] += 1
        if counter["n"] < 3:
            raise _http_status(503)
        return "ok"

    assert await fn() == "ok"
    assert counter["n"] == 3


@pytest.mark.asyncio
async def test_with_retry_does_not_retry_4xx(monkeypatch: pytest.MonkeyPatch) -> None:
    from tenacity import wait_none

    monkeypatch.setattr(
        "sprichblitz_backend.providers.retry.wait_exponential",
        lambda *a, **k: wait_none(),
    )

    counter = {"n": 0}

    @with_retry
    async def fn() -> str:
        counter["n"] += 1
        raise _http_status(400)

    with pytest.raises(httpx.HTTPStatusError):
        await fn()
    assert counter["n"] == 1
