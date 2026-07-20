from __future__ import annotations

import time

from fastapi import APIRouter, Request

from .. import __version__
from ..models.api import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    started_at: float = request.app.state.started_at
    return HealthResponse(
        status="ok",
        version=__version__,
        uptime_seconds=int(time.time() - started_at),
    )
