from collections.abc import AsyncIterator, Awaitable, Callable

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(app_env="test", health_check_timeout_s=0.2)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    # Built without running the lifespan: no real connections. Tests plug in the
    # health checks they need.
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def passing() -> Callable[[], Awaitable[None]]:
    async def check() -> None:
        return None

    return check


def failing() -> Callable[[], Awaitable[None]]:
    async def check() -> None:
        raise ConnectionError("down")

    return check
