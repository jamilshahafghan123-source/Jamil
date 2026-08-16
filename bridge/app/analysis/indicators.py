"""Technical indicators over plain lists of floats.

Dependency-free on purpose: the bridge only pulls numpy in through MetaTrader5
on Windows, and these need to run (and be tested) anywhere. Every function
returns a list aligned to the input, using None for the leading bars where the
indicator has no value yet, so callers can index by bar without bookkeeping.
"""

from __future__ import annotations

from typing import Sequence

Series = Sequence[float]
Optional = list[float | None]


def sma(values: Series, period: int) -> Optional:
    if period <= 0:
        raise ValueError("period must be positive")
    out: Optional = [None] * len(values)
    if len(values) < period:
        return out
    window = sum(values[:period])
    out[period - 1] = window / period
    for i in range(period, len(values)):
        window += values[i] - values[i - period]
        out[i] = window / period
    return out


def ema(values: Series, period: int) -> Optional:
    if period <= 0:
        raise ValueError("period must be positive")
    out: Optional = [None] * len(values)
    if len(values) < period:
        return out
    multiplier = 2 / (period + 1)
    # Seed with the SMA of the first window, the usual convention.
    current = sum(values[:period]) / period
    out[period - 1] = current
    for i in range(period, len(values)):
        current = (values[i] - current) * multiplier + current
        out[i] = current
    return out


def wilder_smooth(values: Series, period: int) -> Optional:
    """Wilder's smoothing (used by RSI and ATR): an EMA with alpha = 1/period."""
    out: Optional = [None] * len(values)
    if len(values) < period:
        return out
    current = sum(values[:period]) / period
    out[period - 1] = current
    for i in range(period, len(values)):
        current = (current * (period - 1) + values[i]) / period
        out[i] = current
    return out


def rsi(closes: Series, period: int = 14) -> Optional:
    out: Optional = [None] * len(closes)
    if len(closes) <= period:
        return out

    gains = [0.0]
    losses = [0.0]
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = wilder_smooth(gains[1:], period)
    avg_loss = wilder_smooth(losses[1:], period)

    for i, (gain, loss) in enumerate(zip(avg_gain, avg_loss), start=1):
        if gain is None or loss is None:
            continue
        if loss == 0:
            out[i] = 100.0
        else:
            rs = gain / loss
            out[i] = 100 - (100 / (1 + rs))
    return out


def macd(
    closes: Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[Optional, Optional, Optional]:
    """Returns (macd line, signal line, histogram)."""
    fast_ema = ema(closes, fast)
    slow_ema = ema(closes, slow)

    line: Optional = [
        None if f is None or s is None else f - s for f, s in zip(fast_ema, slow_ema)
    ]

    defined = [value for value in line if value is not None]
    signal_tail = ema(defined, signal)
    offset = len(line) - len(defined)

    signal_line: Optional = [None] * len(line)
    for i, value in enumerate(signal_tail):
        signal_line[offset + i] = value

    histogram: Optional = [
        None if m is None or s is None else m - s for m, s in zip(line, signal_line)
    ]
    return line, signal_line, histogram


def true_range(highs: Series, lows: Series, closes: Series) -> list[float]:
    out = [highs[0] - lows[0]] if highs else []
    for i in range(1, len(highs)):
        out.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )
    return out


def atr(highs: Series, lows: Series, closes: Series, period: int = 14) -> Optional:
    return wilder_smooth(true_range(highs, lows, closes), period)


def efficiency_ratio(closes: Series, period: int = 30) -> float | None:
    """Kaufman's efficiency ratio: net travel divided by total travel.

    Near 1.0 the market is going somewhere in a straight line; near 0.0 it is
    covering the same ground repeatedly. This is what separates a trend from an
    oscillation that merely looks like one to a pair of moving averages.
    """
    if len(closes) <= period or period <= 0:
        return None
    window = closes[-(period + 1) :]
    direction = abs(window[-1] - window[0])
    volatility = sum(abs(window[i] - window[i - 1]) for i in range(1, len(window)))
    if volatility == 0:
        return 0.0
    return direction / volatility


def slope_per_bar(values: Sequence[float | None], bars: int) -> float | None:
    """Average change per bar over the last `bars` defined values."""
    defined = [value for value in values if value is not None]
    if len(defined) <= bars or bars <= 0:
        return None
    return (defined[-1] - defined[-1 - bars]) / bars


def percentile_rank(values: Sequence[float | None], value: float) -> float:
    """Share of `values` at or below `value`, as a percentage."""
    defined = [v for v in values if v is not None]
    if not defined:
        return 0.0
    below = sum(1 for v in defined if v <= value)
    return below / len(defined) * 100


def swing_points(
    highs: Series, lows: Series, reach: int = 2
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Fractal pivots: bars whose high (low) beats `reach` bars on either side."""
    swing_highs: list[tuple[int, float]] = []
    swing_lows: list[tuple[int, float]] = []

    for i in range(reach, len(highs) - reach):
        window = range(i - reach, i + reach + 1)
        if all(highs[i] >= highs[j] for j in window) and any(
            highs[i] > highs[j] for j in window
        ):
            swing_highs.append((i, highs[i]))
        if all(lows[i] <= lows[j] for j in window) and any(lows[i] < lows[j] for j in window):
            swing_lows.append((i, lows[i]))

    return swing_highs, swing_lows


def distinct_swings(
    points: Sequence[tuple[int, float]], *, min_separation: int, keep: str = "high"
) -> list[tuple[int, float]]:
    """Collapse pivots belonging to the same swing into one.

    A rounded top prints several qualifying pivots a bar or two apart. Counting
    them as separate swings makes "higher high" comparisons meaningless — they
    compare a swing against itself — so pivots closer together than
    `min_separation` bars are merged, keeping the more extreme price.
    """
    if not points:
        return []

    merged: list[tuple[int, float]] = [points[0]]
    for index, price in points[1:]:
        last_index, last_price = merged[-1]
        if index - last_index < min_separation:
            better = price > last_price if keep == "high" else price < last_price
            if better:
                merged[-1] = (index, price)
        else:
            merged.append((index, price))
    return merged


def cluster_levels(
    points: Sequence[tuple[int, float]], tolerance: float
) -> list[dict[str, float | int]]:
    """Group nearby pivots into levels. More touches means a level that matters more."""
    if not points or tolerance <= 0:
        return []

    levels: list[dict[str, float | int]] = []
    for _, price in sorted(points, key=lambda item: item[1]):
        if levels and abs(price - float(levels[-1]["price"])) <= tolerance:
            level = levels[-1]
            touches = int(level["touches"]) + 1
            # Running mean keeps the level centred on its pivots.
            level["price"] = (float(level["price"]) * (touches - 1) + price) / touches
            level["touches"] = touches
        else:
            levels.append({"price": price, "touches": 1})
    return levels
