"""Superadmin: create organisations and set their limits."""

import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.api.deps import GateDep, SessionDep, TenantDep
from app.core.errors import Conflict
from app.core.security import hash_password
from app.domain.states import Role
from app.models import Organization, User
from app.schemas.tenancy import OrganizationCreate, OrganizationOut, OrganizationUpdate
from app.services import scope

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=list[OrganizationOut])
async def list_organizations(ctx: TenantDep, session: SessionDep) -> list[Organization]:
    query = select(Organization).order_by(Organization.name)
    if not ctx.is_superadmin:
        query = query.where(Organization.id == ctx.org_id)
    return list(await session.scalars(query))


@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
async def create_organization(
    body: OrganizationCreate, ctx: TenantDep, session: SessionDep, gate: GateDep
) -> Organization:
    ctx.require_superadmin()
    org = Organization(
        name=body.name,
        sarvam_org_id=body.sarvam_org_id,
        max_concurrent_calls=body.max_concurrent_calls,
        max_calls_per_second=body.max_calls_per_second,
    )
    session.add(org)
    if body.admin_email and body.admin_password:
        await session.flush()
        session.add(
            User(
                email=body.admin_email.lower(),
                full_name=body.admin_name,
                password_hash=hash_password(body.admin_password),
                role=Role.ORG_ADMIN,
                org_id=org.id,
            )
        )
    try:
        await session.commit()
    except IntegrityError as exc:
        raise Conflict("An organisation with that name (or a user with that email) exists") from exc
    await gate.sync_org(
        org.id,
        limit_version=org.limit_version,
        max_cps=org.max_calls_per_second,
        max_concurrent=org.max_concurrent_calls,
    )
    return org


@router.get("/{org_id}", response_model=OrganizationOut)
async def get_organization(org_id: uuid.UUID, ctx: TenantDep, session: SessionDep) -> Organization:
    return await scope.get_org(session, ctx, org_id)


@router.patch("/{org_id}", response_model=OrganizationOut)
async def update_organization(
    org_id: uuid.UUID, body: OrganizationUpdate, ctx: TenantDep, session: SessionDep, gate: GateDep
) -> Organization:
    ctx.require_superadmin()
    org = await scope.get_org(session, ctx, org_id)
    changes = body.model_dump(exclude_unset=True)
    limits_changed = any(
        k in changes and changes[k] != getattr(org, k)
        for k in ("max_concurrent_calls", "max_calls_per_second", "is_active")
    )
    for key, value in changes.items():
        setattr(org, key, value)
    if limits_changed:
        org.limit_version += 1
    try:
        await session.commit()
    except IntegrityError as exc:
        raise Conflict("An organisation with that name already exists") from exc
    await gate.sync_org(
        org.id,
        limit_version=org.limit_version,
        max_cps=org.max_calls_per_second if org.is_active else 0,
        max_concurrent=org.max_concurrent_calls if org.is_active else 0,
    )
    return org


@router.get("/{org_id}/rate")
async def org_rate(
    org_id: uuid.UUID,
    ctx: TenantDep,
    session: SessionDep,
    gate: GateDep,
    seconds: int = Query(default=60, ge=5, le=300),
) -> dict[str, object]:
    """Calls sent per second over the last N seconds, calls live in each second and right now."""
    org = await scope.get_org(session, ctx, org_id)
    now_ms = int((await gate.redis.time())[0]) * 1000
    start_ms = now_ms - seconds * 1000
    fires = await gate.fires_between(org.id, start_ms, now_ms)
    buckets = [0] * seconds
    for ts in fires:
        idx = (ts - start_ms) // 1000
        if 0 <= idx < seconds:
            buckets[idx] += 1
    # Max calls in any rolling 1-second window, measured from our side.
    fires.sort()
    max_rolling, left = 0, 0
    for right, ts in enumerate(fires):
        while ts - fires[left] >= 1000:
            left += 1
        max_rolling = max(max_rolling, right - left + 1)
    start_s = start_ms // 1000
    # Calls in progress at the end of each second: started by then, not yet ended.
    live = await session.execute(
        text(
            """
            WITH a AS (
                SELECT COALESCE(dispatched_at, created_at) AS began,
                       CASE WHEN status IN ('reserved', 'dispatched', 'unknown')
                            THEN 'infinity'::timestamptz ELSE ended_at END AS ended
                FROM call_attempts
                WHERE org_id = :org
                  AND COALESCE(dispatched_at, created_at) < to_timestamp(:last + 1)
                  AND (status IN ('reserved', 'dispatched', 'unknown')
                       OR ended_at > to_timestamp(:first + 1))
            )
            SELECT s.t, count(a.began) AS calls
            FROM generate_series(:first, :last) AS s(t)
            LEFT JOIN a ON a.began <= to_timestamp(s.t + 1) AND a.ended > to_timestamp(s.t + 1)
            GROUP BY s.t ORDER BY s.t
            """
        ),
        {"org": org.id, "first": start_s, "last": start_s + seconds - 1},
    )
    return {
        "org_id": str(org.id),
        "max_calls_per_second": org.max_calls_per_second,
        "max_concurrent_calls": org.max_concurrent_calls,
        "live_calls": await gate.inflight_count(org.id),
        "per_second": [{"t": (start_ms // 1000) + i, "calls": n} for i, n in enumerate(buckets)],
        "max_in_any_rolling_second": max_rolling,
        "live_per_second": [{"t": int(t), "calls": n} for t, n in live],
    }
