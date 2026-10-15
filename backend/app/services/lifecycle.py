"""Campaign lifecycle: start, pause, resume, stop, and keeping the Redis gate in step.

Order matters: Postgres first (the truth), then the Redis gate, then the response. Once the
API has answered "paused", no new call for that campaign can be sent: the gate denies it,
and the claim query also requires Postgres to say "running".
"""

from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Unprocessable
from app.domain.states import (
    ACTION_ALLOWED_FROM,
    ACTION_ALREADY_DONE,
    CampaignStatus,
    LifecycleAction,
)
from app.domain.windows import CallingWindow, window_end
from app.engine import events
from app.engine.gate import Gate
from app.models import Campaign, Contact


def window_until_ms(campaign: Campaign, now: datetime) -> int:
    """Epoch ms when the current calling window closes; 0 if not running or outside it."""
    if campaign.status != CampaignStatus.RUNNING:
        return 0
    closes = window_end(
        now, CallingWindow.from_dict(campaign.calling_window), campaign.start_at, campaign.end_at
    )
    return int(closes.timestamp() * 1000) if closes else 0


async def sync_gate(gate: Gate, campaign: Campaign, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    return await gate.sync_campaign(
        campaign.org_id,
        campaign.id,
        version=campaign.state_version,
        state=campaign.status,
        attempts_per_second=campaign.attempts_per_second,
        window_until_ms=window_until_ms(campaign, now),
    )


async def transition(
    session: AsyncSession,
    campaign: Campaign,
    to_status: str,
    *,
    from_status: str,
    pause_reason: str | None = None,
    now: datetime,
) -> bool:
    """Compare-and-set status change. False if someone else changed the campaign first."""
    values: dict[str, object] = {
        "status": to_status,
        "state_version": Campaign.state_version + 1,
        "pause_reason": pause_reason,
        "updated_at": now,
    }
    if to_status == CampaignStatus.RUNNING and campaign.started_at is None:
        values["started_at"] = now
    if to_status in (CampaignStatus.STOPPED, CampaignStatus.COMPLETED):
        values["finished_at"] = now
    result = await session.execute(
        update(Campaign)
        .where(Campaign.id == campaign.id, Campaign.status == from_status)
        .values(**values)
        .returning(Campaign.state_version)
    )
    return result.scalar_one_or_none() is not None


async def apply_action(
    session: AsyncSession, gate: Gate, redis: "Redis", campaign: Campaign, action: LifecycleAction
) -> Campaign:
    now = datetime.now(UTC)
    if campaign.status in ACTION_ALREADY_DONE[action]:
        return campaign  # idempotent: repeating an action is not an error
    if campaign.status not in ACTION_ALLOWED_FROM[action]:
        raise Conflict(f"Can't {action.value} a campaign that is {campaign.status}")

    if action == LifecycleAction.START:
        has_contacts = await session.scalar(
            select(exists().where(Contact.campaign_id == campaign.id))
        )
        if not has_contacts:
            raise Unprocessable("Upload a cohort before starting the campaign")
        if campaign.end_at is not None and campaign.end_at <= now:
            raise Unprocessable("The campaign's end time has already passed")

    if action in (LifecycleAction.START, LifecycleAction.RESUME):
        before_start = campaign.start_at is not None and campaign.start_at > now
        target = CampaignStatus.SCHEDULED if before_start else CampaignStatus.RUNNING
        reason = None
    elif action == LifecycleAction.PAUSE:
        target, reason = CampaignStatus.PAUSED, "user"
    else:
        target, reason = CampaignStatus.STOPPED, None

    if not await transition(
        session, campaign, target, from_status=campaign.status, pause_reason=reason, now=now
    ):
        await session.rollback()
        raise Conflict("The campaign changed at the same time; reload and try again")
    await session.commit()
    await session.refresh(campaign)
    await sync_gate(gate, campaign, now)
    await events.publish(
        redis, campaign.id, {"type": "campaign.updated", "status": campaign.status}
    )
    return campaign
