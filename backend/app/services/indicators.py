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

# Every timeframe the MT5 bridge exposes, ordered fastest to slowest.
TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]

# Role of each timeframe in the decision hierarchy. A lower timeframe may
# time an entry but must never overrule the major structure above it.
TF_ROLE = {
    "D1": "MAJOR",
    "H4": "MAJOR",
    "H1": "INTERMEDIATE",
    "M30": "INTERMEDIATE",
    "M15": "SETUP",
    "M5": "SETUP",
    "M1": "REFINEMENT",
}


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


def macd(
    close: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[float, float, float]:
    """Returns (macd_line, signal_line, histogram) at the last bar."""
    if len(close) < slow + signal:
        return 0.0, 0.0, 0.0
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return float(line[-1]), float(sig[-1]), float(line[-1] - sig[-1])


def adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> float:
    """Wilder's ADX. Above ~25 means trending, below ~20 means ranging."""
    if len(close) < period * 2:
        return 0.0
    up = high[1:] - high[:-1]
    down = low[:-1] - low[1:]
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    prev_close = close[:-1]
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(np.abs(high[1:] - prev_close), np.abs(low[1:] - prev_close)),
    )

    def _smooth(x: np.ndarray) -> np.ndarray:
        out = np.empty_like(x, dtype=float)
        out[:period] = np.nan
        acc = x[:period].sum()
        out[period - 1] = acc
        for i in range(period, len(x)):
            acc = acc - acc / period + x[i]
            out[i] = acc
        return out

    tr_s, p_s, m_s = _smooth(tr), _smooth(plus_dm), _smooth(minus_dm)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * p_s / tr_s
        minus_di = 100.0 * m_s / tr_s
        dx = 100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    dx = dx[np.isfinite(dx)]
    if len(dx) < period:
        return float(dx[-1]) if len(dx) else 0.0
    return float(dx[-period:].mean())


def volume_stats(bars: list[dict], lookback: int = 20) -> dict:
    """Tick-volume statistics.

    MT5 reports *tick volume* for spot gold — the number of price changes,
    not contracts traded. It is a usable activity proxy and nothing more,
    so the label travels with the numbers and is surfaced in the UI.
    """
    vols = [float(b.get("tick_volume") or 0.0) for b in bars]
    if not vols:
        return {
            "type": "TICK_VOLUME",
            "current": 0.0,
            "average": 0.0,
            "relative": 0.0,
            "trend": "UNKNOWN",
            "state": "UNKNOWN",
        }
    current = vols[-1]
    window = vols[-(lookback + 1) : -1] or vols[:-1] or vols
    average = float(np.mean(window))
    relative = round(current / average, 2) if average > 0 else 0.0

    recent = float(np.mean(vols[-5:])) if len(vols) >= 5 else current
    older = float(np.mean(vols[-15:-5])) if len(vols) >= 15 else recent
    if older > 0 and recent > older * 1.15:
        trend = "EXPANDING"
    elif older > 0 and recent < older * 0.85:
        trend = "CONTRACTING"
    else:
        trend = "STEADY"

    state = "HIGH" if relative >= 1.5 else "LOW" if relative <= 0.6 else "NORMAL"
    return {
        "type": "TICK_VOLUME",
        "current": round(current, 1),
        "average": round(average, 1),
        "relative": relative,
        "trend": trend,
        "state": state,
    }


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


