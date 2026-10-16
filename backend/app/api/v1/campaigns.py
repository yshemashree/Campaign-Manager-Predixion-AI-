"""Campaigns: create, edit, duplicate, lifecycle actions, live stats."""

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import GateDep, RedisDep, SessionDep, TenantDep
from app.core.errors import Conflict, Unprocessable
from app.domain.states import EDIT_ALLOWED, CampaignStatus
from app.domain.windows import CallingWindow, next_allowed, window_end
from app.models import CallAttempt, Campaign, Contact
from app.schemas.campaigns import (
    CampaignCreate,
    CampaignOut,
    CampaignStats,
    CampaignUpdate,
    StatusAction,
)
from app.services import lifecycle, scope

router = APIRouter(tags=["campaigns"])


def _check_numbers(requested: list[str] | None, available: list[str]) -> list[str]:
    if requested is None:
        return list(available)
    if not requested:
        raise Unprocessable("Pick at least one caller number")
    unknown = [n for n in requested if n not in available]
    if unknown:
        raise Unprocessable(f"Not on this connection: {', '.join(unknown)}")
    return requested


async def _contact_counts(
    session: AsyncSession, campaign_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, int]]:
    counts: dict[uuid.UUID, dict[str, int]] = defaultdict(dict)
    if campaign_ids:
        rows = await session.execute(
            select(Contact.campaign_id, Contact.status, func.count())
            .where(Contact.campaign_id.in_(campaign_ids))
            .group_by(Contact.campaign_id, Contact.status)
        )
        for campaign_id, status_, count in rows:
            counts[campaign_id][status_] = count
    return counts


async def _out(session: AsyncSession, campaign: Campaign) -> CampaignOut:
    counts = await _contact_counts(session, [campaign.id])
    out = CampaignOut.model_validate(campaign)
    out.contact_counts = counts[campaign.id]
    return out


@router.get("/workspaces/{workspace_id}/campaigns", response_model=list[CampaignOut])
async def list_campaigns(
    workspace_id: uuid.UUID,
    ctx: TenantDep,
    session: SessionDep,
    status_filter: CampaignStatus | None = Query(default=None, alias="status"),
) -> list[CampaignOut]:
    ws = await scope.get_workspace(session, ctx, workspace_id)
    query = select(Campaign).where(Campaign.workspace_id == ws.id).order_by(Campaign.id.desc())
    if status_filter:
        query = query.where(Campaign.status == status_filter)
    campaigns = list(await session.scalars(query))
    counts = await _contact_counts(session, [c.id for c in campaigns])
    items = [CampaignOut.model_validate(c) for c in campaigns]
    for item in items:
        item.contact_counts = counts[item.id]
    return items


