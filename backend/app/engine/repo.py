"""Hot-path SQL for the engine. Hand-written so every condition is visible.

Every write is a compare-and-set (`WHERE status = <expected> AND current_attempt_id = ...`),
so a slow worker, a duplicate webhook or a racing reaper can never overwrite newer state.
Lock order is always attempt row, then contact row, which rules out deadlocks.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import retry_policy
from app.domain.outcomes import classify
from app.domain.states import TERMINAL_CONTACT_STATUSES, AttemptStatus, ContactStatus
from app.domain.windows import CallingWindow


@dataclass(frozen=True)
class Claim:
    contact_id: uuid.UUID
    org_id: uuid.UUID
    campaign_id: uuid.UUID
    phone: str
    lead_id: str
    variables: dict[str, Any]
    attempt_no: int


@dataclass(frozen=True)
class OutcomeApplied:
    org_id: uuid.UUID
    campaign_id: uuid.UUID
    contact_id: uuid.UUID
    phone: str
    attempt_status: str
    contact_status: str | None  # None if the contact had already moved on
    attempts_made: int
    next_attempt_at: datetime | None  # None once the contact is finished
    last_outcome: str | None
    updated_at: datetime


@dataclass(frozen=True)
class Dispatched:
    next_attempt_at: datetime
    last_outcome: str | None
    updated_at: datetime


def _next_at(status: str, next_attempt_at: datetime | None) -> datetime | None:
    return None if status in TERMINAL_CONTACT_STATUSES else next_attempt_at


_CLAIM_SQL = text(
    """
    WITH picked AS (
        SELECT c.id FROM contacts c
        WHERE c.campaign_id = :campaign_id
          AND c.status IN ('pending', 'retry_scheduled')
          AND c.next_attempt_at <= now()
          AND NOT EXISTS (SELECT 1 FROM dnd_numbers d
                          WHERE d.org_id = c.org_id AND d.phone_e164 = c.phone_e164)
          AND EXISTS (SELECT 1 FROM campaigns k
                      WHERE k.id = :campaign_id AND k.status = 'running'
                        AND k.state_version = :version)
        ORDER BY c.priority, c.next_attempt_at, c.id
        LIMIT 1
        FOR UPDATE OF c SKIP LOCKED
    )
    UPDATE contacts c
    SET status = 'dialing', prev_status = c.status, attempts_made = c.attempts_made + 1,
        current_attempt_id = :attempt_ref, lease_owner = :worker,
        lease_expires_at = now() + make_interval(secs => :lease_s), updated_at = now()
    FROM picked
    WHERE c.id = picked.id
    RETURNING c.id, c.org_id, c.campaign_id, c.phone_e164, c.lead_id, c.variables,
              c.attempts_made
    """
)


async def claim_next(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    granted_version: int,
    worker_id: str,
    attempt_ref: uuid.UUID,
    from_number: str,
    lease_s: int,
) -> Claim | None:
    """Lock the next due contact (others skip it instead of waiting) and reserve attempt #n."""
    row = (
        await session.execute(
            _CLAIM_SQL,
            {
                "campaign_id": campaign_id,
                "version": granted_version,
                "attempt_ref": attempt_ref,
                "worker": worker_id,
                "lease_s": lease_s,
            },
        )
    ).first()
    if row is None:
        await session.rollback()
        return None
    await session.execute(
        text(
            "INSERT INTO call_attempts (id, org_id, campaign_id, contact_id, attempt_no, status,"
            " from_number, created_at) VALUES (:id, :org, :camp, :contact, :no, 'reserved',"
            " :from_number, now())"
        ),
        {
            "id": attempt_ref,
            "org": row.org_id,
            "camp": row.campaign_id,
            "contact": row.id,
            "no": row.attempts_made,
            "from_number": from_number,
        },
    )
    await session.commit()
    return Claim(
        contact_id=row.id,
        org_id=row.org_id,
        campaign_id=row.campaign_id,
        phone=row.phone_e164,
        lead_id=row.lead_id,
        variables=row.variables or {},
        attempt_no=row.attempts_made,
    )