def detect_structure(
    high: np.ndarray,
    low: np.ndarray,
    hi_idx: list[int],
    lo_idx: list[int],
    last_close: float,
) -> dict:
    """Swing-based market structure: HH/HL/LH/LL plus BOS and CHOCH.

    BOS   — price closes beyond the most recent swing in the trend direction,
            i.e. the existing trend just extended.
    CHOCH — price closes beyond the most recent swing *against* the prevailing
            swing sequence, the first mechanical hint of a reversal.
    Reported only when enough confirmed swings exist to mean anything;
    otherwise the pattern is UNCLEAR and no claim is made.
    """
    out = {
        "pattern": "UNCLEAR",
        "bos": False,
        "choch": False,
        "description": "Not enough confirmed swings to read structure.",
    }
    if len(hi_idx) < 2 or len(lo_idx) < 2:
        return out

    last_h, prev_h = float(high[hi_idx[-1]]), float(high[hi_idx[-2]])
    last_l, prev_l = float(low[lo_idx[-1]]), float(low[lo_idx[-2]])
    hh, hl = last_h > prev_h, last_l > prev_l
    lh, ll = last_h < prev_h, last_l < prev_l

    if hh and hl:
        out["pattern"] = "HIGHER_HIGH_HIGHER_LOW"
        out["description"] = "Bullish — higher highs and higher lows remain intact."
    elif lh and ll:
        out["pattern"] = "LOWER_HIGH_LOWER_LOW"
        out["description"] = "Bearish — lower highs and lower lows remain intact."
    elif hh and ll:
        out["pattern"] = "EXPANSION"
        out["description"] = "Expanding range — both extremes are widening."
    elif lh and hl:
        out["pattern"] = "CONSOLIDATION"
        out["description"] = "Consolidating — the range is compressing."
    else:
        out["pattern"] = "RANGE"
        out["description"] = "Ranging — no directional swing sequence."

    bullish_seq = out["pattern"] == "HIGHER_HIGH_HIGHER_LOW"
    bearish_seq = out["pattern"] == "LOWER_HIGH_LOWER_LOW"

    if bullish_seq and last_close > last_h:
        out["bos"] = True
        out["description"] += f" Break of structure above {round(last_h, 2)}."
    elif bearish_seq and last_close < last_l:
        out["bos"] = True
        out["description"] += f" Break of structure below {round(last_l, 2)}."
    elif bullish_seq and last_close < last_l:
        out["choch"] = True
        out["description"] += (
            f" Change of character — closed below the last higher low {round(last_l, 2)}."
        )
    elif bearish_seq and last_close > last_h:
        out["choch"] = True
        out["description"] += (
            f" Change of character — closed above the last lower high {round(last_h, 2)}."
        )
    return out


def fair_value_gaps(
    bars: list[dict],
    atr_value: float,
    limit: int = 4,
) -> list[dict]:
    """Unmitigated three-bar imbalances (fair value gaps).

    A bullish FVG is a gap between bar i-2's high and bar i's low: price moved
    up so fast that the middle bar never traded that band. Bearish is the
    mirror. Only gaps that are still unmitigated are returned — once price has
    traded back into the band the imbalance is gone and drawing it would be a
    claim about the past, not the present.

    Gaps narrower than 0.15 ATR are noise at this timeframe and are dropped,
    so a quiet chart reports nothing rather than a wall of thin boxes.
    """
    if len(bars) < 3:
        return []
    floor = max(atr_value * 0.15, 0.01)
    out: list[dict] = []

    for i in range(2, len(bars)):
        first, gap_bar = bars[i - 2], bars[i]
        if gap_bar["low"] > first["high"]:
            zone_low, zone_high, side = first["high"], gap_bar["low"], "bullish"
        elif gap_bar["high"] < first["low"]:
            zone_low, zone_high, side = gap_bar["high"], first["low"], "bearish"
        else:
            continue
        if zone_high - zone_low < floor:
            continue
        # Mitigated as soon as a later bar trades back inside the band.
        if any(
            later["low"] < zone_high and later["high"] > zone_low
            for later in bars[i + 1 :]
        ):
            continue
        out.append(
            {
                "kind": "fvg",
                "side": side,
                "low": round(float(zone_low), 2),
                "high": round(float(zone_high), 2),
                "from_time": bars[i - 1]["time"],
                "label": "Bullish FVG" if side == "bullish" else "Bearish FVG",
            }
        )

    # Consecutive triplets often both qualify over one impulse, producing
    # nested boxes for a single imbalance. Keep the narrowest of each
    # overlapping same-side cluster: it is the tightest band the bars
    # actually support, and the wider one always includes price the middle
    # bar traded through.
    kept: list[dict] = []
    for gap in sorted(out, key=lambda z: z["high"] - z["low"]):
        if any(
            k["side"] == gap["side"]
            and k["low"] < gap["high"]
            and k["high"] > gap["low"]
            for k in kept
        ):
            continue
        kept.append(gap)

    last = float(bars[-1]["close"])
    kept.sort(key=lambda z: abs((z["low"] + z["high"]) / 2 - last))
    return kept[:limit]


