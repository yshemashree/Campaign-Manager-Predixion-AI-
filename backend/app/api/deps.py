"""Shared request dependencies: database session, Redis, the logged-in user and tenant scope.

Tenant isolation is enforced here, in one place: every endpoint that touches tenant data
gets a TenantContext and loads records through `scope` helpers that check the org (and, for
members, the workspace). A record from another org is reported as 404, not 403, so its
existence isn't revealed.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_access_token
from app.domain.states import Role
from app.engine.gate import Gate
from app.models import User, Workspace, WorkspaceMember

_bearer = HTTPBearer(auto_error=False)


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


def get_redis(request: Request) -> "Redis":
    redis: Redis = request.app.state.redis
    return redis


def get_gate(request: Request) -> Gate:
    gate: Gate = request.app.state.gate
    return gate


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
RedisDep = Annotated["Redis", Depends(get_redis)]
GateDep = Annotated[Gate, Depends(get_gate)]


@dataclass
class TenantContext:
    user: User
    workspace_ids: set[uuid.UUID] = field(default_factory=set)

    @property
    def role(self) -> str:
        return self.user.role

    @property
    def org_id(self) -> uuid.UUID | None:
        return self.user.org_id

    @property
    def is_superadmin(self) -> bool:
        return self.user.role == Role.SUPERADMIN

    @property
    def is_org_admin(self) -> bool:
        return self.user.role == Role.ORG_ADMIN

    def can_see(self, org_id: uuid.UUID, workspace_id: uuid.UUID | None = None) -> bool:
        if self.is_superadmin:
            return True
        if org_id != self.org_id:
            return False
        if self.is_org_admin or workspace_id is None:
            return True
        return workspace_id in self.workspace_ids

    def require_admin(self) -> None:
        """Org admin (for their org) or superadmin."""
        if not (self.is_superadmin or self.is_org_admin):
            raise Forbidden("This action needs an organisation admin")

    def require_superadmin(self) -> None:
        if not self.is_superadmin:
            raise Forbidden("This action needs a superadmin")


async def load_workspace_ids(session: AsyncSession, user: User) -> set[uuid.UUID]:
    if user.role == Role.SUPERADMIN or user.org_id is None:
        return set()
    if user.role == Role.ORG_ADMIN:
        rows = await session.scalars(select(Workspace.id).where(Workspace.org_id == user.org_id))
    else:
        rows = await session.scalars(
            select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user.id)
        )
    return set(rows)


async def tenant_from_token(session: AsyncSession, settings: Settings, token: str) -> TenantContext:
    try:
        claims = decode_access_token(settings, token)
        user_id = uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise Unauthorized("Invalid or expired token") from exc
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise Unauthorized("User not found or disabled")
    return TenantContext(user=user, workspace_ids=await load_workspace_ids(session, user))


async def get_tenant(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> TenantContext:
    if credentials is None:
        raise Unauthorized("Missing bearer token")
    return await tenant_from_token(session, settings, credentials.credentials)


TenantDep = Annotated[TenantContext, Depends(get_tenant)]
