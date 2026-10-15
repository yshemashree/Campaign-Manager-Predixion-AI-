"""Sarvam's call-outcome webhook.

Sarvam doesn't document signed webhooks, so we authenticate them ourselves: every call we
place carries `attempt_ref` and an HMAC `sig` in `webhook_config.metadata`, which Sarvam echoes
back. A webhook without a valid signature is rejected.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Request

from app.core.errors import Unauthorized, Unprocessable
from app.core.security import verify_attempt_signature
from app.services import outcomes

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/sarvam")
async def sarvam_webhook(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except ValueError as exc:
        raise Unprocessable("Body must be JSON") from exc
    if not isinstance(payload, dict):
        raise Unprocessable("Body must be a JSON object")

    fields = outcomes.parse(payload)
    ref, sig = fields["attempt_ref"], fields["sig"]
    settings = request.app.state.settings
    if not ref or not sig or not verify_attempt_signature(settings, str(ref), str(sig)):
        raise Unauthorized("Missing or invalid webhook signature")
    try:
        attempt_ref = uuid.UUID(str(ref))
    except ValueError as exc:
        raise Unprocessable("attempt_ref is not a valid id") from exc

    factory = request.app.state.session_factory
    async with factory() as session:
        event_id = await outcomes.store_event(session, payload, attempt_ref)
    if event_id is None:
        return {"status": "duplicate"}
    # Stored and acknowledged even if processing fails below; the sweeper will retry it.
    await outcomes.process_event(factory, request.app.state.gate, request.app.state.redis, event_id)
    return {"status": "ok"}
