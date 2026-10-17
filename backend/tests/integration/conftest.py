"""Fixtures for tests that need real Postgres and Redis.

They use a separate database (`<name>_test`) and Redis DB 15, wiped before every test, so
they never touch local demo data. Skipped automatically when Postgres/Redis aren't running.
"""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.db import create_engine, create_session_factory
from app.main import create_app
from app.seed import seed


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "integration" in str(item.path):
            item.add_marker(pytest.mark.integration)


BACKEND_DIR = Path(__file__).resolve().parents[2]
BASE = Settings()
TEST_DB_URL = BASE.database_url.rsplit("/", 1)[0] + "/campaign_manager_test"
TEST_REDIS_URL = BASE.redis_url.rsplit("/", 1)[0] + "/15"

TABLES = (
    "webhook_events, call_attempts, contacts, cohorts, campaigns, connections, agents,"
    " workspace_members, users, workspaces, organizations"
)


def _plain(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _prepare_database() -> None:
    admin_url = _plain(BASE.database_url).rsplit("/", 1)[0] + "/postgres"
    conn = await asyncpg.connect(admin_url, timeout=3)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = 'campaign_manager_test'"
        )
        if not exists:
            await conn.execute("CREATE DATABASE campaign_manager_test")
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def test_database() -> str:
    try:
        asyncio.run(_prepare_database())
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Postgres not reachable ({exc!r}); run `make up` first")
    env = {**os.environ, "DATABASE_URL": TEST_DB_URL}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        capture_output=True,
    )
    return TEST_DB_URL


@pytest.fixture
def settings(test_database: str) -> Settings:
    return Settings(
        app_env="test",
        database_url=test_database,
        redis_url=TEST_REDIS_URL,
        scheduler_tick_s=0.2,
        dispatch_slots=6,
        webhook_timeout_s=60,
        lease_seconds=30,
        seed_demo_data=False,
    )


@pytest.fixture
async def factory(settings: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(settings)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    yield create_session_factory(engine)
    await engine.dispose()


@pytest.fixture
async def redis(settings: Settings) -> AsyncIterator[Redis]:
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"Redis not reachable ({exc!r})")
    await client.flushdb()
    yield client
    await client.aclose()


@pytest.fixture
async def app(
    settings: Settings, factory: async_sessionmaker[AsyncSession], redis: Redis
) -> AsyncIterator[FastAPI]:
    async with factory() as session:
        await seed(session, settings)
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as c:
        yield c


async def login(client: httpx.AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def superadmin(client: httpx.AsyncClient, settings: Settings) -> dict[str, str]:
    return await login(client, settings.seed_superadmin_email, settings.seed_superadmin_password)


async def make_org(
    client: httpx.AsyncClient,
    superadmin: dict[str, str],
    name: str,
    *,
    concurrent: int = 5,
    cps: int = 5,
) -> dict[str, Any]:
    """An org with an admin, a workspace with credentials, an agent and a connection."""
    email = f"admin@{name.lower().replace(' ', '')}.example.com"
    resp = await client.post(
        "/api/v1/organizations",
        headers=superadmin,
        json={
            "name": name,
            "sarvam_org_id": f"sv-{name.lower().replace(' ', '')}",
            "max_concurrent_calls": concurrent,
            "max_calls_per_second": cps,
            "admin_email": email,
            "admin_password": "password123",
        },
    )
    assert resp.status_code == 201, resp.text
    org = resp.json()
    admin = await login(client, email, "password123")
    ws = (
        await client.post(
            "/api/v1/workspaces",
            headers=admin,
            json={"name": "Main", "sarvam_workspace_id": "ws-main", "sarvam_api_key": "key-1234"},
        )
    ).json()
    agent = (
        await client.post(
            f"/api/v1/workspaces/{ws['id']}/agents",
            headers=admin,
            json={
                "name": "Reminder",
                "app_id": "app-1",
                "app_version": 3,
                "variables": [
                    {"name": "customer_name", "type": "string", "required": True},
                    {"name": "emi_amount", "type": "number", "required": True},
                ],
            },
        )
    ).json()
    conn = (
        await client.post(
            f"/api/v1/workspaces/{ws['id']}/connections",
            headers=admin,
            json={
                "name": "Line",
                "connection_id": "conn-1",
                "caller_numbers": ["+918069000001", "+918069000002"],
            },
        )
    ).json()
    return {"org": org, "admin": admin, "ws": ws, "agent": agent, "conn": conn}


ALWAYS_OPEN = {"timezone": "UTC", "days": [1, 2, 3, 4, 5, 6, 7], "start": "00:00", "end": "23:59"}


def csv_rows(n: int, start: int = 0) -> str:
    lines = ["phone_number,lead_id,customer_name,emi_amount"]
    for i in range(start, start + n):
        lines.append(f"+9198{76000000 + i},lead-{i},Customer {i},{1000 + i}")
    return "\n".join(lines) + "\n"
