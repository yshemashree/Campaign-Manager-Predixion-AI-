"""The per-organisation Do Not Disturb list.

Numbers on it are skipped at cohort upload, never claimed by the dispatcher, and any that
are already queued get cancelled by the scheduler.
"""

import csv
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.domain.cohort_schema import PHONE_COLUMN, normalise_phone
from app.models import DndNumber
from app.schemas.dnd import DndAddResult

REASON_COLUMN = "reason"
INSERT_CHUNK = 5000


async def listed(session: AsyncSession, org_id: uuid.UUID, phones: list[str]) -> set[str]:
    found: set[str] = set()
    for i in range(0, len(phones), INSERT_CHUNK):
        rows = await session.scalars(
            select(DndNumber.phone_e164).where(
                DndNumber.org_id == org_id,
                DndNumber.phone_e164.in_(phones[i : i + INSERT_CHUNK]),
            )
        )
        found.update(rows)
    return found


async def add(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    entries: Iterable[tuple[str, str | None]],
    user_id: uuid.UUID,
    default_region: str,
) -> DndAddResult:
    """Add (raw phone, reason) pairs. Numbers already listed keep their original reason."""
    invalid: list[str] = []
    wanted: dict[str, str | None] = {}
    for raw, reason in entries:
        phone = normalise_phone(raw, default_region)
        if phone is None:
            invalid.append(raw)
        else:
            wanted.setdefault(phone, reason or None)

    now = datetime.now(UTC)
    rows = [
        {
            "id": new_id(),
            "org_id": org_id,
            "phone_e164": phone,
            "reason": reason[:500] if reason else None,
            "created_by": user_id,
            "created_at": now,
        }
        for phone, reason in wanted.items()
    ]
    added = 0
    for i in range(0, len(rows), INSERT_CHUNK):
        result = await session.execute(
            insert(DndNumber)
            .values(rows[i : i + INSERT_CHUNK])
            .on_conflict_do_nothing(index_elements=["org_id", "phone_e164"])
            .returning(DndNumber.id)
        )
        added += len(result.all())
    await session.commit()
    return DndAddResult(added=added, already_listed=len(wanted) - added, invalid=invalid)


def parse_csv(lines: Iterable[str], max_rows: int) -> list[tuple[str, str | None]]:
    """(phone, reason) pairs from a CSV with a phone_number column and an optional reason."""
    reader = csv.reader(lines)
    header = [h.strip().lstrip("﻿").strip() for h in next(reader, [])]
    if PHONE_COLUMN not in header:
        raise ValueError(f"Missing required column: {PHONE_COLUMN}")
    phone_at = header.index(PHONE_COLUMN)
    reason_at = header.index(REASON_COLUMN) if REASON_COLUMN in header else None
    entries: list[tuple[str, str | None]] = []
    for cells in reader:
        if not any(c.strip() for c in cells):
            continue
        if len(entries) >= max_rows:
            raise ValueError(f"Too many rows: the limit is {max_rows}")
        phone = cells[phone_at].strip() if phone_at < len(cells) else ""
        reason = (
            cells[reason_at].strip() if reason_at is not None and reason_at < len(cells) else ""
        )
        entries.append((phone, reason or None))
    return entries