def order_blocks(
    bars: list[dict],
    hi_idx: list[int],
    lo_idx: list[int],
    atr_value: float,
    limit: int = 2,
) -> list[dict]:
    """Supply and demand zones, defined mechanically.

    A demand zone is the last down-close candle before an impulsive rally that
    closed above the prior swing high; supply is its mirror. That definition is
    checkable against the bars, which is the only kind we are willing to draw.

    Zones price has already traded back through are dropped, for the same
    reason mitigated gaps are.
    """
    if len(bars) < 5 or atr_value <= 0:
        return []

    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    out: list[dict] = []

    def prior_swing(idxs: list[int], before: int, series: list[float]) -> float | None:
        candidates = [i for i in idxs if i < before]
        return series[candidates[-1]] if candidates else None

    for i in range(2, len(bars)):
        bar = bars[i]
        impulse = float(bar["close"]) - float(bar["open"])
        if abs(impulse) < atr_value * 0.8:
            continue

        if impulse > 0:
            swing = prior_swing(hi_idx, i, highs)
            if swing is None or float(bar["close"]) <= swing:
                continue
            origin = next(
                (j for j in range(i - 1, max(i - 6, -1), -1)
                 if bars[j]["close"] < bars[j]["open"]),
                None,
            )
            side, label = "demand", "Demand"
        else:
            swing = prior_swing(lo_idx, i, lows)
            if swing is None or float(bar["close"]) >= swing:
                continue
            origin = next(
                (j for j in range(i - 1, max(i - 6, -1), -1)
                 if bars[j]["close"] > bars[j]["open"]),
                None,
            )
            side, label = "supply", "Supply"

        if origin is None:
            continue
        zone_low = float(bars[origin]["low"])
        zone_high = float(bars[origin]["high"])
        if any(
            later["low"] < zone_high and later["high"] > zone_low
            for later in bars[i + 1 :]
        ):
            continue
        out.append(
            {
                "kind": "order_block",
                "side": side,
                "low": round(zone_low, 2),
                "high": round(zone_high, 2),
                "from_time": bars[origin]["time"],
                "label": label,
            }
        )

    last = float(bars[-1]["close"])
    out.sort(key=lambda z: abs((z["low"] + z["high"]) / 2 - last))
    return out[:limit]


def swing_markers(
    bars: list[dict],
    hi_idx: list[int],
    lo_idx: list[int],
    limit: int = 6,
) -> list[dict]:
    """The most recent confirmed swing highs and lows, with their bar times.

    These are the same swings the structure reading and the stop placement are
    derived from, so plotting them shows the customer what the engine actually
    measured rather than a second, decorative set of points.
    """
    out: list[dict] = []
    for idx in hi_idx[-limit:]:
        out.append(
            {
                "side": "high",
                "price": round(float(bars[idx]["high"]), 2),
                "time": bars[idx]["time"],
            }
        )
    for idx in lo_idx[-limit:]:
        out.append(
            {
                "side": "low",
                "price": round(float(bars[idx]["low"]), 2),
                "time": bars[idx]["time"],
            }
        )
    out.sort(key=lambda m: m["time"])
    return out


