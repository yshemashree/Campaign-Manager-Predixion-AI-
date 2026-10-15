"""Agents and telephony connections, registered per workspace."""

import uuid

from fastapi import APIRouter, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import SessionDep, TenantDep
from app.core.errors import Conflict
from app.domain.cohort_schema import Variable, sample_csv
from app.models import Agent, Connection
from app.schemas.campaigns import (
    AgentCreate,
    AgentOut,
    AgentUpdate,
    ConnectionCreate,
    ConnectionOut,
    ConnectionUpdate,
)
from app.services import scope

router = APIRouter(tags=["agents & connections"])


@router.get("/workspaces/{workspace_id}/agents", response_model=list[AgentOut])
async def list_agents(workspace_id: uuid.UUID, ctx: TenantDep, session: SessionDep) -> list[Agent]:
    ws = await scope.get_workspace(session, ctx, workspace_id)
    return list(
        await session.scalars(select(Agent).where(Agent.workspace_id == ws.id).order_by(Agent.name))
    )


@router.post(
    "/workspaces/{workspace_id}/agents",
    response_model=AgentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_agent(
    workspace_id: uuid.UUID, body: AgentCreate, ctx: TenantDep, session: SessionDep
) -> Agent:
    ctx.require_admin()
    ws = await scope.get_workspace(session, ctx, workspace_id)
    agent = Agent(
        org_id=ws.org_id,
        workspace_id=ws.id,
        name=body.name,
        app_id=body.app_id,
        app_version=body.app_version,
        variables=[v.model_dump() for v in body.variables],
        initial_bot_message=body.initial_bot_message,
        initial_state_name=body.initial_state_name,
    )
    session.add(agent)
    try:
        await session.commit()
    except IntegrityError as exc:
        raise Conflict("An agent with that name already exists in this workspace") from exc
    return agent


@router.get("/agents/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: uuid.UUID, ctx: TenantDep, session: SessionDep) -> Agent:
    return await scope.get_agent(session, ctx, agent_id)


@router.patch("/agents/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: uuid.UUID, body: AgentUpdate, ctx: TenantDep, session: SessionDep
) -> Agent:
    ctx.require_admin()
    agent = await scope.get_agent(session, ctx, agent_id)
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(agent, key, value)
    try:
        await session.commit()
    except IntegrityError as exc:
        raise Conflict("An agent with that name already exists in this workspace") from exc
    return agent


@router.get(
    "/agents/{agent_id}/sample-cohort.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "Sample CSV for this agent"}},
)
async def sample_cohort(agent_id: uuid.UUID, ctx: TenantDep, session: SessionDep) -> Response:
    agent = await scope.get_agent(session, ctx, agent_id)
    body = sample_csv(Variable.from_dict(v) for v in agent.variables)
    safe_name = "".join(c if c.isalnum() else "-" for c in agent.name.lower()).strip("-")
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="sample-{safe_name}.csv"'},
    )


@router.get("/workspaces/{workspace_id}/connections", response_model=list[ConnectionOut])
async def list_connections(
    workspace_id: uuid.UUID, ctx: TenantDep, session: SessionDep
) -> list[Connection]:
    ws = await scope.get_workspace(session, ctx, workspace_id)
    return list(
        await session.scalars(
            select(Connection).where(Connection.workspace_id == ws.id).order_by(Connection.name)
        )
    )


@router.post(
    "/workspaces/{workspace_id}/connections",
    response_model=ConnectionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_connection(
    workspace_id: uuid.UUID, body: ConnectionCreate, ctx: TenantDep, session: SessionDep
) -> Connection:
    ctx.require_admin()
    ws = await scope.get_workspace(session, ctx, workspace_id)
    conn = Connection(
        org_id=ws.org_id,
        workspace_id=ws.id,
        name=body.name,
        connection_id=body.connection_id,
        caller_numbers=body.caller_numbers,
    )
    session.add(conn)
    try:
        await session.commit()
    except IntegrityError as exc:
        raise Conflict("A connection with that name already exists in this workspace") from exc
    return conn


@router.patch("/connections/{connection_id}", response_model=ConnectionOut)
async def update_connection(
    connection_id: uuid.UUID, body: ConnectionUpdate, ctx: TenantDep, session: SessionDep
) -> Connection:
    ctx.require_admin()
    conn = await scope.get_connection(session, ctx, connection_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(conn, key, value)
    try:
        await session.commit()
    except IntegrityError as exc:
        raise Conflict("A connection with that name already exists in this workspace") from exc
    return conn
