"""J Gold AI Session Map: DST correctness and honest ranges."""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.services import sessions
from app.services.sessions import SessionName


def _bar(moment: datetime, high: float, low: float, open_: float = 0.0) -> dict:
    return {"time": moment.isoformat(), "open": open_, "high": high,
            "low": low, "close": (high + low) / 2, "tick_volume": 10}


# --------------------------------------------------------------- DST

def test_london_shifts_with_british_summer_time():
    """London's UTC open must move by an hour between GMT and BST.

    A fixed UTC offset would place every London box an hour wrong for
    roughly half the year.
    """
    winter, _ = sessions.get(SessionName.LONDON).window(date(2026, 1, 15))
    summer, _ = sessions.get(SessionName.LONDON).window(date(2026, 7, 15))
    assert winter.astimezone(timezone.utc).hour == 8
    assert summer.astimezone(timezone.utc).hour == 7


def test_new_york_shifts_with_us_daylight_saving():
    winter, _ = sessions.get(SessionName.NEW_YORK).window(date(2026, 1, 15))
    summer, _ = sessions.get(SessionName.NEW_YORK).window(date(2026, 7, 15))
    assert winter.astimezone(timezone.utc).hour == 13
    assert summer.astimezone(timezone.utc).hour == 12


def test_sydney_shifts_the_opposite_way():
    """The Southern Hemisphere's summer is the Northern Hemisphere's winter.

    This is the case a hand-written offset table gets wrong even when it
    remembers Europe and the US.
    """
    january, _ = sessions.get(SessionName.SYDNEY).window(date(2026, 1, 15))
    july, _ = sessions.get(SessionName.SYDNEY).window(date(2026, 7, 15))
    assert january.astimezone(timezone.utc).hour == 20
    assert july.astimezone(timezone.utc).hour == 21


def test_tokyo_never_shifts():
    """Japan has observed no daylight saving since 1951."""
    january, _ = sessions.get(SessionName.TOKYO).window(date(2026, 1, 15))
    july, _ = sessions.get(SessionName.TOKYO).window(date(2026, 7, 15))
    assert january.astimezone(timezone.utc).hour == july.astimezone(timezone.utc).hour


def test_window_end_is_after_its_start_for_every_session():
    for spec in sessions.SESSIONS:
        start, end = spec.window(date(2026, 3, 29))  # EU clocks change
        assert end > start


def test_active_at_requires_an_aware_moment():
    with pytest.raises(ValueError):
        sessions.active_at(datetime(2026, 6, 1, 12, 0))


def test_sydney_is_open_during_its_own_afternoon():
    moment = datetime(2026, 6, 1, 3, 0, tzinfo=timezone.utc)  # 13:00 Sydney
    assert SessionName.SYDNEY in {s.name for s in sessions.active_at(moment)}


def test_london_and_new_york_overlap_in_the_afternoon():
    """The overlap is a real market feature, so both must report open."""
    moment = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    names = {s.name for s in sessions.active_at(moment)}
    assert {SessionName.LONDON, SessionName.NEW_YORK} <= names


def test_the_market_week_closes_after_new_york_on_friday():
    """Friday 21:00 UTC is New York's close, and nothing follows it.

    Without a weekday rule the four windows tile all 24 hours, so there
    would be no instant in the week with nothing open — and a Saturday
    afternoon would report New York trading.
    """
    friday_open = datetime(2026, 8, 21, 20, 0, tzinfo=timezone.utc)
    assert sessions.active_at(friday_open)
    friday_closed = datetime(2026, 8, 21, 21, 30, tzinfo=timezone.utc)
    assert sessions.active_at(friday_closed) == []


def test_nothing_is_open_across_the_weekend():
    for moment in (
        datetime(2026, 8, 22, 3, 0, tzinfo=timezone.utc),   # Sat, Tokyo hours
        datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),  # Sat, London hours
        datetime(2026, 8, 22, 18, 0, tzinfo=timezone.utc),  # Sat, NY hours
        datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc),  # Sun
        datetime(2026, 8, 23, 20, 0, tzinfo=timezone.utc),  # Sun, pre-open
    ):
        assert sessions.active_at(moment) == [], moment.isoformat()


