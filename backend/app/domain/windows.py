"""Calling-window maths. Pure functions: no database, no clock, easy to test.

A window is one IANA timezone, a set of allowed weekdays (ISO: Monday=1 ... Sunday=7) and a
daily [start, end) interval in local time. A campaign may also have overall start/end instants.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class CallingWindow:
    timezone: str
    days: frozenset[int]
    start: time
    end: time

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "CallingWindow":
        return cls(
            timezone=str(data["timezone"]),
            days=frozenset(int(d) for d in data["days"]),  # type: ignore[attr-defined]
            start=time.fromisoformat(str(data["start"])),
            end=time.fromisoformat(str(data["end"])),
        )

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def _local_instant(day: date, at: time, tz: ZoneInfo) -> datetime:
    """Local wall time on `day` as an aware UTC instant (DST gaps resolve forward)."""
    naive = datetime.combine(day, at)
    aware = naive.replace(tzinfo=tz)
    # Round-trip through UTC so a non-existent local time (spring-forward gap) normalises.
    return aware.astimezone(UTC)


def window_end(
    now: datetime, cw: CallingWindow, start_at: datetime | None, end_at: datetime | None
) -> datetime | None:
    """If `now` is inside an allowed window, when does that window close? Otherwise None."""
    if start_at is not None and now < start_at:
        return None
    if end_at is not None and now >= end_at:
        return None
    local = now.astimezone(cw.tz)
    if local.isoweekday() not in cw.days:
        return None
    opens = _local_instant(local.date(), cw.start, cw.tz)
    closes = _local_instant(local.date(), cw.end, cw.tz)
    if not (opens <= now < closes):
        return None
    return min(closes, end_at) if end_at is not None else closes


def next_allowed(
    t: datetime, cw: CallingWindow, start_at: datetime | None, end_at: datetime | None
) -> datetime | None:
    """Earliest instant >= t inside an allowed window and before end_at. None if there is none."""
    if start_at is not None and t < start_at:
        t = start_at
    if end_at is not None and t >= end_at:
        return None
    local_day = t.astimezone(cw.tz).date()
    for offset in range(8):  # every weekday appears within 8 days
        day = local_day + timedelta(days=offset)
        if day.isoweekday() not in cw.days:
            continue
        opens = _local_instant(day, cw.start, cw.tz)
        closes = _local_instant(day, cw.end, cw.tz)
        candidate = max(t, opens)
        if candidate < closes:
            if end_at is not None and candidate >= end_at:
                return None
            return candidate
    return None
