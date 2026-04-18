"""Liveness probe."""

from __future__ import annotations

from fastapi import APIRouter

from .. import __version__
from ..schemas import HealthResponse

router = APIRouter()


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)
