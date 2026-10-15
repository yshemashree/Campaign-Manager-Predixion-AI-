import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep, TenantContext, TenantDep, load_workspace_ids
from app.core.errors import Conflict, NotFound, Unprocessable
from app.core.security import hash_password
from app.domain.states import Role
from app.models import User, Workspace, WorkspaceMember
from app.schemas.tenancy import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


async def _out(session: AsyncSession, user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.workspace_ids = sorted(await load_workspace_ids(session, user))
    return out


async def _set_workspaces(
    session: AsyncSession, user: User, workspace_ids: list[uuid.UUID]
) -> None:
    if workspace_ids:
        valid = set(
            await session.scalars(
                select(Workspace.id).where(
                    Workspace.id.in_(workspace_ids), Workspace.org_id == user.org_id
                )
            )
        )
        if valid != set(workspace_ids):
            raise Unprocessable("Some workspaces don't exist in this organisation")
    await session.execute(delete(WorkspaceMember).where(WorkspaceMember.user_id == user.id))
    for ws_id in set(workspace_ids):
        session.add(WorkspaceMember(user_id=user.id, workspace_id=ws_id))


async def _get_user(session: AsyncSession, ctx: TenantContext, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None or user.org_id is None or not ctx.can_see(user.org_id):
        raise NotFound("User not found")
    return user


@router.get("", response_model=list[UserOut])
async def list_users(
    ctx: TenantDep, session: SessionDep, org_id: uuid.UUID | None = Query(default=None)
) -> list[UserOut]:
    ctx.require_admin()
    query = select(User).where(User.role != Role.SUPERADMIN).order_by(User.email)
    target = org_id if ctx.is_superadmin else ctx.org_id
    if target is not None:
        query = query.where(User.org_id == target)
    return [await _out(session, u) for u in await session.scalars(query)]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, ctx: TenantDep, session: SessionDep) -> UserOut:
    ctx.require_admin()
    org_id = body.org_id if ctx.is_superadmin else ctx.org_id
    if org_id is None:
        raise Unprocessable("org_id is required for superadmins")
    user = User(
        email=body.email.lower(),
        full_name=body.full_name,
        password_hash=hash_password(body.password),
        role=body.role,
        org_id=org_id,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise Conflict("A user with that email already exists") from exc
    await _set_workspaces(session, user, body.workspace_ids)
    await session.commit()
    return await _out(session, user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, ctx: TenantDep, session: SessionDep
) -> UserOut:
    ctx.require_admin()
    user = await _get_user(session, ctx, user_id)
    changes = body.model_dump(exclude_unset=True)
    if "password" in changes:
        user.password_hash = hash_password(changes.pop("password"))
    workspace_ids = changes.pop("workspace_ids", None)
    for key, value in changes.items():
        setattr(user, key, value)
    if workspace_ids is not None:
        await _set_workspaces(session, user, workspace_ids)
    await session.commit()
    return await _out(session, user)
