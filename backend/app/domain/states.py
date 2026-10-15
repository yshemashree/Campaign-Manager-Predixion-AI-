"""Statuses and allowed lifecycle moves for campaigns, contacts and call attempts.

Kept as plain constants so the API, the engine and the tests share one definition.
"""

from enum import StrEnum


class Role(StrEnum):
    SUPERADMIN = "superadmin"
    ORG_ADMIN = "org_admin"
    MEMBER = "member"


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"


class ContactStatus(StrEnum):
    PENDING = "pending"
    DIALING = "dialing"  # claimed by a worker, request about to be sent
    IN_PROGRESS = "in_progress"  # Sarvam accepted the call; waiting for the outcome
    RETRY_SCHEDULED = "retry_scheduled"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AttemptStatus(StrEnum):
    RESERVED = "reserved"  # created at claim time, not sent yet
    DISPATCHED = "dispatched"  # Sarvam answered 2xx
    UNKNOWN = "unknown"  # may have been sent; waiting for the webhook to tell us
    COMPLETED = "completed"
    BUSY = "busy"
    NO_ANSWER = "no_answer"
    SHORT_CALL = "short_call"
    FAILED = "failed"
    REJECTED = "rejected"  # Sarvam refused the request (4xx); no call was placed
    LOST = "lost"  # no outcome arrived in time


class LifecycleAction(StrEnum):
    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"


# Contacts waiting in the queue (picked up by the dispatcher when due).
QUEUED_CONTACT_STATUSES = frozenset({ContactStatus.PENDING, ContactStatus.RETRY_SCHEDULED})
# Contacts that still need something to happen.
OPEN_CONTACT_STATUSES = frozenset(
    {
        ContactStatus.PENDING,
        ContactStatus.DIALING,
        ContactStatus.IN_PROGRESS,
        ContactStatus.RETRY_SCHEDULED,
    }
)
TERMINAL_CONTACT_STATUSES = frozenset(
    {ContactStatus.COMPLETED, ContactStatus.FAILED, ContactStatus.CANCELLED}
)

OPEN_ATTEMPT_STATUSES = frozenset(
    {AttemptStatus.RESERVED, AttemptStatus.DISPATCHED, AttemptStatus.UNKNOWN}
)

TERMINAL_CAMPAIGN_STATUSES = frozenset({CampaignStatus.STOPPED, CampaignStatus.COMPLETED})

# Which statuses each action may start from. Everything else is a 409 Conflict
# (or a no-op if the campaign is already where the action would take it).
ACTION_ALLOWED_FROM: dict[LifecycleAction, frozenset[CampaignStatus]] = {
    LifecycleAction.START: frozenset({CampaignStatus.DRAFT}),
    LifecycleAction.PAUSE: frozenset({CampaignStatus.RUNNING, CampaignStatus.SCHEDULED}),
    LifecycleAction.RESUME: frozenset({CampaignStatus.PAUSED}),
    LifecycleAction.STOP: frozenset(
        {CampaignStatus.SCHEDULED, CampaignStatus.RUNNING, CampaignStatus.PAUSED}
    ),
}

# If the campaign is already in one of these, repeating the action changes nothing.
ACTION_ALREADY_DONE: dict[LifecycleAction, frozenset[CampaignStatus]] = {
    LifecycleAction.START: frozenset({CampaignStatus.RUNNING, CampaignStatus.SCHEDULED}),
    LifecycleAction.PAUSE: frozenset({CampaignStatus.PAUSED}),
    LifecycleAction.RESUME: frozenset({CampaignStatus.RUNNING, CampaignStatus.SCHEDULED}),
    LifecycleAction.STOP: frozenset({CampaignStatus.STOPPED}),
}

# Campaign states in which new cohorts may be uploaded (mirrors Sarvam's rule).
COHORT_UPLOAD_ALLOWED = frozenset(
    {
        CampaignStatus.DRAFT,
        CampaignStatus.SCHEDULED,
        CampaignStatus.RUNNING,
        CampaignStatus.PAUSED,
    }
)
# Campaign settings can be edited only while nothing is dialing.
EDIT_ALLOWED = frozenset({CampaignStatus.DRAFT, CampaignStatus.SCHEDULED, CampaignStatus.PAUSED})
