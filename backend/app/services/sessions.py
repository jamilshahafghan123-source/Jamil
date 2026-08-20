"""J Gold AI Session Map (sections 8, 9, 10).

Trading sessions are defined in each financial centre's own local time and
converted with `zoneinfo`, so British Summer Time, US daylight saving and
the Southern Hemisphere's opposite calendar are all handled by the tz
database rather than by an offset written into this file. Hard-coding
"London opens at 07:00 UTC" is wrong for around half the year, and wrong
in a way that silently misplaces every session box on the chart.

The session windows themselves are the conventional interbank hours for
each centre, quoted in local time:

    Sydney     07:00 - 16:00  Australia/Sydney
    Tokyo      09:00 - 18:00  Asia/Tokyo
    London     08:00 - 16:30  Europe/London
    New York   08:00 - 17:00  America/New_York

A session's high and low are measured from the bars that fall inside its
window. Nothing here invents a level: if no bar covers the window, the
session reports no range rather than a guess.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


class SessionName(str, enum.Enum):
    SYDNEY = "SYDNEY"
    TOKYO = "TOKYO"
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"


@dataclass(frozen=True, slots=True)
class SessionSpec:
    name: SessionName
    display_name: str
    tz: str
    opens: time
    closes: time
    #: Chart colour, kept with the definition so the UI has no second list
    #: that can drift out of step with this one.
    colour: str

    def window(self, on: date) -> tuple[datetime, datetime]:
        """The session's open and close on `on`, as UTC instants.

        `on` is a date in the session's OWN timezone, not UTC — asking for
        "London on the 3rd" must mean London's third, or the answer shifts
        by a day either side of midnight.
        """
        zone = ZoneInfo(self.tz)
        start = datetime.combine(on, self.opens, tzinfo=zone)
        end = datetime.combine(on, self.closes, tzinfo=zone)
        if end <= start:  # a session that runs past local midnight
            end += timedelta(days=1)
        return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


SESSIONS: tuple[SessionSpec, ...] = (
    SessionSpec(SessionName.SYDNEY, "Sydney", "Australia/Sydney",
                time(7, 0), time(16, 0), "#5aa9a3"),
    SessionSpec(SessionName.TOKYO, "Tokyo", "Asia/Tokyo",
                time(9, 0), time(18, 0), "#c2708f"),
    SessionSpec(SessionName.LONDON, "London", "Europe/London",
                time(8, 0), time(16, 30), "#6aa9ff"),
    SessionSpec(SessionName.NEW_YORK, "New York", "America/New_York",
                time(8, 0), time(17, 0), "#d9a441"),
)

_BY_NAME = {s.name: s for s in SESSIONS}


def get(name: SessionName | str) -> SessionSpec:
    key = SessionName(name) if not isinstance(name, SessionName) else name
    return _BY_NAME[key]


def active_at(moment: datetime) -> list[SessionSpec]:
    """Which sessions are open at `moment`. Several overlap by design."""
    if moment.tzinfo is None:
        raise ValueError("moment must be timezone-aware")
    moment = moment.astimezone(timezone.utc)
    out: list[SessionSpec] = []
    for spec in SESSIONS:
        local_day = moment.astimezone(ZoneInfo(spec.tz)).date()
        # Check yesterday too: a session that crossed local midnight is
        # still open in the early hours of the following local day.
        for day in (local_day - timedelta(days=1), local_day):
            start, end = spec.window(day)
            if start <= moment < end:
                out.append(spec)
                break
    return out


def _parse(value) -> datetime | None:
    """Bar timestamps arrive as ISO strings from the bridge."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _range_of(bars: list[dict], start: datetime, end: datetime) -> dict | None:
    """High, low and open of the bars falling inside [start, end)."""
    high = low = opened = None
    first_time = None
    for bar in bars:
        moment = _parse(bar.get("time"))
        if moment is None or not (start <= moment < end):
            continue
        bar_high, bar_low = bar.get("high"), bar.get("low")
        if bar_high is None or bar_low is None:
            continue
        high = bar_high if high is None else max(high, bar_high)
        low = bar_low if low is None else min(low, bar_low)
        if first_time is None or moment < first_time:
            first_time, opened = moment, bar.get("open")
    if high is None or low is None:
        return None
    return {"high": high, "low": low, "open": opened}


def session_ranges(bars: list[dict], days: int = 3, now: datetime | None = None
                   ) -> list[dict]:
    """Session boxes for the last `days` days, measured from `bars`.

    Only sessions that actually have bars produce a box. A weekend, a
    holiday, or a window the loaded history does not reach simply yields
    nothing for that day.
    """
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    out: list[dict] = []
    for spec in SESSIONS:
        local_today = moment.astimezone(ZoneInfo(spec.tz)).date()
        for back in range(days):
            day = local_today - timedelta(days=back)
            start, end = spec.window(day)
            if start > moment:
                continue
            measured = _range_of(bars, start, end)
            if measured is None:
                continue
            out.append({
                "session": spec.name.value,
                "display_name": spec.display_name,
                "colour": spec.colour,
                "date": day.isoformat(),
                "start": start.isoformat(),
                "end": min(end, moment).isoformat(),
                "complete": end <= moment,
                "high": measured["high"],
                "low": measured["low"],
                "open": measured["open"],
            })
    out.sort(key=lambda r: r["start"])
    return out


# ---------------------------------------------------------------- previous
# Previous-period levels (section 10). Each is measured from completed
# periods only: today's developing high is not "the previous day high",
# and treating it as one would draw a level that moves under the user.

def _period_bounds(kind: str, moment: datetime) -> tuple[datetime, datetime]:
    """UTC bounds of the completed period before the one containing `moment`."""
    day = moment.date()
    if kind == "DAY":
        end = datetime.combine(day, time(0, 0), tzinfo=timezone.utc)
        return end - timedelta(days=1), end
    if kind == "WEEK":
        this_week = day - timedelta(days=day.weekday())
        end = datetime.combine(this_week, time(0, 0), tzinfo=timezone.utc)
        return end - timedelta(days=7), end
    if kind == "MONTH":
        this_month = day.replace(day=1)
        end = datetime.combine(this_month, time(0, 0), tzinfo=timezone.utc)
        previous_last_day = this_month - timedelta(days=1)
        start = datetime.combine(
            previous_last_day.replace(day=1), time(0, 0), tzinfo=timezone.utc
        )
        return start, end
    raise ValueError(f"unknown period: {kind!r}")


#: label prefix per period, matching the conventional abbreviations.
_PERIOD_LABELS = {"DAY": ("PDH", "PDL"), "WEEK": ("PWH", "PWL"),
                  "MONTH": ("PMH", "PML")}


def previous_levels(bars: list[dict], now: datetime | None = None) -> list[dict]:
    """PDH/PDL, PWH/PWL and previous month high/low, where bars reach them.

    A period the loaded history does not cover is omitted rather than
    approximated from whatever the earliest bar happens to be.
    """
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    out: list[dict] = []
    for kind, (high_label, low_label) in _PERIOD_LABELS.items():
        start, end = _period_bounds(kind, moment)
        measured = _range_of(bars, start, end)
        if measured is None:
            continue
        out.append({
            "period": kind,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "high": measured["high"], "high_label": high_label,
            "low": measured["low"], "low_label": low_label,
        })
    return out
