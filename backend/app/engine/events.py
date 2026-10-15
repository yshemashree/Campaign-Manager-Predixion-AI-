"""Live events over Redis pub/sub.

Events are published after the database commit, so the UI never shows a change that was
rolled back. Pub/sub can drop messages, so the UI also refreshes a snapshot periodically
("push for speed, pull for truth").
"""

import contextlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis


def campaign_channel(campaign_id: uuid.UUID | str) -> str:
    return f"ev:campaign:{campaign_id}"


async def publish(redis: "Redis", campaign_id: uuid.UUID | str, event: dict[str, Any]) -> None:
    event = {"at": datetime.now(UTC).isoformat(), **event}
    # Live updates are best-effort: never fail the real work because of them.
    with contextlib.suppress(Exception):
        await redis.publish(campaign_channel(campaign_id), json.dumps(event, default=str))
