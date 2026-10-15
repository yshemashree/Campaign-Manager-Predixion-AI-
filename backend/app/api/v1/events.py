"""Live campaign updates over Server-Sent Events.

GET /api/v1/campaigns/{id}/events streams:
    event: stats     full counters (on connect, then every 5 s: the "pull for truth" part)
    event: updates   contact/campaign changes, coalesced into one message every 250 ms

Browsers send the token in the Authorization header via a fetch-based SSE client; for quick
manual checks with curl or EventSource, ?access_token=... also works.
"""

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.deps import TenantContext, tenant_from_token
from app.api.v1.campaigns import campaign_stats
from app.core.errors import Unauthorized
from app.engine.events import campaign_channel
from app.services import scope

router = APIRouter(tags=["live"])

FLUSH_EVERY_S = 0.25
SNAPSHOT_EVERY_S = 5.0
HEARTBEAT_EVERY_S = 15.0


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.get("/campaigns/{campaign_id}/events", response_class=StreamingResponse)
async def campaign_events(campaign_id: uuid.UUID, request: Request) -> StreamingResponse:
    auth = request.headers.get("authorization", "")
    token = (
        auth[7:] if auth.lower().startswith("bearer ") else request.query_params.get("access_token")
    )
    if not token:
        raise Unauthorized("Missing bearer token")
    factory = request.app.state.session_factory
    async with factory() as session:
        ctx: TenantContext = await tenant_from_token(session, request.app.state.settings, token)
        await scope.get_campaign(session, ctx, campaign_id)  # 404 unless visible

    async def snapshot() -> dict[str, object]:
        async with factory() as session:
            fresh = await scope.get_campaign(session, ctx, campaign_id)
            return (await campaign_stats(session, fresh)).model_dump(mode="json")

    async def stream() -> AsyncIterator[str]:
        pubsub = request.app.state.redis.pubsub()
        await pubsub.subscribe(campaign_channel(campaign_id))
        try:
            yield _sse("stats", await snapshot())
            pending: dict[str, object] = {}
            last_flush = last_snapshot = last_beat = time.monotonic()
            while not await request.is_disconnected():
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=FLUSH_EVERY_S
                )
                if msg and msg.get("data"):
                    event = json.loads(msg["data"])
                    # Keep only the latest change per contact: bounded message rate.
                    pending[str(event.get("contact_id") or event.get("type"))] = event
                now = time.monotonic()
                if pending and now - last_flush >= FLUSH_EVERY_S:
                    yield _sse("updates", list(pending.values()))
                    pending.clear()
                    last_flush = now
                if now - last_snapshot >= SNAPSHOT_EVERY_S:
                    yield _sse("stats", await snapshot())
                    last_snapshot = now
                if now - last_beat >= HEARTBEAT_EVERY_S:
                    yield ": keep-alive\n\n"
                    last_beat = now
                await asyncio.sleep(0)
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