async def release(
    session: AsyncSession, *, contact_id: uuid.UUID, attempt_ref: uuid.UUID, defer_s: int = 0
) -> bool:
    """The attempt was never sent: forget it and put the contact back exactly as it was."""
    deleted = await session.execute(
        text("DELETE FROM call_attempts WHERE id = :ref AND status = 'reserved' RETURNING id"),
        {"ref": attempt_ref},
    )
    if deleted.first() is None:
        await session.rollback()
        return False
    await session.execute(
        text(
            """
            UPDATE contacts
            SET status = COALESCE(prev_status, 'pending'), attempts_made = attempts_made - 1,
                current_attempt_id = NULL, lease_owner = NULL, lease_expires_at = NULL,
                next_attempt_at = CASE WHEN :defer > 0
                                       THEN now() + make_interval(secs => :defer)
                                       ELSE next_attempt_at END,
                updated_at = now()
            WHERE id = :contact AND status = 'dialing' AND current_attempt_id = :ref
            """
        ),
        {"contact": contact_id, "ref": attempt_ref, "defer": defer_s},
    )
    await session.commit()
    return True


async def record_dispatch(
    session: AsyncSession,
    *,
    contact_id: uuid.UUID,
    attempt_ref: uuid.UUID,
    status: str,
    provider_attempt_id: str | None,
    http_status: int | None,
    error: str | None,
) -> Dispatched | None:
    """After the HTTP call. No-op (None) if the (faster) webhook already finished the attempt."""
    await session.execute(
        text(
            """
            UPDATE call_attempts
            SET status = :status, provider_attempt_id = :pid, http_status = :http,
                dispatched_at = now(), failure_reason = :error
            WHERE id = :ref AND status IN ('reserved', 'unknown')
            """
        ),
        {
            "status": status,
            "pid": provider_attempt_id,
            "http": http_status,
            "error": error,
            "ref": attempt_ref,
        },
    )
    row = (
        await session.execute(
            text(
                """
                UPDATE contacts
                SET status = 'in_progress', lease_owner = NULL, lease_expires_at = NULL,
                    updated_at = now()
                WHERE id = :contact AND status = 'dialing' AND current_attempt_id = :ref
                RETURNING next_attempt_at, last_outcome, updated_at
                """
            ),
            {"contact": contact_id, "ref": attempt_ref},
        )
    ).first()
    await session.commit()
    if row is None:
        return None
    return Dispatched(
        next_attempt_at=row.next_attempt_at,
        last_outcome=row.last_outcome,
        updated_at=row.updated_at,
    )


TERMINAL_ATTEMPT = {
    AttemptStatus.COMPLETED,
    AttemptStatus.BUSY,
    AttemptStatus.NO_ANSWER,
    AttemptStatus.SHORT_CALL,
    AttemptStatus.FAILED,
    AttemptStatus.REJECTED,
    AttemptStatus.LOST,
}


