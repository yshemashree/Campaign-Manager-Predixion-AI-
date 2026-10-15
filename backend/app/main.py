"""API service entrypoint.

`create_app()` builds the FastAPI app. Connections to Postgres and Redis are opened when the
app starts and closed when it stops (the lifespan below). Tests can build the app without
starting it and plug in their own health checks.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.api import health
from app.api.middleware import RequestContextMiddleware
from app.api.v1 import (
    agents,
    auth,
    campaigns,
    contacts,
    events,
    organizations,
    users,
    webhooks,
    workspaces,
)
from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_session_factory, ping_database
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.redis import create_redis, ping_redis
from app.engine.gate import Gate

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    engine = create_engine(settings)
    redis = create_redis(settings)

    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.redis = redis
    app.state.gate = Gate(redis, settings)
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
        version="0.2.0",
        description=(
            "Outbound voice campaigns: organisations, agents, cohorts, scheduling, retries, "
            "and per-organisation limits on concurrent calls and calls per second. "
            "Authenticate with POST /api/v1/auth/login, then send `Authorization: Bearer <token>`."
        ),
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.health_checks = {}

    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    app.include_router(health.router)

    v1 = APIRouter(prefix="/api/v1")
    for module in (
        auth,
        organizations,
        workspaces,
        users,
        agents,
        campaigns,
        contacts,
        events,
        webhooks,
    ):
        v1.include_router(module.router)
    app.include_router(v1)
    return app


app = create_app()
