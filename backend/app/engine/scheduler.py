"""The scheduler: a once-a-second reconcile loop. Only the leader acts.

Every step compares "what should be" with "what is" and fixes the difference, using
conditional SQL and versioned Redis writes. So a missed event or a crashed process is
healed on the next tick, and two schedulers running at once (split brain) can't do harm.
The leader lock only avoids duplicate work; correctness never depends on it.
"""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.logging import get_logger
from app.domain.states import AttemptStatus, CampaignStatus
from app.engine import events, repo
from app.engine.gate import RUNNABLE_KEY, Gate, fires_key
from app.models import Campaign, Organization
from app.services import lifecycle, outcomes

log = get_logger("scheduler")

LEADER_KEY = "scheduler:leader"
LEADER_TTL_MS = 5000
FINALISE_BATCH = 5000
REAP_BATCH = 200


class Scheduler:
    def __init__(
        self,
        settings: Settings,
        factory: async_sessionmaker[AsyncSession],
        redis: "Redis",
        gate: Gate,
        worker_id: str,
    ) -> None:
        self.settings = settings
        self.factory = factory
        self.redis = redis
        self.gate = gate
        self.worker_id = worker_id
        self.is_leader = False
        self._ticks = 0

    async def _lead(self) -> bool:
        if await self.redis.set(LEADER_KEY, self.worker_id, nx=True, px=LEADER_TTL_MS):
            return True
        if await self.redis.get(LEADER_KEY) == self.worker_id:
            await self.redis.pexpire(LEADER_KEY, LEADER_TTL_MS)
            return True
        return False

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                was_leader = self.is_leader
                self.is_leader = await self._lead()
                if self.is_leader and not was_leader:
                    log.info("scheduler_leader", worker_id=self.worker_id)
                if self.is_leader:
                    await self.tick()
            except Exception as exc:
                log.exception("scheduler_tick_failed", error=repr(exc))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self.settings.scheduler_tick_s)
        if self.is_leader and await self.redis.get(LEADER_KEY) == self.worker_id:
            await self.redis.delete(LEADER_KEY)

    async def tick(self) -> None:
        self._ticks += 1
        await self.sync_orgs()
        await self.activate_scheduled()
        await self.finish_campaigns()
        await self.sync_campaigns()
        await self.finalise_closed()
        await self.reap_leases()
        await self.reap_lost()
        await self.sweep_webhooks()
        if self._ticks % 30 == 0:
            await self.trim_fires()

    # 1. org limits -> Redis
    async def sync_orgs(self) -> None:
        async with self.factory() as s:
            orgs = list(await s.scalars(select(Organization)))
        for org in orgs:
            await self.gate.sync_org(
                org.id,
                limit_version=org.limit_version,
                max_cps=org.max_calls_per_second if org.is_active else 0,
                max_concurrent=org.max_concurrent_calls if org.is_active else 0,
            )

    async def _transition_many(
        self, sql: str, params: dict[str, object] | None = None
    ) -> list[uuid.UUID]:
        async with self.factory() as s:
            ids = [row[0] for row in await s.execute(text(sql), params or {})]
            await s.commit()
        for cid in ids:
            async with self.factory() as s:
                campaign = await s.get(Campaign, cid)
                if campaign:
                    await lifecycle.sync_gate(self.gate, campaign)
                    await events.publish(
                        self.redis, cid, {"type": "campaign.updated", "status": campaign.status}
                    )
        return ids

    # 2. scheduled -> running at start_at
    async def activate_scheduled(self) -> None:
        ids = await self._transition_many(
            """
            UPDATE campaigns SET status = 'running', state_version = state_version + 1,
                   started_at = COALESCE(started_at, now()), updated_at = now()
            WHERE status = 'scheduled' AND (start_at IS NULL OR start_at <= now())
            RETURNING id
            """
        )
        for cid in ids:
            log.info("campaign_started", campaign_id=str(cid))

    # 3. running/paused -> completed (end time passed, or every contact finished)
    async def finish_campaigns(self) -> None:
        await self._transition_many(
            """
            UPDATE campaigns SET status = 'completed', state_version = state_version + 1,
                   finished_at = now(), updated_at = now()
            WHERE status IN ('running', 'paused', 'scheduled')
              AND end_at IS NOT NULL AND end_at <= now()
            RETURNING id
            """
        )
        await self._transition_many(
            """
            UPDATE campaigns k SET status = 'completed', state_version = state_version + 1,
                   finished_at = now(), updated_at = now()
            WHERE k.status = 'running'
              AND EXISTS (SELECT 1 FROM contacts c WHERE c.campaign_id = k.id)
              AND NOT EXISTS (SELECT 1 FROM contacts c WHERE c.campaign_id = k.id
                              AND c.status IN ('pending', 'dialing', 'in_progress',
                                               'retry_scheduled'))
            RETURNING id
            """
        )

    # 4. campaign state + window -> Redis gates; publish the runnable set
    async def sync_campaigns(self) -> None:
        now = datetime.now(UTC)
        async with self.factory() as s:
            campaigns = list(
                await s.scalars(
                    select(Campaign).where(
                        Campaign.status.in_(
                            [
                                CampaignStatus.RUNNING,
                                CampaignStatus.PAUSED,
                                CampaignStatus.SCHEDULED,
                            ]
                        )
                    )
                )
            )
            running = [c for c in campaigns if c.status == CampaignStatus.RUNNING]
            due: set[uuid.UUID] = set()
            if running:
                rows = await s.execute(
                    text(
                        "SELECT DISTINCT campaign_id FROM contacts WHERE campaign_id = ANY(:ids)"
                        " AND status IN ('pending', 'retry_scheduled') AND next_attempt_at <= now()"
                    ),
                    {"ids": [c.id for c in running]},
                )
                due = {row[0] for row in rows}
        runnable: dict[str, str] = {}
        for c in campaigns:
            await lifecycle.sync_gate(self.gate, c, now)
            if (
                c.status == CampaignStatus.RUNNING
                and c.id in due
                and lifecycle.window_until_ms(c, now)
            ):
                runnable[str(c.id)] = str(c.org_id)
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.delete(RUNNABLE_KEY)
            if runnable:
                pipe.hset(RUNNABLE_KEY, mapping=cast(Any, runnable))
            await pipe.execute()

    # 5. stopped/completed campaigns: close out contacts still waiting, in batches
    async def finalise_closed(self) -> None:
        async with self.factory() as s:
            result = await s.execute(
                text(
                    """
                    WITH batch AS (
                        SELECT c.id, k.status AS campaign_status FROM contacts c
                        JOIN campaigns k ON k.id = c.campaign_id
                        WHERE k.status IN ('stopped', 'completed')
                          AND c.status IN ('pending', 'retry_scheduled')
                        LIMIT :batch FOR UPDATE OF c SKIP LOCKED
                    )
                    UPDATE contacts c
                    SET status = CASE WHEN batch.campaign_status = 'stopped'
                                      THEN 'cancelled' ELSE 'failed' END,
                        final_reason = CASE WHEN batch.campaign_status = 'stopped'
                                            THEN 'campaign_stopped' ELSE 'campaign_ended' END,
                        updated_at = now()
                    FROM batch WHERE c.id = batch.id
                    RETURNING c.campaign_id
                    """
                ),
                {"batch": FINALISE_BATCH},
            )
            touched = {row[0] for row in result}
            await s.commit()
        for cid in touched:
            await events.publish(self.redis, cid, {"type": "campaign.updated"})

    # 6. workers that died holding a contact
    async def reap_leases(self) -> None:
        async with self.factory() as s:
            rows = (
                await s.execute(
                    text(
                        "SELECT id, org_id, phone_e164, current_attempt_id FROM contacts"
                        " WHERE status = 'dialing' AND lease_expires_at < now() LIMIT :n"
                    ),
                    {"n": REAP_BATCH},
                )
            ).all()
        for contact_id, org_id, phone, ref in rows:
            if ref is None:
                continue
            if await self.gate.revoke(org_id, ref):
                # No send marker: provably never sent, and now it never can be. Free retry.
                async with self.factory() as s:
                    await repo.release(s, contact_id=contact_id, attempt_ref=ref)
                await self.gate.release(org_id, ref, phone)
                log.warning("lease_reaped_unsent", contact_id=str(contact_id))
            else:
                # Marker present: it may have been sent. Never re-send; wait for the webhook.
                async with self.factory() as s:
                    await repo.record_dispatch(
                        s,
                        contact_id=contact_id,
                        attempt_ref=ref,
                        status=AttemptStatus.UNKNOWN,
                        provider_attempt_id=None,
                        http_status=None,
                        error="worker lost before recording",
                    )
                log.warning("lease_reaped_maybe_sent", contact_id=str(contact_id))

    # 7. attempts whose outcome never arrived
    async def reap_lost(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(seconds=self.settings.webhook_timeout_s)
        async with self.factory() as s:
            refs = [
                row[0]
                for row in await s.execute(
                    text(
                        "SELECT id FROM call_attempts WHERE status IN ('dispatched', 'unknown')"
                        " AND COALESCE(dispatched_at, created_at) < :cutoff LIMIT :n"
                    ),
                    {"cutoff": cutoff, "n": REAP_BATCH},
                )
            ]
        for ref in refs:
            await outcomes.finish(
                self.factory,
                self.gate,
                self.redis,
                attempt_ref=ref,
                forced_outcome=AttemptStatus.LOST,
                reason="no outcome received in time",
            )

    # 8. webhooks stored but not processed (API died mid-way, or processing failed)
    async def sweep_webhooks(self) -> None:
        async with self.factory() as s:
            ids = [
                row[0]
                for row in await s.execute(
                    text(
                        "SELECT id FROM webhook_events WHERE processed_at IS NULL"
                        " AND received_at < now() - interval '30 seconds' LIMIT 100"
                    )
                )
            ]
        for event_id in ids:
            await outcomes.process_event(self.factory, self.gate, self.redis, event_id)

    async def trim_fires(self) -> None:
        async with self.factory() as s:
            org_ids = list(await s.scalars(select(Organization.id)))
        cutoff_ms = int((await self.redis.time())[0]) * 1000 - 600_000
        for org_id in org_ids:
            await self.redis.zremrangebyscore(fires_key(org_id), "-inf", cutoff_ms)
