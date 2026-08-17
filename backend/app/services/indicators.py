"""Deterministic technical analysis.

Everything here is computed in Python from real OHLCV bars supplied by the
MT5 bridge. The AI analyst is handed *only* the output of this module — it
never sees a request to "estimate" or "recall" a price, which is what makes
the no-invented-data rule enforceable rather than aspirational.

No external TA library: keeps the container small and the maths auditable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Sequence

import numpy as np

TIMEFRAMES = ["M1", "M5", "M15", "H1"]


# ------------------------------------------------------------ primitives


def ema(values: np.ndarray, period: int) -> np.ndarray:
    if len(values) == 0:
        return values
    alpha = 2.0 / (period + 1.0)
    out = np.empty_like(values, dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def rsi(close: np.ndarray, period: int = 14) -> float:
    if len(close) <= period:
        return 50.0
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    # Wilder smoothing
    avg_gain = gain[:period].mean()
    avg_loss = loss[:period].mean()
    for i in range(period, len(delta)):
        avg_gain = (avg_gain * (period - 1) + gain[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> float:
    if len(close) < 2:
        return 0.0
    prev_close = close[:-1]
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(np.abs(high[1:] - prev_close), np.abs(low[1:] - prev_close)),
    )
    if len(tr) < period:
        return float(tr.mean()) if len(tr) else 0.0
    return float(tr[-period:].mean())


def swing_points(
    high: np.ndarray, low: np.ndarray, left: int = 2, right: int = 2
) -> tuple[list[int], list[int]]:
    """Fractal swing highs/lows. Returns (high_indices, low_indices)."""
    highs, lows = [], []
    for i in range(left, len(high) - right):
        window_h = high[i - left : i + right + 1]
        window_l = low[i - left : i + right + 1]
        if high[i] == window_h.max() and (window_h.argmax() == left):
            highs.append(i)
        if low[i] == window_l.min() and (window_l.argmin() == left):
            lows.append(i)
    return highs, lows


def cluster(levels: Sequence[float], tolerance: float) -> list[float]:
    """Merge nearby price levels into representative levels, strongest first.

    `tolerance` is an absolute price distance (we pass ~0.5 ATR).
    """
    if not levels:
        return []
    ordered = sorted(levels)
    groups: list[list[float]] = [[ordered[0]]]
    for lv in ordered[1:]:
        if abs(lv - groups[-1][-1]) <= tolerance:
            groups[-1].append(lv)
        else:
            groups.append([lv])
    # More touches == stronger level.
    groups.sort(key=len, reverse=True)
    return [round(float(np.mean(g)), 2) for g in groups]


# --------------------------------------------------------------- results


@dataclass
class TimeframeAnalysis:
    timeframe: str
    bars_analyzed: int
    last_close: float
    ema_fast: float
    ema_slow: float
    rsi14: float
    atr14: float
    trend: str  # UP | DOWN | RANGE
    structure: str  # HH-HL | LH-LL | MIXED
    support: list[float] = field(default_factory=list)
    resistance: list[float] = field(default_factory=list)
    breakout: str = "NONE"  # UP | DOWN | NONE
    pullback: str = "NONE"  # BULLISH | BEARISH | NONE
    liquidity: list[dict] = field(default_factory=list)
    range_high: float = 0.0
    range_low: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def analyze_timeframe(timeframe: str, bars: list[dict]) -> TimeframeAnalysis | None:
    """Compute the full deterministic picture for one timeframe."""
    if len(bars) < 30:
        return None

    o = np.array([b["open"] for b in bars], dtype=float)
    h = np.array([b["high"] for b in bars], dtype=float)
    lo = np.array([b["low"] for b in bars], dtype=float)
    c = np.array([b["close"] for b in bars], dtype=float)

    ef = ema(c, 20)
    es = ema(c, 50)
    a = atr(h, lo, c, 14)
    r = rsi(c, 14)
    last = float(c[-1])

    # --- trend: EMA alignment plus separation relative to volatility
    sep = float(ef[-1] - es[-1])
    sep_threshold = max(a * 0.15, 1e-9)
    if sep > sep_threshold and last > es[-1]:
        trend = "UP"
    elif sep < -sep_threshold and last < es[-1]:
        trend = "DOWN"
    else:
        trend = "RANGE"

    # --- market structure from the last two confirmed swings each side
    hi_idx, lo_idx = swing_points(h, lo)
    structure = "MIXED"
    if len(hi_idx) >= 2 and len(lo_idx) >= 2:
        hh = h[hi_idx[-1]] > h[hi_idx[-2]]
        hl = lo[lo_idx[-1]] > lo[lo_idx[-2]]
        lh = h[hi_idx[-1]] < h[hi_idx[-2]]
        ll = lo[lo_idx[-1]] < lo[lo_idx[-2]]
        if hh and hl:
            structure = "HH-HL"
        elif lh and ll:
            structure = "LH-LL"

    # --- support / resistance clustered from swing prices
    tol = max(a * 0.5, 0.01)
    res_levels = cluster([float(h[i]) for i in hi_idx], tol)
    sup_levels = cluster([float(lo[i]) for i in lo_idx], tol)
    resistance = [lv for lv in res_levels if lv >= last][:4]
    support = [lv for lv in sup_levels if lv <= last][:4]
    # If price sits outside every cluster, fall back to nearest levels.
    if not resistance:
        resistance = sorted(lv for lv in res_levels)[:2]
    if not support:
        support = sorted((lv for lv in sup_levels), reverse=True)[:2]

    # --- breakout: close beyond the prior N-bar range, with range expansion
    lookback = min(20, len(c) - 1)
    prior_high = float(h[-lookback - 1 : -1].max())
    prior_low = float(lo[-lookback - 1 : -1].min())
    bar_range = float(h[-1] - lo[-1])
    expanding = bar_range > a * 1.2 if a > 0 else False
    breakout = "NONE"
    if last > prior_high and expanding:
        breakout = "UP"
    elif last < prior_low and expanding:
        breakout = "DOWN"

    # --- pullback: with-trend retrace into the fast EMA without breaking structure
    pullback = "NONE"
    dist_to_ema = abs(last - float(ef[-1]))
    near_ema = dist_to_ema <= a * 0.75 if a > 0 else False
    if trend == "UP" and near_ema and last > float(es[-1]):
        pullback = "BULLISH"
    elif trend == "DOWN" and near_ema and last < float(es[-1]):
        pullback = "BEARISH"

    # --- liquidity: equal highs/lows are where stop clusters sit
    liquidity: list[dict] = []
    eq_tol = max(a * 0.15, 0.01)
    for label, idxs, series in (
        ("equal_highs", hi_idx, h),
        ("equal_lows", lo_idx, lo),
    ):
        vals = [float(series[i]) for i in idxs[-8:]]
        for i in range(len(vals) - 1):
            for j in range(i + 1, len(vals)):
                if abs(vals[i] - vals[j]) <= eq_tol:
                    zone_lo, zone_hi = sorted((vals[i], vals[j]))
                    liquidity.append(
                        {
                            "low": round(zone_lo - eq_tol / 2, 2),
                            "high": round(zone_hi + eq_tol / 2, 2),
                            "label": label,
                        }
                    )
                    break
    # De-duplicate overlapping zones, keep the 4 nearest to price.
    liquidity = sorted(
        {(z["low"], z["high"], z["label"]) for z in liquidity},
        key=lambda z: abs((z[0] + z[1]) / 2 - last),
    )[:4]
    liquidity = [{"low": z[0], "high": z[1], "label": z[2]} for z in liquidity]

    return TimeframeAnalysis(
        timeframe=timeframe,
        bars_analyzed=len(bars),
        last_close=round(last, 2),
        ema_fast=round(float(ef[-1]), 2),
        ema_slow=round(float(es[-1]), 2),
        rsi14=round(r, 1),
        atr14=round(a, 2),
        trend=trend,
        structure=structure,
        support=support,
        resistance=resistance,
        breakout=breakout,
        pullback=pullback,
        liquidity=liquidity,
        range_high=round(prior_high, 2),
        range_low=round(prior_low, 2),
    )


def build_snapshot(
    symbol: str,
    tick: dict,
    bars_by_tf: dict[str, list[dict]],
) -> dict:
    """The complete deterministic market picture handed to the AI."""
    tfs: list[dict] = []
    for tf in TIMEFRAMES:
        res = analyze_timeframe(tf, bars_by_tf.get(tf, []))
        if res:
            tfs.append(res.to_dict())

    # Higher-timeframe-weighted confluence, purely mechanical.
    weights = {"M1": 1, "M5": 2, "M15": 3, "H1": 4}
    score = sum(
        weights.get(t["timeframe"], 1)
        * (1 if t["trend"] == "UP" else -1 if t["trend"] == "DOWN" else 0)
        for t in tfs
    )
    total = sum(weights.get(t["timeframe"], 1) for t in tfs) or 1

    return {
        "symbol": symbol,
        "bid": tick["bid"],
        "ask": tick["ask"],
        "spread_points": tick["spread_points"],
        "tick_time": str(tick["time"]),
        "timeframes": tfs,
        "confluence_score": round(score / total, 3),
    }
