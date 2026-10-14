"""API service entrypoint.

`create_app()` builds the FastAPI app. Connections to Postgres and Redis are opened when the
app starts and closed when it stops (the lifespan below). Tests can build the app without
starting it and plug in their own health checks.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health
from app.api.middleware import RequestContextMiddleware
from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_session_factory, ping_database
from app.core.logging import configure_logging, get_logger
from app.core.redis import create_redis, ping_redis

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    engine = create_engine(settings)
    redis = create_redis(settings)

    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.redis = redis
    app.state.health_checks = {
        "database": lambda: ping_database(engine),
        "redis": lambda: ping_redis(redis),
    }
    log.info("api_started", env=settings.app_env)
    try:
        yield
    finally:
        await redis.aclose()
        await engine.dispose()
        log.info("api_stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    app = FastAPI(
        title="Campaign Manager API",
        version="0.1.0",
        description="Outbound voice campaigns: cohorts, scheduling, retries and per-org limits.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.health_checks = {}

    app.add_middleware(RequestContextMiddleware)
    app.include_router(health.router)
    return app


app = create_app()
