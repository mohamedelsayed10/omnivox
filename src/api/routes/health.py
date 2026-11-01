"""Liveness endpoint. Makes no external calls."""

import time

from fastapi import APIRouter, Request

from config.settings import Settings
from src import __version__
from src.api.schemas.responses import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, status_code=200)
async def health(request: Request) -> HealthResponse:
    """Report that the process is up."""
    settings: Settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        service=settings.APP_NAME,
        version=__version__,
        env=settings.APP_ENV,
        uptime_seconds=round(time.monotonic() - request.app.state.started_at, 3),
    )