def ranked_levels(
    prices: list[float],
    tolerance: float,
    kind: str,
    last_close: float,
    limit: int = 3,
) -> list[dict]:
    """Cluster swing prices into a handful of ranked levels.

    Strength comes from how many independent swings formed the cluster — a
    price that has repeatedly rejected is stronger than a single touch. The
    goal is a few levels a trader can act on, not every level on the chart.
    """
    if not prices:
        return []
    ordered = sorted(prices)
    groups: list[list[float]] = [[ordered[0]]]
    for lv in ordered[1:]:
        if abs(lv - groups[-1][-1]) <= tolerance:
            groups[-1].append(lv)
        else:
            groups.append([lv])

    out: list[dict] = []
    for g in groups:
        price = round(float(np.mean(g)), 2)
        if kind == "resistance" and price < last_close:
            continue
        if kind == "support" and price > last_close:
            continue
        touches = len(g)
        strength = "HIGH" if touches >= 3 else "MEDIUM" if touches == 2 else "LOW"
        word = "swing high" if kind == "resistance" else "swing low"
        reason = (
            f"{touches} {word} rejections clustered here"
            if touches > 1
            else f"recent {word}"
        )
        out.append(
            {
                "price": price,
                "strength": strength,
                "touches": touches,
                "reason": reason,
                "distance": round(abs(price - last_close), 2),
            }
        )
    out.sort(key=lambda lv: (lv["distance"], -lv["touches"]))
    return out[:limit]


