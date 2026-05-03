"""FastAPI application factory for feral-registry."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import __version__
from .config import get_settings
from .db import Base, engine
from .routes import (
    auth_github,
    blobs,
    catalog,
    flag,
    health,
    item,
    publish,
    review,
    submissions,
)

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # SQLite dev bootstrap; prod uses alembic.
    settings = get_settings()
    if settings.db_url.startswith("sqlite"):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="feral-registry",
        version=__version__,
        description="Community marketplace for Feral skills, daemons, and MCPs.",
        lifespan=lifespan,
    )
    app.include_router(health.router, prefix=API_PREFIX, tags=["health"])
    app.include_router(publish.router, prefix=API_PREFIX, tags=["publish"])
    app.include_router(catalog.router, prefix=API_PREFIX, tags=["catalog"])
    app.include_router(item.router, prefix=API_PREFIX, tags=["item"])
    app.include_router(flag.router, prefix=API_PREFIX, tags=["flag"])
    app.include_router(auth_github.router, prefix=API_PREFIX, tags=["auth"])
    app.include_router(blobs.router, prefix=API_PREFIX, tags=["blobs"])
    app.include_router(review.router, prefix=API_PREFIX, tags=["review"])
    app.include_router(submissions.router, prefix=API_PREFIX, tags=["submissions"])
    return app


app = create_app()
