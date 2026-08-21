"""Deriving chart intervals the feed does not serve natively (section 10).

MT5 provides M1, M2, M3, M5, M10, M15, M30, H1, H2, H3, H4, D1 and above
as real timeframes. It does NOT provide M45, and the reason matters: 45
minutes does not divide an hour, so there is no obvious place to start
each bucket and different platforms answer that differently.

It does divide a DAY exactly — 1440 / 45 = 32 — so anchoring the grid at
midnight UTC gives buckets that are consistent, repeatable, and identical
for every customer. That anchor is stated here and shown in the UI rather
than left implicit, because a resampled interval whose boundaries nobody
can predict is worse than not offering it.

The rules a correct resample must follow, all enforced below:

  open   the first source bar's open, never the bucket's average
  high   the maximum high in the bucket
  low    the minimum low in the bucket
  close  the LAST source bar's close
  volume the sum of the source volumes

A partial bucket — one whose source bars have not all arrived — is
returned but flagged, so nothing treats a forming bar as settled.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

#: Intervals MT5 serves directly. Anything here is passed straight
#: through; nothing is resampled that does not have to be.
NATIVE_MINUTES: dict[str, int] = {
    "M1": 1, "M2": 2, "M3": 3, "M5": 5, "M10": 10, "M15": 15, "M30": 30,
    "H1": 60, "H2": 120, "H3": 180, "H4": 240, "D1": 1440,
}

#: Intervals derived from a native one. The source must divide the target
#: exactly, or the buckets would contain a varying number of bars.
DERIVED: dict[str, tuple[str, int]] = {
    # target: (source timeframe, minutes)
    "M45": ("M15", 45),
}

for _target, (_source, _minutes) in DERIVED.items():
    assert _minutes % NATIVE_MINUTES[_source] == 0, _target
    assert 1440 % _minutes == 0, (
        f"{_target} does not divide a day evenly, so its buckets would "
        f"have no stable anchor"
    )


def supported() -> list[str]:
    """Every interval the platform can serve, native or derived."""
    return sorted(
        [*NATIVE_MINUTES, *DERIVED],
        key=lambda tf: NATIVE_MINUTES.get(tf) or DERIVED[tf][1],
    )


def minutes_of(timeframe: str) -> int | None:
    upper = timeframe.upper()
    if upper in NATIVE_MINUTES:
        return NATIVE_MINUTES[upper]
    if upper in DERIVED:
        return DERIVED[upper][1]
    return None


def source_for(timeframe: str) -> tuple[str, int] | None:
    """The native timeframe a derived interval is built from."""
    return DERIVED.get(timeframe.upper())


def _parse(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def bucket_start(moment: datetime, minutes: int) -> datetime:
    """The start of the bucket containing `moment`, anchored to midnight UTC.

    Anchoring at midnight is what makes the boundaries predictable: the
    same instant always lands in the same bucket, for everyone, on every
    reload.
    """
    moment = moment.astimezone(timezone.utc)
    midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = int((moment - midnight).total_seconds() // 60)
    return midnight + timedelta(minutes=(elapsed // minutes) * minutes)


def resample(bars: list[dict], timeframe: str) -> list[dict]:
    """Aggregate native bars into a derived interval.

    Raises for an interval that is not derived: silently returning the
    input would make an unsupported timeframe look supported, which is
    exactly the failure this module exists to prevent.
    """
    spec = source_for(timeframe)
    if spec is None:
        raise ValueError(f"{timeframe} is not a derived interval")
    _, minutes = spec
    if not bars:
        return []

    buckets: dict[datetime, dict] = {}
    order: list[datetime] = []
    counts: dict[datetime, int] = {}

    for bar in bars:
        moment = _parse(bar.get("time"))
        if moment is None:
            continue  # an unparseable timestamp cannot be placed
        start = bucket_start(moment, minutes)
        existing = buckets.get(start)
        if existing is None:
            buckets[start] = {
                "time": start.isoformat(),
                "open": bar.get("open"),
                "high": bar.get("high"),
                "low": bar.get("low"),
                "close": bar.get("close"),
                "tick_volume": bar.get("tick_volume") or 0,
            }
            order.append(start)
            counts[start] = 1
            continue
        # open stays the FIRST bar's open; close follows the last.
        if bar.get("high") is not None:
            existing["high"] = max(existing["high"], bar["high"])
        if bar.get("low") is not None:
            existing["low"] = min(existing["low"], bar["low"])
        existing["close"] = bar.get("close")
        existing["tick_volume"] += bar.get("tick_volume") or 0
        counts[start] += 1

    expected = minutes // NATIVE_MINUTES[spec[0]]
    out = []
    for start in order:
        bucket = buckets[start]
        # A bucket missing source bars is still returned — dropping it
        # would leave a hole in the chart — but it is marked so nothing
        # mistakes a forming or gapped bar for a settled one.
        bucket["complete"] = counts[start] == expected
        bucket["source_bars"] = counts[start]
        out.append(bucket)
    return out
