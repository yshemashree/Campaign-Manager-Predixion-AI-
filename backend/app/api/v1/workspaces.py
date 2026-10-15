import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import SessionDep, SettingsDep, TenantDep
from app.core.errors import Conflict, Unprocessable
from app.core.security import encrypt_secret
from app.models import Workspace
from app.schemas.tenancy import WorkspaceCreate, WorkspaceOut, WorkspaceUpdate
from app.services import scope

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(
    ctx: TenantDep,
    session: SessionDep,
    org_id: uuid.UUID | None = Query(default=None, description="Superadmin: filter by org"),
) -> list[Workspace]:
    query = select(Workspace).order_by(Workspace.name)
    if ctx.is_superadmin:
        if org_id:
            query = query.where(Workspace.org_id == org_id)
    elif ctx.is_org_admin:
        query = query.where(Workspace.org_id == ctx.org_id)
    else:
        query = query.where(Workspace.id.in_(ctx.workspace_ids or {uuid.UUID(int=0)}))
    return list(await session.scalars(query))


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: WorkspaceCreate,
    ctx: TenantDep,
    session: SessionDep,
    settings: SettingsDep,
    org_id: uuid.UUID | None = Query(default=None, description="Superadmin: which org"),
) -> Workspace:
    ctx.require_admin()
    target_org = org_id if ctx.is_superadmin else ctx.org_id
    if target_org is None:
        raise Unprocessable("org_id is required for superadmins")
    await scope.get_org(session, ctx, target_org)
    ws = Workspace(org_id=target_org, name=body.name, sarvam_workspace_id=body.sarvam_workspace_id)
    if body.sarvam_api_key:
        ws.sarvam_api_key_enc = encrypt_secret(settings, body.sarvam_api_key)
        ws.sarvam_api_key_last4 = body.sarvam_api_key[-4:]
    session.add(ws)
    try:
        await session.commit()
    except IntegrityError as exc:
        raise Conflict("A workspace with that name already exists") from exc
    return ws


@router.get("/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(workspace_id: uuid.UUID, ctx: TenantDep, session: SessionDep) -> Workspace:
    return await scope.get_workspace(session, ctx, workspace_id)


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
async def update_workspace(
    workspace_id: uuid.UUID,
    body: WorkspaceUpdate,
    ctx: TenantDep,
    session: SessionDep,
    settings: SettingsDep,
) -> Workspace:
    ctx.require_admin()
    ws = await scope.get_workspace(session, ctx, workspace_id)
    changes = body.model_dump(exclude_unset=True)
    api_key = changes.pop("sarvam_api_key", None)
    for key, value in changes.items():
        setattr(ws, key, value)
    if api_key:
        ws.sarvam_api_key_enc = encrypt_secret(settings, api_key)
        ws.sarvam_api_key_last4 = api_key[-4:]
    try:
        await session.commit()
    except IntegrityError as exc:
        raise Conflict("A workspace with that name already exists") from exc
    return ws