def session_levels(d1_bars: list[dict]) -> list[dict]:
    """Previous-day and previous-week extremes from real D1 candles.

    Returns [] when D1 data is unavailable rather than approximating these
    from a faster timeframe — a wrong PDH is worse than no PDH.
    """
    if len(d1_bars) < 2:
        return []
    prev = d1_bars[-2]
    out = [
        {"label": "PDH", "price": round(float(prev["high"]), 2),
         "reason": "previous day high"},
        {"label": "PDL", "price": round(float(prev["low"]), 2),
         "reason": "previous day low"},
    ]
    if len(d1_bars) >= 11:
        week = d1_bars[-11:-6]
        out.append({"label": "PWH",
                    "price": round(max(float(b["high"]) for b in week), 2),
                    "reason": "previous week high"})
        out.append({"label": "PWL",
                    "price": round(min(float(b["low"]) for b in week), 2),
                    "reason": "previous week low"})
    return out


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
    # --- added for the multi-timeframe analyst -------------------------
    role: str = ""
    ema200: float = 0.0
    macd_line: float = 0.0
    macd_signal: float = 0.0
    macd_hist: float = 0.0
    adx14: float = 0.0
    regime: str = "UNKNOWN"  # TRENDING | RANGING | EXPANSION | CONSOLIDATION
    momentum: str = "NEUTRAL"  # RISING | FALLING | NEUTRAL
    structure_detail: dict = field(default_factory=dict)
    bos: bool = False
    choch: bool = False
    support_levels: list[dict] = field(default_factory=list)
    resistance_levels: list[dict] = field(default_factory=list)
    volume: dict = field(default_factory=dict)
    breakout_confirmed: bool = False
    breakout_level: float = 0.0
    # Structural zones and markers, each carrying the bar time they start at
    # so the chart can draw them where they actually happened.
    fvg: list[dict] = field(default_factory=list)
    order_blocks: list[dict] = field(default_factory=list)
    swings: list[dict] = field(default_factory=list)

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

    # ---- extended indicator set -------------------------------------
    e200 = ema(c, 200) if len(c) >= 200 else ema(c, max(2, len(c) // 2))
    macd_line, macd_sig, macd_hist = macd(c)
    adx14 = adx(h, lo, c, 14)
    vol = volume_stats(bars)

    # Regime: ADX separates trending from ranging; the swing pattern
    # distinguishes an expanding range from a compressing one.
    struct_detail = detect_structure(h, lo, hi_idx, lo_idx, last)
    if adx14 >= 25:
        regime = "TRENDING"
    elif struct_detail["pattern"] == "EXPANSION":
        regime = "EXPANSION"
    elif struct_detail["pattern"] == "CONSOLIDATION":
        regime = "CONSOLIDATION"
    else:
        regime = "RANGING"

    # Momentum from MACD histogram slope plus RSI position.
    if macd_hist > 0 and r >= 50:
        momentum = "RISING"
    elif macd_hist < 0 and r <= 50:
        momentum = "FALLING"
    else:
        momentum = "NEUTRAL"

    # A breakout is only "confirmed" when the close is beyond the level AND
    # activity expanded. Price poking through on quiet tape is not a signal.
    breakout_confirmed = False
    breakout_level = 0.0
    if breakout == "UP":
        breakout_level = round(prior_high, 2)
        breakout_confirmed = vol.get("relative", 0.0) >= 1.2 and macd_hist > 0
    elif breakout == "DOWN":
        breakout_level = round(prior_low, 2)
        breakout_confirmed = vol.get("relative", 0.0) >= 1.2 and macd_hist < 0

    tol_lv = max(a * 0.5, 0.01)
    support_levels = ranked_levels(
        [float(lo[i]) for i in lo_idx], tol_lv, "support", last
    )
    resistance_levels = ranked_levels(
        [float(h[i]) for i in hi_idx], tol_lv, "resistance", last
    )

    gaps = fair_value_gaps(bars, a)
    blocks = order_blocks(bars, hi_idx, lo_idx, a)
    swings = swing_markers(bars, hi_idx, lo_idx)

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
        role=TF_ROLE.get(timeframe, "SETUP"),
        ema200=round(float(e200[-1]), 2),
        macd_line=round(macd_line, 3),
        macd_signal=round(macd_sig, 3),
        macd_hist=round(macd_hist, 3),
        adx14=round(adx14, 1),
        regime=regime,
        momentum=momentum,
        structure_detail=struct_detail,
        bos=bool(struct_detail["bos"]),
        choch=bool(struct_detail["choch"]),
        support_levels=support_levels,
        resistance_levels=resistance_levels,
        volume=vol,
        breakout_confirmed=breakout_confirmed,
        breakout_level=breakout_level,
        fvg=gaps,
        order_blocks=blocks,
        swings=swings,
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
    weights = {"M1": 1, "M5": 2, "M15": 3, "M30": 4, "H1": 5, "H4": 7, "D1": 9}
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
        "hierarchy": timeframe_hierarchy(tfs),
        "session_levels": session_levels(bars_by_tf.get("D1", [])),
        "volume": (
            next((t["volume"] for t in tfs if t["timeframe"] == "M15"), None)
            or next((t["volume"] for t in tfs if t.get("volume")), {})
        ),
    }


def _group_bias(tfs: list[dict], names: tuple[str, ...]) -> dict:
    """Collapse a group of timeframes into one directional read."""
    present = [t for t in tfs if t["timeframe"] in names]
    if not present:
        return {"bias": "UNKNOWN", "timeframes": [], "agree": False}
    ups = sum(1 for t in present if t["trend"] == "UP")
    downs = sum(1 for t in present if t["trend"] == "DOWN")
    if ups and not downs:
        bias = "BULLISH"
    elif downs and not ups:
        bias = "BEARISH"
    elif ups > downs:
        bias = "BULLISH"
    elif downs > ups:
        bias = "BEARISH"
    else:
        bias = "RANGE"
    return {
        "bias": bias,
        "timeframes": [t["timeframe"] for t in present],
        "agree": bool(present) and (ups == 0 or downs == 0),
    }


def timeframe_hierarchy(tfs: list[dict]) -> dict:
    """Split the timeframes into their decision roles.

    The setup engine reads direction from `major` and `intermediate`, and uses
    `setup`/`refinement` only for timing. This is what stops an M15 pullback
    from being mistaken for a trend reversal.
    """
    major = _group_bias(tfs, ("D1", "H4"))
    intermediate = _group_bias(tfs, ("H1", "M30"))
    setup = _group_bias(tfs, ("M15", "M5"))
    refinement = _group_bias(tfs, ("M1",))
    aligned = (
        major["bias"] == intermediate["bias"]
        and major["bias"] in ("BULLISH", "BEARISH")
    )
    return {
        "major": major,
        "intermediate": intermediate,
        "setup": setup,
        "refinement": refinement,
        "higher_aligned": aligned,
    }