def test_the_week_reopens_with_sydney_on_sunday_evening_utc():
    """Sydney's Monday morning is Sunday night in UTC, and that is the open."""
    moment = datetime(2026, 8, 23, 22, 0, tzinfo=timezone.utc)
    assert SessionName.SYDNEY in {s.name for s in sessions.active_at(moment)}


# ------------------------------------------------------- session ranges

def test_session_range_is_measured_from_bars_in_the_window():
    now = datetime(2026, 6, 1, 20, 0, tzinfo=timezone.utc)
    start, _ = sessions.get(SessionName.LONDON).window(date(2026, 6, 1))
    bars = [
        _bar(start + timedelta(minutes=15), 2010.0, 2000.0, 2005.0),
        _bar(start + timedelta(minutes=45), 2025.0, 2015.0),
    ]
    london = [r for r in sessions.session_ranges(bars, days=1, now=now)
              if r["session"] == "LONDON"]
    assert len(london) == 1
    assert london[0]["high"] == 2025.0
    assert london[0]["low"] == 2000.0
    assert london[0]["open"] == 2005.0
    assert london[0]["complete"] is True


def test_a_session_with_no_bars_produces_no_box():
    """A holiday or a gap in history must not invent a range."""
    now = datetime(2026, 6, 1, 20, 0, tzinfo=timezone.utc)
    assert sessions.session_ranges([], days=2, now=now) == []


def test_bars_outside_the_window_are_excluded():
    now = datetime(2026, 6, 1, 20, 0, tzinfo=timezone.utc)
    start, end = sessions.get(SessionName.LONDON).window(date(2026, 6, 1))
    bars = [
        _bar(start - timedelta(hours=2), 9999.0, 9998.0),   # before the open
        _bar(start + timedelta(minutes=30), 2010.0, 2000.0),
        _bar(end + timedelta(hours=1), 1.0, 0.5),           # after the close
    ]
    london = [r for r in sessions.session_ranges(bars, days=1, now=now)
              if r["session"] == "LONDON"][0]
    assert london["high"] == 2010.0
    assert london["low"] == 2000.0


def test_a_session_still_running_is_marked_incomplete():
    # 10:00 UTC on 1 June is inside London (07:00-15:30 UTC under BST).
    now = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    start, _ = sessions.get(SessionName.LONDON).window(date(2026, 6, 1))
    bars = [_bar(start + timedelta(minutes=20), 2010.0, 2000.0)]
    london = [r for r in sessions.session_ranges(bars, days=1, now=now)
              if r["session"] == "LONDON"][0]
    assert london["complete"] is False


# ----------------------------------------------------- previous levels

def test_previous_day_levels_exclude_today():
    """Today's developing high is not the previous day's high.

    Including it would draw a level that moves under the user as the day
    progresses, which is the opposite of what a reference level is for.
    """
    now = datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc)
    bars = [
        _bar(datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc), 2010.0, 1990.0),
        _bar(now, 9999.0, 1.0),  # today, must be ignored
    ]
    day = [lv for lv in sessions.previous_levels(bars, now=now)
           if lv["period"] == "DAY"][0]
    assert day["high"] == 2010.0
    assert day["low"] == 1990.0
    assert day["high_label"] == "PDH"
    assert day["low_label"] == "PDL"


def test_previous_week_uses_the_completed_week():
    now = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)  # a Wednesday
    last_week = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)
    bars = [_bar(last_week, 2100.0, 2050.0), _bar(now, 9999.0, 1.0)]
    week = [lv for lv in sessions.previous_levels(bars, now=now)
            if lv["period"] == "WEEK"][0]
    assert (week["high"], week["low"]) == (2100.0, 2050.0)
    assert (week["high_label"], week["low_label"]) == ("PWH", "PWL")


def test_periods_absent_from_history_are_omitted_not_guessed():
    now = datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc)
    # Only today's bars: no completed prior period is covered at all.
    assert sessions.previous_levels([_bar(now, 10.0, 5.0)], now=now) == []


def test_unparseable_timestamps_are_skipped_rather_than_crashing():
    now = datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc)
    bars = [{"time": "not-a-date", "high": 1.0, "low": 0.0},
            _bar(datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc), 2010.0, 1990.0)]
    day = [lv for lv in sessions.previous_levels(bars, now=now)
           if lv["period"] == "DAY"][0]
    assert day["high"] == 2010.0
