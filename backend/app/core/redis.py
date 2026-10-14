"""Redis client (used for the rate gate, campaign gates, locks and live events)."""

from redis.asyncio import Redis

from app.core.config import Settings


def create_redis(settings: Settings) -> "Redis":
    # decode_responses=True: we get str back instead of bytes.
    return Redis.from_url(settings.redis_url, decode_responses=True)


async def ping_redis(client: "Redis") -> None:
    """Raises if Redis doesn't answer PING."""
    await client.ping()