@router.post(
    "/workspaces/{workspace_id}/campaigns",
    response_model=CampaignOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_campaign(
    workspace_id: uuid.UUID, body: CampaignCreate, ctx: TenantDep, session: SessionDep
) -> CampaignOut:
    ws = await scope.get_workspace(session, ctx, workspace_id)
    agent = await scope.get_agent(session, ctx, body.agent_id)
    conn = await scope.get_connection(session, ctx, body.connection_id)
    if agent.workspace_id != ws.id or conn.workspace_id != ws.id:
        raise Unprocessable("The agent and the connection must belong to this workspace")
    campaign = Campaign(
        org_id=ws.org_id,
        workspace_id=ws.id,
        agent_id=agent.id,
        connection_id=conn.id,
        name=body.name,
        status=CampaignStatus.DRAFT,
        attempts_per_second=body.attempts_per_second,
        caller_numbers=_check_numbers(body.caller_numbers, conn.caller_numbers),
        retry_policy=body.retry_policy.model_dump(),
        calling_window=body.calling_window.model_dump(),
        start_at=body.start_at,
        end_at=body.end_at,
        app_overrides=body.app_overrides.model_dump(exclude_none=True),
        created_by=ctx.user.id,
    )
    session.add(campaign)
    await session.commit()
    return CampaignOut.model_validate(campaign)


@router.get("/campaigns/{campaign_id}", response_model=CampaignOut)
async def get_campaign(campaign_id: uuid.UUID, ctx: TenantDep, session: SessionDep) -> CampaignOut:
    return await _out(session, await scope.get_campaign(session, ctx, campaign_id))


@router.patch("/campaigns/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: uuid.UUID, body: CampaignUpdate, ctx: TenantDep, session: SessionDep, gate: GateDep
) -> CampaignOut:
    campaign = await scope.get_campaign(session, ctx, campaign_id)
    if campaign.status not in EDIT_ALLOWED:
        raise Conflict(f"Pause the campaign before editing it (it is {campaign.status})")
    changes = body.model_dump(exclude_unset=True)
    draft_only = [k for k in ("agent_id", "connection_id", "caller_numbers") if k in changes]
    if draft_only and campaign.status != CampaignStatus.DRAFT:
        raise Conflict(
            f"{', '.join(draft_only)} can only be changed while the campaign is a draft"
            f" (it is {campaign.status})"
        )
    for key in ("agent_id", "connection_id"):
        if key in changes and changes[key] is None:
            raise Unprocessable(f"{key} can't be empty")
    if "agent_id" in changes:
        agent = await scope.get_agent(session, ctx, changes["agent_id"])
        if agent.workspace_id != campaign.workspace_id:
            raise Unprocessable("The agent must belong to the campaign's workspace")
    if "connection_id" in changes or "caller_numbers" in changes:
        conn = await scope.get_connection(
            session, ctx, changes.get("connection_id", campaign.connection_id)
        )
        if conn.workspace_id != campaign.workspace_id:
            raise Unprocessable("The connection must belong to the campaign's workspace")
        # A new connection without explicit numbers gets all of its numbers, as on create.
        changes["caller_numbers"] = _check_numbers(
            changes.get("caller_numbers"), conn.caller_numbers
        )
    if "app_overrides" in changes and changes["app_overrides"] is not None:
        changes["app_overrides"] = {k: v for k, v in changes["app_overrides"].items() if v}
    for key, value in changes.items():
        setattr(campaign, key, value)
    start_at, end_at = campaign.start_at, campaign.end_at
    if start_at and end_at and end_at <= start_at:
        raise Unprocessable("end_at must be after start_at")
    await session.commit()
    await lifecycle.sync_gate(gate, campaign)
    return await _out(session, campaign)


@router.post(
    "/campaigns/{campaign_id}/duplicate",
    response_model=CampaignOut,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_campaign(
    campaign_id: uuid.UUID, ctx: TenantDep, session: SessionDep
) -> CampaignOut:
    """A new draft with the same settings. Contacts and start/end times are not copied."""
    source = await scope.get_campaign(session, ctx, campaign_id)
    suffix = " (copy)"
    campaign = Campaign(
        org_id=source.org_id,
        workspace_id=source.workspace_id,
        agent_id=source.agent_id,
        connection_id=source.connection_id,
        name=source.name[: 200 - len(suffix)] + suffix,
        status=CampaignStatus.DRAFT,
        attempts_per_second=source.attempts_per_second,
        caller_numbers=list(source.caller_numbers),
        retry_policy=dict(source.retry_policy),
        calling_window=dict(source.calling_window),
        app_overrides=dict(source.app_overrides),
        created_by=ctx.user.id,
    )
    session.add(campaign)
    await session.commit()
    return CampaignOut.model_validate(campaign)


@router.delete("/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(campaign_id: uuid.UUID, ctx: TenantDep, session: SessionDep) -> Response:
    campaign = await scope.get_campaign(session, ctx, campaign_id)
    if campaign.status != CampaignStatus.DRAFT:
        raise Conflict("Only draft campaigns can be deleted; stop it instead")
    await session.delete(campaign)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/campaigns/{campaign_id}/status", response_model=CampaignOut)
async def change_status(
    campaign_id: uuid.UUID,
    body: StatusAction,
    ctx: TenantDep,
    session: SessionDep,
    gate: GateDep,
    redis: RedisDep,
) -> CampaignOut:
    """Start, pause, resume or stop. Repeating an action that already happened is a no-op."""
    campaign = await scope.get_campaign(session, ctx, campaign_id)
    campaign = await lifecycle.apply_action(session, gate, redis, campaign, body.action)
    return await _out(session, campaign)


async def campaign_stats(session: Any, campaign: Campaign) -> CampaignStats:
    rows = await session.execute(
        select(Contact.status, func.count())
        .where(Contact.campaign_id == campaign.id)
        .group_by(Contact.status)
    )
    by_status = {status_: count for status_, count in rows}
    attempts = await session.scalar(
        select(func.count()).select_from(CallAttempt).where(CallAttempt.campaign_id == campaign.id)
    )
    now = datetime.now(UTC)
    cw = CallingWindow.from_dict(campaign.calling_window)
    closes = window_end(now, cw, campaign.start_at, campaign.end_at)
    opens = None if closes else next_allowed(now, cw, campaign.start_at, campaign.end_at)
    return CampaignStats(
        campaign_id=campaign.id,
        status=campaign.status,
        total=sum(by_status.values()),
        by_status=by_status,
        attempts_total=attempts or 0,
        in_window=closes is not None,
        window_closes_at=closes,
        next_window_opens_at=opens,
    )


@router.get("/campaigns/{campaign_id}/stats", response_model=CampaignStats)
async def get_stats(campaign_id: uuid.UUID, ctx: TenantDep, session: SessionDep) -> CampaignStats:
    campaign = await scope.get_campaign(session, ctx, campaign_id)
    return await campaign_stats(session, campaign)
