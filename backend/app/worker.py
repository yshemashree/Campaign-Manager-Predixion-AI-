"""Worker service entrypoint: `python -m app.worker`.

Today it only proves the process is alive and can reach Postgres and Redis (a heartbeat).
The dispatch slots and the scheduler loop are added here in the engine phase.

Shutdown is graceful: on SIGTERM (docker stop) or Ctrl+C the loop finishes its current step
and closes connections, instead of being killed mid-way.
"""

import asyncio
import contextlib
import os
import signal
import socket
import time
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.db import create_engine, ping_database
from app.core.logging import configure_logging, get_logger
from app.core.redis import create_redis, ping_redis

log = get_logger("worker")


def worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


async def run(settings: Settings, stop: asyncio.Event) -> None:
    engine = create_engine(settings)
    redis = create_redis(settings)
    wid = worker_id()
    heartbeat_file = Path(settings.worker_heartbeat_file)
    interval = settings.worker_heartbeat_interval_s
    log.info("worker_started", worker_id=wid)

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
        await redis.delete(f"worker:heartbeat:{wid}")
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
