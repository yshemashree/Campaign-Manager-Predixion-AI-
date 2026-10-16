"""Cohort uploads and the contacts inside a campaign."""

import csv
import io
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import RedisDep, SessionDep, SettingsDep, TenantDep
from app.core.errors import Conflict, NotFound, Unprocessable
from app.domain.cohort_schema import LEAD_COLUMN, PHONE_COLUMN, csv_safe
from app.domain.states import COHORT_UPLOAD_ALLOWED, QUEUED_CONTACT_STATUSES, ContactStatus
from app.engine import events
from app.models import CallAttempt, Cohort, Contact
from app.schemas.campaigns import (
    AttemptOut,
    CohortOut,
    CohortUploadResult,
    ContactDetail,
    ContactOut,
    ContactPage,
)
from app.services import cohorts, scope

router = APIRouter(tags=["cohorts & contacts"])

EXPORT_BATCH = 2000
EXPORT_TAIL = (
    "status",
    "attempts_made",
    "last_outcome",
    "final_reason",
    "last_attempt_at",
    "last_duration_s",
    "updated_at",
)
_EXPORT_SQL = text(
    """
    SELECT c.id, c.phone_e164, c.lead_id, c.variables, c.status, c.attempts_made,
           c.last_outcome, c.final_reason, c.updated_at,
           a.last_attempt_at, a.duration_s AS last_duration_s
    FROM contacts c
    LEFT JOIN LATERAL (
        SELECT COALESCE(dispatched_at, created_at) AS last_attempt_at, duration_s
        FROM call_attempts WHERE contact_id = c.id ORDER BY attempt_no DESC LIMIT 1
    ) a ON true
    WHERE c.campaign_id = :campaign_id AND c.id > :after
    ORDER BY c.id
    LIMIT :n
    """
)


@router.post("/campaigns/{campaign_id}/cohorts", response_model=CohortUploadResult)
async def upload_cohort(
    campaign_id: uuid.UUID,
    ctx: TenantDep,
    session: SessionDep,
    settings: SettingsDep,
    file: UploadFile = File(description="CSV with phone_number, lead_id and the agent's variables"),
    dry_run: bool = Form(default=False, description="Validate only, import nothing"),
    skip_invalid: bool = Form(default=False, description="Import the valid rows, skip the rest"),
) -> CohortUploadResult:
    campaign = await scope.get_campaign(session, ctx, campaign_id)
    if campaign.status not in COHORT_UPLOAD_ALLOWED:
        raise Conflict(f"Can't add contacts to a campaign that is {campaign.status}")
    if file.size is not None and file.size > settings.max_upload_bytes:
        raise Unprocessable(f"The file is larger than {settings.max_upload_bytes // 1_000_000} MB")
    agent = await scope.get_agent(session, ctx, campaign.agent_id)
    return await cohorts.upload(
        session,
        settings,
        campaign=campaign,
        agent=agent,
        filename=file.filename or "cohort.csv",
        binary=file.file,
        dry_run=dry_run,
        skip_invalid=skip_invalid,
        user_id=ctx.user.id,
    )


@router.get("/campaigns/{campaign_id}/cohorts", response_model=list[CohortOut])
async def list_cohorts(campaign_id: uuid.UUID, ctx: TenantDep, session: SessionDep) -> list[Cohort]:
    campaign = await scope.get_campaign(session, ctx, campaign_id)
    return list(
        await session.scalars(
            select(Cohort).where(Cohort.campaign_id == campaign.id).order_by(Cohort.id.desc())
        )
    )


@router.get(
    "/cohorts/{cohort_id}/errors.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
async def cohort_errors(cohort_id: uuid.UUID, ctx: TenantDep, session: SessionDep) -> Response:
    cohort = await scope.get_cohort(session, ctx, cohort_id)
    if not cohort.error_report:
        raise NotFound("This cohort had no rejected rows")
    return Response(
        content=cohort.error_report,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="errors-{cohort.id}.csv"'},
    )


@router.get("/campaigns/{campaign_id}/contacts", response_model=ContactPage)
async def list_contacts(
    campaign_id: uuid.UUID,
    ctx: TenantDep,
    session: SessionDep,
    status_filter: ContactStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=100, description="Phone or lead id prefix"),
    cursor: uuid.UUID | None = Query(default=None, description="next_cursor from the last page"),
    limit: int = Query(default=50, ge=1, le=500),
) -> ContactPage:
    """Keyset pagination: fast on any page, unlike OFFSET."""
    campaign = await scope.get_campaign(session, ctx, campaign_id)
    query = select(Contact).where(Contact.campaign_id == campaign.id)
    if status_filter:
        query = query.where(Contact.status == status_filter)
    if q:
        query = query.where(
            or_(Contact.phone_e164.startswith(q.strip()), Contact.lead_id.startswith(q.strip()))
        )
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    if cursor:
        query = query.where(Contact.id > cursor)
    rows = list(await session.scalars(query.order_by(Contact.id).limit(limit + 1)))
    more = len(rows) > limit
    items = rows[:limit]
    return ContactPage(
        items=[ContactOut.model_validate(c) for c in items],
        next_cursor=str(items[-1].id) if more and items else None,
        total=total or 0,
    )


