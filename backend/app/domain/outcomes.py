"""Turn Sarvam's webhook into our outcome.

Sarvam reports `status` in {connected, busy, no_answer, failed} and a `duration` in seconds.
"""

from app.domain.states import AttemptStatus


def classify(sarvam_status: str | None, duration_s: int | None, short_threshold_s: int) -> str:
    status = (sarvam_status or "").strip().lower()
    if status == "connected":
        if duration_s is not None and duration_s < short_threshold_s:
            return AttemptStatus.SHORT_CALL
        return AttemptStatus.COMPLETED
    if status == "busy":
        return AttemptStatus.BUSY
    if status in {"no_answer", "no-answer", "noanswer"}:
        return AttemptStatus.NO_ANSWER
    return AttemptStatus.FAILED
