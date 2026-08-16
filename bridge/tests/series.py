"""Deterministic candle series for the analysis tests.

Hand-built rather than random so a failing assertion always points at the
pipeline, never at the fixture.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone


def candles(closes: list[float], *, wick: float = 0.4, step_minutes: int = 15) -> list[dict]:
    """Wrap a close series in OHLC bars with symmetric wicks."""
    start = datetime.now(tz=timezone.utc) - timedelta(minutes=step_minutes * len(closes))
    rows = []
    previous = closes[0]
    for i, close in enumerate(closes):
        open_ = previous
        rows.append(
            {
                "time": int((start + timedelta(minutes=step_minutes * i)).timestamp()),
                "open": round(open_, 5),
                "high": round(max(open_, close) + wick, 5),
                "low": round(min(open_, close) - wick, 5),
                "close": round(close, 5),
                "tick_volume": 500 + i,
                "spread": 30,
                "real_volume": 0,
            }
        )
        previous = close
    return rows


# Pullbacks have to be deeper than the drift, or the series only ever rises:
# RSI pins at 100, no swing pivots form, and the S/R stage has nothing to read.
# amplitude/period here (1.7/bar) comfortably exceeds the 0.6/bar drift.
_PULLBACK_AMPLITUDE = 6.0
_PULLBACK_PERIOD = 3.5


def uptrend(bars: int = 260, start: float = 2350.0, slope: float = 0.6) -> list[dict]:
    """A rising market with regular pullbacks — the classic long setup."""
    closes = [
        start + i * slope + math.sin(i / _PULLBACK_PERIOD) * _PULLBACK_AMPLITUDE
        for i in range(bars)
    ]
    return candles(closes)


def downtrend(bars: int = 260, start: float = 2450.0, slope: float = 0.6) -> list[dict]:
    closes = [
        start - i * slope + math.sin(i / _PULLBACK_PERIOD) * _PULLBACK_AMPLITUDE
        for i in range(bars)
    ]
    return candles(closes)


def choppy(bars: int = 260, centre: float = 2400.0) -> list[dict]:
    """No trend: oscillation around a level, so trend and momentum disagree."""
    closes = [centre + math.sin(i / 5) * 8 for i in range(bars)]
    return candles(closes)


def volatility_spike(bars: int = 260, start: float = 2400.0) -> list[dict]:
    """A quiet series that ends in a violent expansion, pushing ATR to its ceiling."""
    closes = [start + math.sin(i / 6) * 1.5 + i * 0.25 for i in range(bars - 12)]
    last = closes[-1]
    for i in range(12):
        last += 45 if i % 2 == 0 else -30
        closes.append(last)
    return candles(closes, wick=12.0)