async def _export_rows(
    factory: async_sessionmaker[AsyncSession], campaign_id: uuid.UUID, variables: list[str]
) -> AsyncIterator[str]:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([PHONE_COLUMN, LEAD_COLUMN, *variables, *EXPORT_TAIL])
    after = uuid.UUID(int=0)
    async with factory() as session:
        while True:
            rows = (
                await session.execute(
                    _EXPORT_SQL, {"campaign_id": campaign_id, "after": after, "n": EXPORT_BATCH}
                )
            ).all()
            for r in rows:
                values = r.variables or {}
                writer.writerow(
                    [
                        r.phone_e164,  # normalised E.164, never a formula
                        csv_safe(r.lead_id),
                        *[csv_safe(str(values.get(v, ""))) for v in variables],
                        r.status,
                        r.attempts_made,
                        r.last_outcome or "",
                        r.final_reason or "",
                        r.last_attempt_at.isoformat() if r.last_attempt_at else "",
                        "" if r.last_duration_s is None else r.last_duration_s,
                        r.updated_at.isoformat(),
                    ]
                )
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate()
            if len(rows) < EXPORT_BATCH:
                return
            after = rows[-1].id


@router.get(
    "/campaigns/{campaign_id}/contacts.csv",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/csv": {}}, "description": "Every contact, as CSV"}},
)
async def export_contacts(
    campaign_id: uuid.UUID, request: Request, ctx: TenantDep, session: SessionDep
) -> StreamingResponse:
    campaign = await scope.get_campaign(session, ctx, campaign_id)
    agent = await scope.get_agent(session, ctx, campaign.agent_id)
    variables = [str(v["name"]) for v in agent.variables]
    safe_name = "".join(c if c.isalnum() else "-" for c in campaign.name.lower()).strip("-")
    # The stream outlives this request's session, so it reads through its own.
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    return StreamingResponse(
        _export_rows(factory, campaign.id, variables),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="contacts-{safe_name}.csv"'},
    )


@router.get("/contacts/{contact_id}", response_model=ContactDetail)
async def get_contact(contact_id: uuid.UUID, ctx: TenantDep, session: SessionDep) -> ContactDetail:
    contact = await scope.get_contact(session, ctx, contact_id)
    attempts = await session.scalars(
        select(CallAttempt)
        .where(CallAttempt.contact_id == contact.id)
        .order_by(CallAttempt.attempt_no)
    )
    return ContactDetail(
        **ContactOut.model_validate(contact).model_dump(),
        attempts=[AttemptOut.model_validate(a) for a in attempts],
    )


@router.post("/contacts/{contact_id}/cancel", response_model=ContactOut)
async def cancel_contact(
    contact_id: uuid.UUID, ctx: TenantDep, session: SessionDep, redis: RedisDep
) -> ContactOut:
    """Take a waiting contact out of the queue. A call already in progress can't be cancelled."""
    contact = await scope.get_contact(session, ctx, contact_id)
    now = datetime.now(UTC)
    # Compare-and-set: loses cleanly if a worker claims the contact at the same moment.
    cancelled = await session.scalar(
        update(Contact)
        .where(Contact.id == contact.id, Contact.status.in_(QUEUED_CONTACT_STATUSES))
        .values(status=ContactStatus.CANCELLED, final_reason="cancelled_by_user", updated_at=now)
        .returning(Contact.id)
    )
    if cancelled is None:
        await session.rollback()
        await session.refresh(contact)
        raise Conflict(f"Only waiting contacts can be cancelled (this one is {contact.status})")
    await session.commit()
    await session.refresh(contact)
    out = ContactOut.model_validate(contact)
    event: dict[str, Any] = {
        "type": "contact.updated",
        "contact_id": str(contact.id),
        "status": contact.status,
        "attempts_made": contact.attempts_made,
        "next_attempt_at": events.iso(out.next_attempt_at),
        "last_outcome": contact.last_outcome,
        "updated_at": events.iso(contact.updated_at),
    }
    await events.publish(redis, contact.campaign_id, event)
    return out
