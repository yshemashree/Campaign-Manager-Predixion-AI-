"""Tests against a real Postgres and Redis.

They run in CI (which starts both as services) and locally after `make up`. When the
databases aren't reachable they are skipped rather than failed.
"""

import asyncio
from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.core.db import create_engine, ping_database
from app.core.redis import create_redis, ping_redis
from app.main import create_app
from app.worker import run as run_worker
from app.worker import worker_id

pytestmark = pytest.mark.integration


@pytest.fixture
async def real_settings(tmp_path: Path) -> Settings:
    s = Settings(
        app_env="test",
        worker_heartbeat_interval_s=0.1,
        worker_heartbeat_file=str(tmp_path / "heartbeat"),
    )
    engine, redis = create_engine(s), create_redis(s)
    try:
        await asyncio.wait_for(ping_database(engine), 2)
        await asyncio.wait_for(ping_redis(redis), 2)
    except Exception as exc:
        pytest.skip(f"Postgres/Redis not reachable ({exc!r}); run `make up` first")
    finally:
        await redis.aclose()
        await engine.dispose()
    return s


async def test_readyz_is_ready_with_real_dependencies(real_settings: Settings) -> None:
    app = create_app(real_settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/readyz")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ready", "checks": {"database": "ok", "redis": "ok"}}


async def test_worker_heartbeats_then_cleans_up_on_stop(real_settings: Settings) -> None:
    stop = asyncio.Event()
    task = asyncio.create_task(run_worker(real_settings, stop))
    heartbeat_file = Path(real_settings.worker_heartbeat_file)
    redis = create_redis(real_settings)
    key = f"worker:heartbeat:{worker_id()}"
    try:
        for _ in range(50):  # up to ~5 s for the first beat
            if await asyncio.to_thread(heartbeat_file.exists):
                break
            await asyncio.sleep(0.1)
        assert await asyncio.to_thread(heartbeat_file.exists)
        assert await redis.exists(key) == 1

        stop.set()
        await asyncio.wait_for(task, timeout=5)

        assert await redis.exists(key) == 0  # a stopped worker removes itself
    finally:
        stop.set()
        await redis.aclose()
