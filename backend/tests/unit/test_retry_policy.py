import copy
from datetime import UTC, datetime, time, timedelta

from app.domain.outcomes import classify
from app.domain.retry_policy import DEFAULT_RETRY_POLICY, decide
from app.domain.windows import CallingWindow

ALWAYS = CallingWindow("UTC", frozenset(range(1, 8)), time(0), time(23, 59))
NOW = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)


def run(outcome: str, attempts: int = 1, **kw: object) -> object:
    args: dict[str, object] = {
        "outcome": outcome,
        "attempts_made": attempts,
        "policy": DEFAULT_RETRY_POLICY,
        "campaign_status": "running",
        "window": ALWAYS,
        "start_at": None,
        "end_at": None,
        "now": NOW,
    }
    args.update(kw)
    return decide(**args)  # type: ignore[arg-type]


def test_classify() -> None:
    assert classify("connected", 45, 10) == "completed"
    assert classify("connected", 4, 10) == "short_call"
    assert classify("connected", None, 10) == "completed"
    assert classify("BUSY", None, 10) == "busy"
    assert classify("no-answer", None, 10) == "no_answer"
    assert classify("something new", None, 10) == "failed"
    assert classify(None, None, 10) == "failed"


def test_completed_is_final() -> None:
    assert run("completed").status == "completed"  # type: ignore[attr-defined]


def test_busy_retries_after_its_delay() -> None:
    d = run("busy")
    assert d.status == "retry_scheduled"  # type: ignore[attr-defined]
    assert d.next_attempt_at == NOW + timedelta(seconds=600)  # type: ignore[attr-defined]


def test_backoff_grows_the_delay() -> None:
    policy = copy.deepcopy(DEFAULT_RETRY_POLICY)
    policy["backoff"] = 2.0
    policy["max_attempts"] = 5
    d = run("busy", attempts=3, policy=policy)
    assert d.next_attempt_at == NOW + timedelta(seconds=2400)  # type: ignore[attr-defined]


def test_disabled_rule_and_max_attempts() -> None:
    assert run("failed").reason == "failed"  # type: ignore[attr-defined]
    assert run("busy", attempts=3).reason == "max_attempts_reached"  # type: ignore[attr-defined]


def test_rejected_never_retries_and_lost_uses_the_failed_rule() -> None:
    assert run("rejected").status == "failed"  # type: ignore[attr-defined]
    policy = copy.deepcopy(DEFAULT_RETRY_POLICY)
    policy["rules"]["failed"]["enabled"] = True
    assert run("lost", policy=policy).status == "retry_scheduled"  # type: ignore[attr-defined]


def test_stopped_campaign_cancels_retries() -> None:
    assert run("busy", campaign_status="stopped").status == "cancelled"  # type: ignore[attr-defined]


def test_retry_moves_into_the_next_window() -> None:
    office = CallingWindow("UTC", frozenset(range(1, 8)), time(9), time(10, 5))
    d = run("busy", window=office)
    assert d.next_attempt_at == datetime(2026, 10, 16, 9, 0, tzinfo=UTC)  # type: ignore[attr-defined]


def test_no_window_left_before_the_end() -> None:
    d = run("busy", end_at=NOW + timedelta(seconds=60))
    assert (d.status, d.reason) == ("failed", "campaign_ended")  # type: ignore[attr-defined]
