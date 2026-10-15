"""Worker service entrypoint: `python -m app.worker`.

Runs three things side by side:
    heartbeat   proves the process is alive and connected (used by the container healthcheck)
    scheduler   the once-a-second reconcile loop (only the leader acts)
    dispatcher  N slots that place calls

Shutdown is graceful: on SIGTERM (docker stop) or Ctrl+C the loops finish their current step
and close connections, instead of being killed mid-way.
"""

import asyncio
import contextlib
import os
import signal
import socket
import time
from pathlib import Path

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_session_factory, ping_database
from app.core.logging import configure_logging, get_logger
from app.core.redis import create_redis, ping_redis
from app.engine.dispatcher import Dispatcher
from app.engine.gate import Gate
from app.engine.sarvam_client import SarvamClient
from app.engine.scheduler import Scheduler

log = get_logger("worker")


def worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


async def heartbeat(
    settings: Settings, engine: AsyncEngine, redis: "Redis", wid: str, stop: asyncio.Event
) -> None:
    heartbeat_file = Path(settings.worker_heartbeat_file)
    interval = settings.worker_heartbeat_interval_s
    try:
        while not stop.is_set():
            try:
                await ping_database(engine)
                await ping_redis(redis)
                # Live workers are visible in Redis; the key expires if this worker dies.
                ttl_ms = max(1000, int(interval * 3 * 1000))
                await redis.set(f"worker:heartbeat:{wid}", int(time.time()), px=ttl_ms)
                await asyncio.to_thread(heartbeat_file.write_text, str(time.time()))
                log.debug("heartbeat", worker_id=wid)
            except Exception as exc:
                # Not fatal: dependencies may be restarting. The container healthcheck
                # turns unhealthy if this keeps failing, because the file goes stale.
                log.warning("heartbeat_failed", worker_id=wid, error=repr(exc))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=interval)
    finally:
        with contextlib.suppress(Exception):
            await redis.delete(f"worker:heartbeat:{wid}")


async def run(settings: Settings, stop: asyncio.Event, *, engine_loops: bool = True) -> None:
    engine = create_engine(settings)
    redis = create_redis(settings)
    factory = create_session_factory(engine)
    gate = Gate(redis, settings)
    sarvam = SarvamClient(settings)
    wid = worker_id()
    log.info("worker_started", worker_id=wid, slots=settings.dispatch_slots)

    tasks = [asyncio.create_task(heartbeat(settings, engine, redis, wid, stop))]
    if engine_loops:
        tasks.append(asyncio.create_task(Scheduler(settings, factory, redis, gate, wid).run(stop)))
        tasks.append(
            asyncio.create_task(Dispatcher(settings, factory, redis, gate, sarvam, wid).run(stop))
        )
    try:
        await stop.wait()
    finally:
        await asyncio.gather(*tasks, return_exceptions=True)
        await sarvam.aclose()
        await redis.aclose()
        await engine.dispose()
        log.info("worker_stopped", worker_id=wid)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    await run(settings, stop)


if __name__ == "__main__":
    asyncio.run(main())
