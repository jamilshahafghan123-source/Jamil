"""Derived chart intervals (section 10)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services import resample


def m15(start: datetime, count: int, base: float = 100.0) -> list[dict]:
    """Sequential M15 bars with predictable, distinguishable values."""
    out = []
    for i in range(count):
        out.append({
            "time": (start + timedelta(minutes=15 * i)).isoformat(),
            "open": base + i,
            "high": base + i + 2,
            "low": base + i - 1,
            "close": base + i + 0.5,
            "tick_volume": 10 + i,
        })
    return out


def test_only_intervals_that_divide_a_day_are_derived():
    """An interval with no stable anchor must not be offered at all.

    45 minutes does not divide an hour, which is why MT5 has no M45 — but
    it divides a day exactly, so anchoring at midnight gives boundaries
    everyone agrees on. The module asserts this at import; this test
    states the rule.
    """
    for target, (_source, minutes) in resample.DERIVED.items():
        assert 1440 % minutes == 0, target


def test_a_derived_interval_is_a_whole_number_of_source_bars():
    for target, (source, minutes) in resample.DERIVED.items():
        assert minutes % resample.NATIVE_MINUTES[source] == 0, target


def test_native_intervals_are_never_resampled():
    """Passing a native timeframe through the resampler is a mistake.

    Returning the input unchanged would make it impossible to tell a
    supported interval from an unsupported one.
    """
    for native in ("M1", "M5", "H1", "D1"):
        with pytest.raises(ValueError):
            resample.resample([], native)


def test_buckets_anchor_to_midnight_utc():
    start = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    assert resample.bucket_start(start, 45) == start
    assert resample.bucket_start(
        datetime(2026, 6, 1, 0, 44, tzinfo=timezone.utc), 45) == start
    assert resample.bucket_start(
        datetime(2026, 6, 1, 0, 45, tzinfo=timezone.utc), 45
    ) == start + timedelta(minutes=45)
    # The same instant always lands in the same bucket.
    moment = datetime(2026, 6, 1, 13, 22, tzinfo=timezone.utc)
    assert resample.bucket_start(moment, 45) == resample.bucket_start(moment, 45)


def test_ohlc_aggregation_follows_the_rules():
    """Open from the first bar, close from the last, high/low the extremes."""
    start = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    bars = m15(start, 3)
    out = resample.resample(bars, "M45")
    assert len(out) == 1
    bucket = out[0]
    assert bucket["open"] == bars[0]["open"]
    assert bucket["close"] == bars[-1]["close"]
    assert bucket["high"] == max(b["high"] for b in bars)
    assert bucket["low"] == min(b["low"] for b in bars)
    assert bucket["tick_volume"] == sum(b["tick_volume"] for b in bars)


def test_open_is_not_the_average_of_the_bucket():
    """The classic resampling bug: averaging instead of taking the first."""
    start = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    bars = m15(start, 3)
    bucket = resample.resample(bars, "M45")[0]
    average = sum(b["open"] for b in bars) / 3
    assert bucket["open"] != average
    assert bucket["open"] == bars[0]["open"]


def test_three_m15_bars_make_exactly_one_m45_bar():
    start = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    assert len(resample.resample(m15(start, 3), "M45")) == 1
    assert len(resample.resample(m15(start, 6), "M45")) == 2
    assert len(resample.resample(m15(start, 12), "M45")) == 4


def test_a_partial_bucket_is_flagged_rather_than_hidden_or_faked():
    """A forming bar must not be mistaken for a settled one."""
    start = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    out = resample.resample(m15(start, 4), "M45")
    assert len(out) == 2
    assert out[0]["complete"] is True
    assert out[0]["source_bars"] == 3
    assert out[1]["complete"] is False      # only one of three arrived
    assert out[1]["source_bars"] == 1


def test_unparseable_timestamps_are_skipped_not_guessed():
    start = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    bars = [{"time": "nonsense", "open": 1, "high": 2, "low": 0, "close": 1,
             "tick_volume": 5}, *m15(start, 3)]
    out = resample.resample(bars, "M45")
    assert len(out) == 1
    assert out[0]["source_bars"] == 3


def test_empty_history_produces_nothing():
    assert resample.resample([], "M45") == []


def test_supported_lists_native_and_derived_in_order():
    supported = resample.supported()
    assert supported[0] == "M1"
    assert "M45" in supported
    assert "H3" in supported
    # Ascending by duration, so a selector can render it directly.
    minutes = [resample.minutes_of(tf) for tf in supported]
    assert minutes == sorted(minutes)
