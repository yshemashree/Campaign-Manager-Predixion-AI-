"""Load records through the tenant check. Anything not visible to the caller is a 404."""

import uuid
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import TenantContext
from app.core.errors import NotFound
from app.models import Agent, Campaign, Cohort, Connection, Contact, Organization, Workspace

T = TypeVar("T", Agent, Campaign, Cohort, Connection, Contact)


async def get_org(session: AsyncSession, ctx: TenantContext, org_id: uuid.UUID) -> Organization:
    org = await session.get(Organization, org_id)
    if org is None or not ctx.can_see(org.id):
        raise NotFound("Organisation not found")
    return org


async def get_workspace(
    session: AsyncSession, ctx: TenantContext, workspace_id: uuid.UUID
) -> Workspace:
    ws = await session.get(Workspace, workspace_id)
    if ws is None or not ctx.can_see(ws.org_id, ws.id):
        raise NotFound("Workspace not found")
    return ws


async def _get_scoped[T: (Agent, Campaign, Cohort, Connection, Contact)](
    session: AsyncSession, ctx: TenantContext, model: type[T], obj_id: uuid.UUID, label: str
) -> T:
    obj = await session.get(model, obj_id)
    if obj is None:
        raise NotFound(f"{label} not found")
    workspace_id = getattr(obj, "workspace_id", None)
    if workspace_id is None and isinstance(obj, (Contact, Cohort)):
        campaign = await session.get(Campaign, obj.campaign_id)
        workspace_id = campaign.workspace_id if campaign else None
    if not ctx.can_see(obj.org_id, workspace_id):
        raise NotFound(f"{label} not found")
    return obj


async def get_agent(session: AsyncSession, ctx: TenantContext, agent_id: uuid.UUID) -> Agent:
    return await _get_scoped(session, ctx, Agent, agent_id, "Agent")


async def get_connection(
    session: AsyncSession, ctx: TenantContext, connection_id: uuid.UUID
) -> Connection:
    return await _get_scoped(session, ctx, Connection, connection_id, "Connection")


async def get_campaign(
    session: AsyncSession, ctx: TenantContext, campaign_id: uuid.UUID
) -> Campaign:
    return await _get_scoped(session, ctx, Campaign, campaign_id, "Campaign")


async def get_cohort(session: AsyncSession, ctx: TenantContext, cohort_id: uuid.UUID) -> Cohort:
    return await _get_scoped(session, ctx, Cohort, cohort_id, "Cohort")


async def get_contact(session: AsyncSession, ctx: TenantContext, contact_id: uuid.UUID) -> Contact:
    return await _get_scoped(session, ctx, Contact, contact_id, "Contact")
