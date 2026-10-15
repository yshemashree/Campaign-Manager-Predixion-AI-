"""What happens to a contact after an attempt ends. Pure logic, no I/O."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.domain.states import AttemptStatus, ContactStatus
from app.domain.windows import CallingWindow, next_allowed

RETRYABLE_OUTCOMES = (
    AttemptStatus.BUSY,
    AttemptStatus.NO_ANSWER,
    AttemptStatus.SHORT_CALL,
    AttemptStatus.FAILED,
)

DEFAULT_RETRY_POLICY: dict[str, Any] = {
    "max_attempts": 3,
    "short_call_threshold_s": 10,
    "backoff": 1.0,
    "rules": {
        "busy": {"enabled": True, "delay_s": 600},
        "no_answer": {"enabled": True, "delay_s": 1800},
        "short_call": {"enabled": True, "delay_s": 3600},
        "failed": {"enabled": False, "delay_s": 900},
    },
}


@dataclass(frozen=True)
class Decision:
    status: str  # completed | retry_scheduled | failed | cancelled
    reason: str | None = None
    next_attempt_at: datetime | None = None


def decide(
    *,
    outcome: str,
    attempts_made: int,
    policy: dict[str, Any],
    campaign_status: str,
    window: CallingWindow,
    start_at: datetime | None,
    end_at: datetime | None,
    now: datetime,
) -> Decision:
    if outcome == AttemptStatus.COMPLETED:
        return Decision(ContactStatus.COMPLETED)
    # A rejected request (bad number, bad config) won't succeed by trying again.
    if outcome == AttemptStatus.REJECTED:
        return Decision(ContactStatus.FAILED, reason="rejected")
    rule_key = AttemptStatus.FAILED if outcome == AttemptStatus.LOST else outcome
    rule = policy.get("rules", {}).get(rule_key)
    if not rule or not rule.get("enabled"):
        return Decision(ContactStatus.FAILED, reason=str(outcome))
    if attempts_made >= int(policy.get("max_attempts", 1)):
        return Decision(ContactStatus.FAILED, reason="max_attempts_reached")
    if campaign_status in ("stopped", "completed"):
        return Decision(ContactStatus.CANCELLED, reason=f"campaign_{campaign_status}")
    backoff = float(policy.get("backoff", 1.0))
    delay = float(rule.get("delay_s", 0)) * (backoff ** max(attempts_made - 1, 0))
    when = next_allowed(now + timedelta(seconds=delay), window, start_at, end_at)
    if when is None:
        return Decision(ContactStatus.FAILED, reason="campaign_ended")
    return Decision(ContactStatus.RETRY_SCHEDULED, next_attempt_at=when)
