"""Cohort uploads and the contacts inside a campaign."""

import uuid

from fastapi import APIRouter, File, Form, Query, Response, UploadFile
from sqlalchemy import or_, select

from app.api.deps import SessionDep, SettingsDep, TenantDep
from app.core.errors import Conflict, NotFound, Unprocessable
from app.domain.states import COHORT_UPLOAD_ALLOWED, ContactStatus
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
    if cursor:
        query = query.where(Contact.id > cursor)
    rows = list(await session.scalars(query.order_by(Contact.id).limit(limit + 1)))
    more = len(rows) > limit
    items = rows[:limit]
    return ContactPage(
        items=[ContactOut.model_validate(c) for c in items],
        next_cursor=str(items[-1].id) if more and items else None,
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
