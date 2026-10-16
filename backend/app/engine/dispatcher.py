"""Dispatch slots: the loops that place calls.

Each worker runs `dispatch_slots` copies of `_slot()`. One iteration:

    1. pick a runnable campaign (round-robin)
    2. reserve a send slot in Redis       (state, window, pacing, org concurrency, atomically)
    3. claim the next due contact in PG   (FOR UPDATE SKIP LOCKED, attempt row reserved)
    4. wait for the slot time
    5. fire: last atomic check + send-intent marker
    6. call Sarvam, record the result

Nothing is queued ahead of time: if the campaign is paused or the window closes at any point,
step 2 or 5 refuses and the contact goes back untouched.
"""

import asyncio
import contextlib
import random
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.security import decrypt_secret
from app.domain.states import AttemptStatus, CampaignStatus
from app.engine import events, repo
from app.engine.gate import RUNNABLE_KEY, Gate
from app.engine.sarvam_client import CallResult, CallTarget, SarvamClient, build_payload
from app.models import Agent, Campaign, Connection, Organization, Workspace
from app.services import lifecycle, outcomes

log = get_logger("dispatcher")

TARGET_TTL_S = 5.0
UNKNOWN_STREAK_COOLDOWN = 5  # this many maybe-sent failures in a row: pause the org briefly
REJECT_STREAK_PAUSE = 10  # this many 4xx rejections in a row: auto-pause the campaign


