from datetime import UTC, datetime, time, timedelta

from hypothesis import given
from hypothesis import strategies as st

from app.domain.windows import CallingWindow, next_allowed, window_end

# Weekdays 09:00-18:00 India time (UTC+5:30, no DST).
IST = CallingWindow("Asia/Kolkata", frozenset({1, 2, 3, 4, 5}), time(9), time(18))


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def test_inside_the_window_reports_when_it_closes() -> None:
    now = utc(2026, 10, 15, 6, 0)  # Thursday 11:30 IST
    assert window_end(now, IST, None, None) == utc(2026, 10, 15, 12, 30)


def test_campaign_end_cuts_the_window_short() -> None:
    now = utc(2026, 10, 15, 6, 0)
    end = utc(2026, 10, 15, 7, 0)
    assert window_end(now, IST, None, end) == end
    assert window_end(end, IST, None, end) is None


def test_outside_the_window() -> None:
    assert window_end(utc(2026, 10, 15, 13, 0), IST, None, None) is None  # 18:30 IST
    assert window_end(utc(2026, 10, 17, 6, 0), IST, None, None) is None  # Saturday


def test_next_allowed_skips_the_weekend() -> None:
    friday_evening = utc(2026, 10, 16, 13, 0)  # Fri 18:30 IST
    assert next_allowed(friday_evening, IST, None, None) == utc(2026, 10, 19, 3, 30)  # Mon 09:00


def test_next_allowed_respects_start_and_end() -> None:
    start = utc(2026, 10, 20, 4, 0)
    assert next_allowed(utc(2026, 10, 15, 6, 0), IST, start, None) == start
    assert next_allowed(utc(2026, 10, 16, 13, 0), IST, None, utc(2026, 10, 18)) is None


def test_dst_zone_uses_local_wall_clock() -> None:
    ny = CallingWindow("America/New_York", frozenset(range(1, 8)), time(9), time(17))
    # 9am New York is 13:00 UTC in summer and 14:00 UTC in winter.
    assert next_allowed(utc(2026, 7, 1, 0, 0), ny, None, None) == utc(2026, 7, 1, 13, 0)
    assert next_allowed(utc(2026, 12, 1, 0, 0), ny, None, None) == utc(2026, 12, 1, 14, 0)


instants = st.datetimes(
    min_value=datetime(2026, 1, 1), max_value=datetime(2030, 12, 31), timezones=st.just(UTC)
)
windows = st.builds(
    lambda tz, days, start_h, length: CallingWindow(
        tz, frozenset(days), time(start_h), time(min(start_h + length, 23), 59)
    ),
    st.sampled_from(["Asia/Kolkata", "America/New_York", "Europe/London", "UTC"]),
    st.sets(st.integers(1, 7), min_size=1),
    st.integers(0, 20),
    st.integers(1, 10),
)


@given(instants, windows)
def test_next_allowed_is_always_inside_a_window(t: datetime, cw: CallingWindow) -> None:
    found = next_allowed(t, cw, None, None)
    assert found is not None and found >= t
    closes = window_end(found, cw, None, None)
    assert closes is not None and closes > found


@given(instants, windows)
def test_next_allowed_is_the_earliest(t: datetime, cw: CallingWindow) -> None:
    found = next_allowed(t, cw, None, None)
    assert found is not None
    # Nothing between t and found is callable (checked at one-minute steps).
    probe = t
    while probe < found - timedelta(minutes=1):
        assert window_end(probe, cw, None, None) is None
        probe += timedelta(minutes=37)
