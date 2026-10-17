"""Cohort upload: validate the CSV against the agent's variables, then bulk-insert contacts.

Defaults are strict: if any row is bad, nothing is imported and the caller gets a row-level
report. `skip_invalid=true` imports the good rows only; `dry_run=true` validates only.
Inserts use Postgres COPY into a temporary table, then one INSERT ... ON CONFLICT DO NOTHING,
which also skips numbers already in the campaign.
"""

import asyncio
import codecs
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import IO

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.ids import new_id
from app.domain.cohort_schema import Variable, error_report_csv, validate
from app.models import Agent, Campaign, Cohort, Contact
from app.schemas.campaigns import CohortOut, CohortUploadResult, RowErrorOut


def _lines(binary: IO[bytes]) -> Iterator[str]:
    """Stream text lines from an uploaded file (UTF-8, BOM tolerated)."""
    reader = codecs.getreader("utf-8-sig")(binary)
    yield from reader


async def _existing_phones(
    session: AsyncSession, campaign_id: uuid.UUID, phones: list[str]
) -> set[str]:
    found: set[str] = set()
    for i in range(0, len(phones), 5000):
        chunk = phones[i : i + 5000]
        rows = await session.scalars(
            select(Contact.phone_e164).where(
                Contact.campaign_id == campaign_id, Contact.phone_e164.in_(chunk)
            )
        )
        found.update(rows)
    return found


async def upload(
    session: AsyncSession,
    settings: Settings,
    *,
    campaign: Campaign,
    agent: Agent,
    filename: str,
    binary: IO[bytes],
    dry_run: bool,
    skip_invalid: bool,
    user_id: uuid.UUID,
) -> CohortUploadResult:
    variables = [Variable.from_dict(v) for v in agent.variables]
    try:
        # CPU-bound for big files: run it off the event loop so the API stays responsive.
        result = await asyncio.to_thread(
            lambda: validate(
                _lines(binary),
                variables,
                default_region=settings.default_phone_region,
                max_rows=settings.max_upload_rows,
            )
        )
    except UnicodeDecodeError:
        return CohortUploadResult(
            dry_run=dry_run,
            accepted=False,
            rows_total=0,
            rows_valid=0,
            rows_rejected=0,
            duplicates_in_file=0,
            duplicates_existing=0,
            header_errors=["The file must be UTF-8 encoded CSV"],
            errors=[],
        )

    report = error_report_csv(result.header, result.rejected_rows) if result.rejected_rows else None
    existing = await _existing_phones(
        session, campaign.id, [r.phone_e164 for r in result.valid_rows]
    )
    new_rows = [r for r in result.valid_rows if r.phone_e164 not in existing]
    base = CohortUploadResult(
        dry_run=dry_run,
        accepted=False,
        rows_total=result.rows_total,
        rows_valid=len(result.valid_rows),
        rows_rejected=len(result.rejected_rows),
        duplicates_in_file=result.duplicates_in_file,
        duplicates_existing=len(existing),
        header_errors=result.header_errors,
        errors=[
            RowErrorOut(row=e.row, column=e.column, message=e.message) for e in result.errors[:100]
        ],
        error_report_csv=report,
    )
    blocked = bool(result.header_errors) or (bool(result.rejected_rows) and not skip_invalid)
    if dry_run or blocked or not new_rows:
        return base

    now = datetime.now(UTC)
    cohort = Cohort(
        org_id=campaign.org_id,
        campaign_id=campaign.id,
        filename=filename[:300],
        rows_total=result.rows_total,
        rows_rejected=len(result.rejected_rows),
        error_report=report,
        uploaded_by=user_id,
    )
    session.add(cohort)
    await session.flush()

    records = []
    for r in new_rows:
        contact_id = new_id()
        records.append(
            (
                contact_id,
                campaign.org_id,
                campaign.id,
                cohort.id,
                r.phone_e164,
                r.lead_id or str(contact_id),
                json.dumps(r.variables),
                now,
            )
        )
    conn = await session.connection()
    raw = await conn.get_raw_connection()
    pg = raw.driver_connection  # asyncpg connection, same transaction
    assert pg is not None
    await pg.execute(
        "CREATE TEMP TABLE tmp_contacts (id uuid, org_id uuid, campaign_id uuid, cohort_id uuid,"
        " phone_e164 text, lead_id text, variables jsonb, created_at timestamptz) ON COMMIT DROP"
    )
    await pg.copy_records_to_table(
        "tmp_contacts",
        records=records,
        columns=[
            "id",
            "org_id",
            "campaign_id",
            "cohort_id",
            "phone_e164",
            "lead_id",
            "variables",
            "created_at",
        ],
    )
    inserted = await session.execute(
        text(
            "INSERT INTO contacts (id, org_id, campaign_id, cohort_id, phone_e164, lead_id,"
            " variables, status, priority, attempts_made, next_attempt_at, created_at, updated_at)"
            " SELECT id, org_id, campaign_id, cohort_id, phone_e164, lead_id, variables,"
            " 'pending', 1, 0, created_at, created_at, created_at FROM tmp_contacts"
            " ON CONFLICT (campaign_id, phone_e164) DO NOTHING"
        )
    )
    accepted_count = inserted.rowcount or 0  # type: ignore[attr-defined]
    cohort.rows_accepted = accepted_count
    cohort.rows_duplicate = (
        result.duplicates_in_file + len(existing) + (len(new_rows) - accepted_count)
    )
    await session.commit()

    base.accepted = True
    base.cohort = CohortOut.model_validate(cohort)
    return base
