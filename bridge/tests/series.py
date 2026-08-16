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


# --- XAUUSD multi-timeframe fixtures ------------------------------------------
#
# The strategy reads three timeframes, so a fixture has to supply all three and
# they have to tell a coherent story. Each builder returns a dict keyed by the
# stub's timeframe constants, ready for state.rates["XAUUSD"].

TF_M1, TF_M5, TF_M15 = 1, 5, 15


def _wave(bars: int, start: float, slope: float, amp: float, period: float) -> list[float]:
    """A drifting market that keeps retracing: trend plus regular pullbacks."""
    return [start + i * slope + math.sin(i / period) * amp for i in range(bars)]


def _pullback_then_reclaim(
    base: list[float], *, depth: float, recovery: float, bars: int = 12
) -> list[float]:
    """Tack a dip and a recovery onto the end of a series.

    This is the shape the M1 trigger looks for: price leaves the average, comes
    back to it, then closes back through it in the original direction.
    """
    closes = list(base)
    last = closes[-1]
    half = bars // 2
    for i in range(half):
        closes.append(last - depth * (i + 1) / half)
    dipped = closes[-1]
    for i in range(bars - half):
        closes.append(dipped + recovery * (i + 1) / (bars - half))
    return closes


# Tuned so each timeframe reads the way a trader would describe it: the M15 is
# directional but keeps retracing (efficiency ratio ~0.5, not a straight line),
# the M5 ends mid-pullback so RSI sits in the 60s rather than pinned overbought,
# and the M1 dips to its average and closes back through it.
_M15 = dict(bars=300, start=2280.0, slope=0.7, amp=5.0, period=3.5)
_M5 = dict(bars=190, start=2380.0, slope=0.25, amp=2.4, period=5.0)
_M1 = dict(bars=140, start=2422.0, slope=0.03, amp=0.9, period=6.0)

# Reflecting a bullish series through this price gives the bearish mirror.
_MIRROR = 4900.0


def _bullish_closes() -> tuple[list[float], list[float], list[float]]:
    m15 = _wave(**_M15)
    m5 = _pullback_then_reclaim(_wave(**_M5), depth=3.0, recovery=1.0, bars=10)
    m1 = _pullback_then_reclaim(_wave(**_M1), depth=1.6, recovery=2.2)
    return m15, m5, m1


def _as_rates(m15: list[float], m5: list[float], m1: list[float]) -> dict[int, list[dict]]:
    return {
        TF_M15: candles(m15, wick=1.2, step_minutes=15),
        TF_M5: candles(m5, wick=0.6, step_minutes=5),
        TF_M1: candles(m1, wick=0.25, step_minutes=1),
    }


def xauusd_bullish() -> dict[int, list[dict]]:
    """Textbook long: M15 stacked up, M5 making higher highs and lows, M1 reclaiming."""
    return _as_rates(*_bullish_closes())


def xauusd_bearish() -> dict[int, list[dict]]:
    """The mirror image: everything pointing down."""
    m15, m5, m1 = _bullish_closes()
    return _as_rates(
        [_MIRROR - price for price in m15],
        [_MIRROR - price for price in m5],
        [_MIRROR - price for price in m1],
    )


def xauusd_conflicting() -> dict[int, list[dict]]:
    """M15 trending up while M5 structure rolls over — the classic trap."""
    bullish = xauusd_bullish()
    bearish = xauusd_bearish()
    return {
        TF_M15: bullish[TF_M15],
        TF_M5: bearish[TF_M5],
        TF_M1: bullish[TF_M1],
    }


def xauusd_thin() -> dict[int, list[dict]]:
    """Not enough closed history for an EMA200 read on the trend timeframe."""
    thin = xauusd_bullish()
    return {
        TF_M15: thin[TF_M15][-80:],
        TF_M5: thin[TF_M5],
        TF_M1: thin[TF_M1],
    }


def last_close(rates: dict[int, list[dict]]) -> float:
    """The current price implied by a fixture: the newest bar on the finest timeframe."""
    return float(rates[TF_M1][-1]["close"])
