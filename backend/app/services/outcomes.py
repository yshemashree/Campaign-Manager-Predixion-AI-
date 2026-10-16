"""Finishing attempts: from webhooks, rejected requests and the "lost" timeout.

Webhooks are stored first (one quick insert, deduplicated), then processed. If processing
fails, the stored event is retried by the scheduler's sweeper, so nothing is lost.
"""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.ids import new_id
from app.core.logging import get_logger
from app.engine import events, repo
from app.engine.gate import Gate
from app.models import WebhookEvent

log = get_logger("outcomes")


async def after_outcome(
    redis: "Redis", gate: Gate, applied: repo.OutcomeApplied, ref: uuid.UUID
) -> None:
    """Free the concurrency place and phone lock, then tell the UI."""
    await gate.release(applied.org_id, ref, applied.phone)
    await events.publish(
        redis,
        applied.campaign_id,
        {
            "type": "contact.updated",
            "contact_id": str(applied.contact_id),
            "attempt_status": applied.attempt_status,
            "status": applied.contact_status,
            "attempts_made": applied.attempts_made,
            "next_attempt_at": events.iso(applied.next_attempt_at),
            "last_outcome": applied.last_outcome,
            "updated_at": events.iso(applied.updated_at),
        },
    )


async def finish(
    factory: async_sessionmaker[AsyncSession],
    gate: Gate,
    redis: "Redis",
    *,
    attempt_ref: uuid.UUID,
    forced_outcome: str,
    reason: str | None = None,
) -> repo.OutcomeApplied | None:
    async with factory() as session:
        applied = await repo.apply_outcome(
            session, attempt_ref=attempt_ref, forced_outcome=forced_outcome, failure_reason=reason
        )
        await session.commit()
    if applied:
        await after_outcome(redis, gate, applied, attempt_ref)
    return applied


def _extract(payload: dict[str, Any]) -> dict[str, Any]:
    config = payload.get("webhook_config") or {}
    metadata = config.get("metadata") or payload.get("metadata") or {}
    duration = payload.get("duration")
    try:
        duration = int(float(duration)) if duration is not None else None
    except (TypeError, ValueError):
        duration = None
    return {
        "attempt_ref": metadata.get("attempt_ref"),
        "sig": metadata.get("sig"),
        "status": payload.get("status"),
        "duration": duration,
        "failure_reason": payload.get("failure_reason"),
        "provider_attempt_id": payload.get("attempt_id"),
    }


def parse(payload: dict[str, Any]) -> dict[str, Any]:
    return _extract(payload)


async def store_event(
    session: AsyncSession, payload: dict[str, Any], attempt_ref: uuid.UUID
) -> uuid.UUID | None:
    """Insert the raw event. None means we've seen this exact event before."""
    fields = _extract(payload)
    key_src = (
        f"{attempt_ref}|{fields['status']}|{fields['duration']}|{fields['provider_attempt_id']}"
    )
    dedupe_key = hashlib.sha256(key_src.encode()).hexdigest()
    event_id = new_id()
    inserted = await session.execute(
        insert(WebhookEvent)
        .values(id=event_id, dedupe_key=dedupe_key, attempt_ref=attempt_ref, payload=payload)
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(WebhookEvent.id)
    )
    row = inserted.first()
    await session.commit()
    return row[0] if row else None


async def process_event(
    factory: async_sessionmaker[AsyncSession], gate: Gate, redis: "Redis", event_id: uuid.UUID
) -> None:
    async with factory() as session:
        event = await session.scalar(
            select(WebhookEvent)
            .where(WebhookEvent.id == event_id)
            .with_for_update(skip_locked=True)
        )
        if event is None or event.processed_at is not None or event.attempt_ref is None:
            return
        fields = _extract(event.payload)
        try:
            applied = await repo.apply_outcome(
                session,
                attempt_ref=event.attempt_ref,
                sarvam_status=fields["status"],
                duration_s=fields["duration"],
                failure_reason=fields["failure_reason"],
                provider_attempt_id=fields["provider_attempt_id"],
            )
            event.processed_at = datetime.now(UTC)
            event.error = None
            await session.commit()
        except Exception as exc:
            await session.rollback()
            await session.execute(
                text("UPDATE webhook_events SET error = :e WHERE id = :id"),
                {"e": repr(exc)[:1000], "id": event_id},
            )
            await session.commit()
            log.exception("webhook_processing_failed", event_id=str(event_id))
            return
    if applied:
        await after_outcome(redis, gate, applied, event.attempt_ref)
