"""The organisation's Do Not Disturb list. Members can read it; admins change it."""

import asyncio
import uuid

from fastapi import APIRouter, File, Query, Response, UploadFile, status
from sqlalchemy import delete, func, select

from app.api.deps import SessionDep, SettingsDep, TenantDep
from app.core.errors import NotFound, Unprocessable
from app.domain.cohort_schema import normalise_phone
from app.models import DndNumber
from app.schemas.dnd import DndAdd, DndAddResult, DndOut, DndPage
from app.services import cohorts, dnd, scope

router = APIRouter(prefix="/organizations", tags=["do not disturb"])


@router.get("/{org_id}/dnd", response_model=DndPage)
async def list_dnd(
    org_id: uuid.UUID,
    ctx: TenantDep,
    session: SessionDep,
    search: str | None = Query(default=None, max_length=30, description="Part of the number"),
    cursor: uuid.UUID | None = Query(default=None, description="next_cursor from the last page"),
    limit: int = Query(default=50, ge=1, le=500),
) -> DndPage:
    """Newest first."""
    org = await scope.get_org(session, ctx, org_id)
    query = select(DndNumber).where(DndNumber.org_id == org.id)
    if search and search.strip():
        query = query.where(DndNumber.phone_e164.contains(search.strip(), autoescape=True))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    if cursor:
        query = query.where(DndNumber.id < cursor)
    rows = list(await session.scalars(query.order_by(DndNumber.id.desc()).limit(limit + 1)))
    more = len(rows) > limit
    items = rows[:limit]
    return DndPage(
        items=[DndOut.model_validate(d) for d in items],
        next_cursor=str(items[-1].id) if more and items else None,
        total=total or 0,
    )


@router.post("/{org_id}/dnd", response_model=DndAddResult)
async def add_dnd(
    org_id: uuid.UUID, body: DndAdd, ctx: TenantDep, session: SessionDep, settings: SettingsDep
) -> DndAddResult:
    org = await scope.get_org(session, ctx, org_id)
    ctx.require_admin()
    return await dnd.add(
        session,
        org_id=org.id,
        entries=[(p, body.reason) for p in body.phone_numbers],
        user_id=ctx.user.id,
        default_region=settings.default_phone_region,
    )


@router.post("/{org_id}/dnd/upload", response_model=DndAddResult)
async def upload_dnd(
    org_id: uuid.UUID,
    ctx: TenantDep,
    session: SessionDep,
    settings: SettingsDep,
    file: UploadFile = File(description="CSV with a phone_number column and an optional reason"),
) -> DndAddResult:
    org = await scope.get_org(session, ctx, org_id)
    ctx.require_admin()
    if file.size is not None and file.size > settings.max_upload_bytes:
        raise Unprocessable(f"The file is larger than {settings.max_upload_bytes // 1_000_000} MB")
    try:
        entries = await asyncio.to_thread(
            dnd.parse_csv, cohorts.lines(file.file), settings.max_upload_rows
        )
    except UnicodeDecodeError as exc:
        raise Unprocessable("The file must be UTF-8 encoded CSV") from exc
    except ValueError as exc:
        raise Unprocessable(str(exc)) from exc
    return await dnd.add(
        session,
        org_id=org.id,
        entries=entries,
        user_id=ctx.user.id,
        default_region=settings.default_phone_region,
    )


@router.delete("/{org_id}/dnd/{phone_e164}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_dnd(
    org_id: uuid.UUID, phone_e164: str, ctx: TenantDep, session: SessionDep, settings: SettingsDep
) -> Response:
    """Contacts already cancelled because of this number stay cancelled."""
    org = await scope.get_org(session, ctx, org_id)
    ctx.require_admin()
    phone = normalise_phone(phone_e164, settings.default_phone_region)
    removed = None
    if phone is not None:
        removed = await session.scalar(
            delete(DndNumber)
            .where(DndNumber.org_id == org.id, DndNumber.phone_e164 == phone)
            .returning(DndNumber.id)
        )
    if removed is None:
        raise NotFound("That number is not on the DND list")
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