async def apply_outcome(
    session: AsyncSession,
    *,
    attempt_ref: uuid.UUID,
    sarvam_status: str | None = None,
    duration_s: int | None = None,
    failure_reason: str | None = None,
    provider_attempt_id: str | None = None,
    forced_outcome: str | None = None,
    now: datetime | None = None,
) -> OutcomeApplied | None:
    """Finish an attempt and decide what happens to its contact. Idempotent.

    Returns None if the attempt doesn't exist or was already final (duplicate webhook).
    Does not commit; the caller commits (so a webhook event can be marked in the same txn).
    """
    now = now or datetime.now(UTC)
    attempt = (
        (
            await session.execute(
                text("SELECT * FROM call_attempts WHERE id = :ref FOR UPDATE"), {"ref": attempt_ref}
            )
        )
        .mappings()
        .first()
    )
    if attempt is None:
        return None
    campaign = (
        (
            await session.execute(
                text(
                    "SELECT id, org_id, status, retry_policy, calling_window, start_at, end_at"
                    " FROM campaigns WHERE id = :id"
                ),
                {"id": attempt["campaign_id"]},
            )
        )
        .mappings()
        .one()
    )
    policy = campaign["retry_policy"] or retry_policy.DEFAULT_RETRY_POLICY
    outcome = forced_outcome or classify(
        sarvam_status, duration_s, int(policy.get("short_call_threshold_s", 10))
    )

    late_result_for_lost = attempt["status"] == AttemptStatus.LOST and outcome != AttemptStatus.LOST
    if attempt["status"] in TERMINAL_ATTEMPT and not late_result_for_lost:
        return None  # duplicate or late webhook for a finished attempt

    await session.execute(
        text(
            """
            UPDATE call_attempts
            SET status = :status, ended_at = :now, duration_s = COALESCE(:duration, duration_s),
                failure_reason = COALESCE(:reason, failure_reason),
                provider_attempt_id = COALESCE(provider_attempt_id, :pid),
                dispatched_at = COALESCE(dispatched_at, :now)
            WHERE id = :ref
            """
        ),
        {
            "status": outcome,
            "now": now,
            "duration": duration_s,
            "reason": failure_reason,
            "pid": provider_attempt_id,
            "ref": attempt_ref,
        },
    )
    contact = (
        (
            await session.execute(
                text("SELECT * FROM contacts WHERE id = :id FOR UPDATE"),
                {"id": attempt["contact_id"]},
            )
        )
        .mappings()
        .one()
    )
    applied = OutcomeApplied(
        org_id=attempt["org_id"],
        campaign_id=attempt["campaign_id"],
        contact_id=contact["id"],
        phone=contact["phone_e164"],
        attempt_status=outcome,
        contact_status=None,
        attempts_made=contact["attempts_made"],
        next_attempt_at=_next_at(contact["status"], contact["next_attempt_at"]),
        last_outcome=contact["last_outcome"],
        updated_at=contact["updated_at"],
    )
    if contact["current_attempt_id"] != attempt_ref:
        return applied  # the contact has moved on to a newer attempt

    if late_result_for_lost:
        # We gave up waiting and scheduled a retry; the real result arrived after all.
        if contact["status"] != ContactStatus.RETRY_SCHEDULED:
            return applied
        if outcome != AttemptStatus.COMPLETED:
            return applied  # keep the retry
    elif contact["status"] not in (ContactStatus.DIALING, ContactStatus.IN_PROGRESS):
        return applied

    decision = retry_policy.decide(
        outcome=outcome,
        attempts_made=contact["attempts_made"],
        policy=policy,
        campaign_status=campaign["status"],
        window=CallingWindow.from_dict(campaign["calling_window"]),
        start_at=campaign["start_at"],
        end_at=campaign["end_at"],
        now=now,
    )
    is_retry = decision.status == ContactStatus.RETRY_SCHEDULED
    await session.execute(
        text(
            """
            UPDATE contacts
            SET status = :status, last_outcome = :outcome, final_reason = :reason,
                lease_owner = NULL, lease_expires_at = NULL,
                next_attempt_at = COALESCE(:next_at, next_attempt_at),
                priority = CASE WHEN :is_retry THEN 0 ELSE priority END,
                updated_at = :now
            WHERE id = :id
            """
        ),
        {
            "status": decision.status,
            "outcome": outcome,
            "reason": decision.reason,
            "next_at": decision.next_attempt_at,
            "is_retry": is_retry,
            "now": now,
            "id": contact["id"],
        },
    )
    return OutcomeApplied(
        org_id=applied.org_id,
        campaign_id=applied.campaign_id,
        contact_id=applied.contact_id,
        phone=applied.phone,
        attempt_status=outcome,
        contact_status=decision.status,
        attempts_made=applied.attempts_made,
        next_attempt_at=_next_at(
            decision.status, decision.next_attempt_at or contact["next_attempt_at"]
        ),
        last_outcome=outcome,
        updated_at=now,
    )