class Dispatcher:
    def __init__(
        self,
        settings: Settings,
        factory: async_sessionmaker[AsyncSession],
        redis: "Redis",
        gate: Gate,
        sarvam: SarvamClient,
        worker_id: str,
    ) -> None:
        self.settings = settings
        self.factory = factory
        self.redis = redis
        self.gate = gate
        self.sarvam = sarvam
        self.worker_id = worker_id
        self.runnable: list[tuple[uuid.UUID, uuid.UUID]] = []
        self._cursor = random.randrange(1_000_000)  # workers start at different campaigns
        self._cool: dict[uuid.UUID, float] = {}
        self._targets: dict[uuid.UUID, tuple[float, CallTarget | None]] = {}
        self._unknown_streak: dict[uuid.UUID, int] = defaultdict(int)
        self._reject_streak: dict[uuid.UUID, int] = defaultdict(int)
        self.sent = 0

    # ----- runnable campaigns -----

    async def refresh_runnable(self) -> None:
        raw = await self.redis.hgetall(RUNNABLE_KEY)
        self.runnable = [(uuid.UUID(str(c)), uuid.UUID(str(o))) for c, o in raw.items()]

    def _pick(self) -> tuple[uuid.UUID, uuid.UUID] | None:
        now = time.monotonic()
        n = len(self.runnable)
        for _ in range(n):
            self._cursor = (self._cursor + 1) % n
            campaign_id, org_id = self.runnable[self._cursor]
            if self._cool.get(campaign_id, 0) <= now:
                return campaign_id, org_id
        return None

    def _cool_down(self, campaign_id: uuid.UUID, ms: int) -> None:
        self._cool[campaign_id] = time.monotonic() + max(20, min(ms, 2000)) / 1000

    # ----- campaign call settings (cached briefly) -----

    async def _target(self, campaign_id: uuid.UUID) -> CallTarget | None:
        cached = self._targets.get(campaign_id)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        target = await self._load_target(campaign_id)
        self._targets[campaign_id] = (time.monotonic() + TARGET_TTL_S, target)
        return target

    async def _load_target(self, campaign_id: uuid.UUID) -> CallTarget | None:
        async with self.factory() as s:
            row = (
                await s.execute(
                    select(Campaign, Agent, Connection, Workspace, Organization)
                    .join(Agent, Agent.id == Campaign.agent_id)
                    .join(Connection, Connection.id == Campaign.connection_id)
                    .join(Workspace, Workspace.id == Campaign.workspace_id)
                    .join(Organization, Organization.id == Campaign.org_id)
                    .where(Campaign.id == campaign_id)
                )
            ).first()
        if row is None:
            return None
        campaign, agent, connection, workspace, org = row
        if not (
            workspace.sarvam_api_key_enc and workspace.sarvam_workspace_id and org.sarvam_org_id
        ):
            return None
        overrides = {
            k: v
            for k, v in {
                "initial_bot_message": agent.initial_bot_message,
                "initial_state_name": agent.initial_state_name,
                **(campaign.app_overrides or {}),
            }.items()
            if v
        }
        return CallTarget(
            campaign_id=campaign.id,
            org_id=campaign.org_id,
            workspace_id=campaign.workspace_id,
            sarvam_org_id=org.sarvam_org_id,
            sarvam_workspace_id=workspace.sarvam_workspace_id,
            api_key=decrypt_secret(self.settings, workspace.sarvam_api_key_enc),
            app_id=agent.app_id,
            app_version=agent.app_version,
            connection_id=connection.connection_id,
            caller_numbers=tuple(campaign.caller_numbers or connection.caller_numbers),
            app_overrides=overrides,
        )

    # ----- auto-pause -----

    async def _auto_pause(self, campaign_ids: list[uuid.UUID], reason: str) -> None:
        async with self.factory() as s:
            for cid in campaign_ids:
                campaign = await s.get(Campaign, cid)
                if campaign is None or campaign.status != CampaignStatus.RUNNING:
                    continue
                if await lifecycle.transition(
                    s,
                    campaign,
                    CampaignStatus.PAUSED,
                    from_status=CampaignStatus.RUNNING,
                    pause_reason=reason,
                    now=datetime.now(UTC),
                ):
                    await s.commit()
                    await s.refresh(campaign)
                    await lifecycle.sync_gate(self.gate, campaign)
                    await events.publish(
                        self.redis,
                        cid,
                        {"type": "campaign.updated", "status": "paused", "pause_reason": reason},
                    )
                    log.warning("campaign_auto_paused", campaign_id=str(cid), reason=reason)

    async def _pause_workspace(self, workspace_id: uuid.UUID, reason: str) -> None:
        async with self.factory() as s:
            ids = list(
                await s.scalars(
                    select(Campaign.id).where(
                        Campaign.workspace_id == workspace_id,
                        Campaign.status == CampaignStatus.RUNNING,
                    )
                )
            )
        await self._auto_pause(ids, reason)

    # ----- the loop -----

    async def run(self, stop: asyncio.Event) -> None:
        slots = [asyncio.create_task(self._slot(stop)) for _ in range(self.settings.dispatch_slots)]
        try:
            while not stop.is_set():
                try:
                    await self.refresh_runnable()
                except Exception as exc:
                    log.warning("runnable_refresh_failed", error=repr(exc))
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=0.5)
        finally:
            for task in slots:
                task.cancel()
            await asyncio.gather(*slots, return_exceptions=True)

    async def _slot(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                worked = await self._dispatch_one()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # one bad iteration must not kill the slot
                log.exception("dispatch_iteration_failed", error=repr(exc))
                worked = False
            if not worked:
                await asyncio.sleep(0.05 + random.random() * 0.1)

    async def _dispatch_one(self) -> bool:
        picked = self._pick()
        if picked is None:
            await asyncio.sleep(0.2)
            return True
        campaign_id, org_id = picked

        target = await self._target(campaign_id)
        if target is None or not target.caller_numbers:
            await self._auto_pause([campaign_id], "missing_credentials")
            self._cool_down(campaign_id, 2000)
            return False

        attempt_ref = new_id()
        grant = await self.gate.reserve(org_id, campaign_id, attempt_ref)
        if not grant.ok:
            self._cool_down(campaign_id, grant.retry_after_ms)
            return False

        from_number = target.caller_numbers[(grant.rr - 1) % len(target.caller_numbers)]
        async with self.factory() as s:
            claim = await repo.claim_next(
                s,
                campaign_id=campaign_id,
                granted_version=int(grant.campaign_ver),
                worker_id=self.worker_id,
                attempt_ref=attempt_ref,
                from_number=from_number,
                lease_s=self.settings.lease_seconds,
            )
        if claim is None:
            await self.gate.refund(org_id, campaign_id, attempt_ref, grant)
            self._cool_down(campaign_id, 500)  # nothing due right now
            return False

        # Build the request now, so nothing slow sits between the final check and the send.
        payload = build_payload(
            self.settings,
            target,
            attempt_ref=attempt_ref,
            phone=claim.phone,
            lead_id=claim.lead_id,
            variables=claim.variables,
            from_number=from_number,
        )
        await asyncio.sleep(max(grant.delay_ms, 0) / 1000)
        verdict = await self.gate.fire(org_id, campaign_id, attempt_ref, claim.phone, grant)
        while verdict.reason == "early":
            await asyncio.sleep(verdict.wait_ms / 1000 + 0.001)
            verdict = await self.gate.fire(org_id, campaign_id, attempt_ref, claim.phone, grant)
        if not verdict.ok:
            defer = 300 if verdict.reason == "phone_busy" else 0
            async with self.factory() as s:
                await repo.release(
                    s, contact_id=claim.contact_id, attempt_ref=attempt_ref, defer_s=defer
                )
            await self.gate.release(org_id, attempt_ref, claim.phone)
            return False

        result = await self.sarvam.place_call(target, payload)
        await self._handle_result(target, claim, attempt_ref, result)
        return True

    async def _handle_result(
        self, target: CallTarget, claim: repo.Claim, ref: uuid.UUID, result: CallResult
    ) -> None:
        org_id, campaign_id = target.org_id, target.campaign_id
        if result.kind in ("dispatched", "unknown"):
            status = (
                AttemptStatus.DISPATCHED if result.kind == "dispatched" else AttemptStatus.UNKNOWN
            )
            async with self.factory() as s:
                dispatched = await repo.record_dispatch(
                    s,
                    contact_id=claim.contact_id,
                    attempt_ref=ref,
                    status=status,
                    provider_attempt_id=result.provider_attempt_id,
                    http_status=result.http_status,
                    error=result.error,
                )
            self.sent += 1
            self._reject_streak[campaign_id] = 0
            if result.kind == "unknown":
                self._unknown_streak[org_id] += 1
                if self._unknown_streak[org_id] >= UNKNOWN_STREAK_COOLDOWN:
                    await self.gate.cooldown(org_id, 30_000)
                    self._unknown_streak[org_id] = 0
                log.warning("dispatch_outcome_unknown", attempt_ref=str(ref), error=result.error)
            else:
                self._unknown_streak[org_id] = 0
            if dispatched is None:
                return  # the webhook won the race and has already published the outcome
            await events.publish(
                self.redis,
                campaign_id,
                {
                    "type": "contact.updated",
                    "contact_id": str(claim.contact_id),
                    "status": "in_progress",
                    "attempts_made": claim.attempt_no,
                    "next_attempt_at": events.iso(dispatched.next_attempt_at),
                    "last_outcome": dispatched.last_outcome,
                    "updated_at": events.iso(dispatched.updated_at),
                },
            )
            return

        if result.kind == "rejected":
            await outcomes.finish(
                self.factory,
                self.gate,
                self.redis,
                attempt_ref=ref,
                forced_outcome=AttemptStatus.REJECTED,
                reason=f"HTTP {result.http_status}: {result.error}",
            )
            self._reject_streak[campaign_id] += 1
            if self._reject_streak[campaign_id] >= REJECT_STREAK_PAUSE:
                await self._auto_pause([campaign_id], "config_error")
                self._reject_streak[campaign_id] = 0
            return

        # Not placed at all: put the contact back as if nothing happened.
        async with self.factory() as s:
            await repo.release(s, contact_id=claim.contact_id, attempt_ref=ref)
        await self.gate.release(org_id, ref, claim.phone)
        if result.kind == "auth_error":
            await self._pause_workspace(target.workspace_id, "auth_error")
        elif result.kind == "rate_limited":
            await self.gate.cooldown(org_id, result.retry_after_ms or 1000)
            log.error("sarvam_rate_limited", org_id=str(org_id))
        else:  # not_sent
            await self.gate.cooldown(org_id, 2000)
            log.warning("sarvam_unreachable", error=result.error)
