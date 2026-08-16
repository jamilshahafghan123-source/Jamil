"""The XAUUSD multi-timeframe strategy engine.

One instrument, one method, three timeframes:

    M15  the main trend       EMA 20/50/200 stack, slope, efficiency ratio
    M5   structure + momentum swing structure (HH/HL vs LH/LL), RSI 14, EMA 20/50
    M1   the entry trigger    pullback to EMA20 then a reclaim, RSI turning up

The verdict is BUY, SELL or NO_TRADE — nothing else. A single indicator crossing
is never enough: the trigger timeframe is only consulted once the trend and
structure timeframes already agree, and every timeframe must confirm the same
direction before a signal is produced.

Everything is computed from **closed** candles. The bar currently forming is
excluded, because it repaints until it closes and a strategy that reads it is
testing the future against itself.

Prices are never invented. Entry comes from the live tick, stops come from the
market's own structure widened by ATR, and targets are multiples of that risk.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Sequence

from ..config import Settings
from . import indicators

logger = logging.getLogger(__name__)

Direction = Literal["BUY", "SELL", "NO_TRADE"]
Bias = Literal["bullish", "bearish", "neutral"]

# What each timeframe contributes to the 0-100 score.
WEIGHTS = {"trend": 40.0, "structure": 35.0, "trigger": 25.0}

EMA_FAST, EMA_MID, EMA_SLOW = 20, 50, 200
RSI_PERIOD = 14
ATR_PERIOD = 14
SWING_REACH = 2


@dataclass
class TimeframeRead:
    """One timeframe's opinion, with the numbers it was formed from."""

    timeframe: str
    bias: Bias
    # 0..1 - how convincing this timeframe finds its own read.
    strength: float
    reasons: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def confirms(self, direction: Direction) -> bool:
        if direction == "BUY":
            return self.bias == "bullish"
        if direction == "SELL":
            return self.bias == "bearish"
        return False

    def as_dict(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "bias": self.bias,
            "strength": round(self.strength, 3),
            "reasons": self.reasons,
            **self.data,
        }


@dataclass
class Candles:
    """A closed-candle series, split into the arrays the indicators want."""

    timeframe: str
    time: list[str]
    open: list[float]
    high: list[float]
    low: list[float]
    close: list[float]

    def __len__(self) -> int:
        return len(self.close)

    @classmethod
    def from_rows(cls, timeframe: str, rows: Sequence[dict[str, Any]]) -> "Candles":
        return cls(
            timeframe=timeframe,
            time=[str(row["time"]) for row in rows],
            open=[float(row["open"]) for row in rows],
            high=[float(row["high"]) for row in rows],
            low=[float(row["low"]) for row in rows],
            close=[float(row["close"]) for row in rows],
        )


# --- M15: the main trend ------------------------------------------------------


def read_trend(candles: Candles, settings: Settings) -> TimeframeRead:
    """EMA 20/50/200 stack plus slope, filtered by how directional the move is.

    A stack alone is not a trend: price can oscillate through three EMAs and
    leave them nominally ordered. The efficiency ratio separates a market that
    is going somewhere from one retracing its own steps.
    """
    closes = candles.close
    ema_fast = indicators.ema(closes, EMA_FAST)
    ema_mid = indicators.ema(closes, EMA_MID)
    ema_slow = indicators.ema(closes, EMA_SLOW)
    atr = indicators.atr(candles.high, candles.low, closes, ATR_PERIOD)

    fast, mid, slow = ema_fast[-1], ema_mid[-1], ema_slow[-1]
    atr_value = atr[-1] or 0.0
    price = closes[-1]

    if fast is None or mid is None or slow is None or atr_value <= 0:
        return TimeframeRead(
            candles.timeframe,
            "neutral",
            0.0,
            ["Not enough closed history for the EMA 20/50/200 stack."],
        )

    stacked_up = fast > mid > slow and price > slow
    stacked_down = fast < mid < slow and price < slow
    efficiency = indicators.efficiency_ratio(closes, 30) or 0.0
    slope = indicators.slope_per_bar(ema_mid, 10) or 0.0
    slope_atr = slope / atr_value
    separation = abs(fast - mid) / atr_value

    reasons: list[str] = []
    data = {
        "ema_20": round(fast, 5),
        "ema_50": round(mid, 5),
        "ema_200": round(slow, 5),
        "atr": round(atr_value, 5),
        "efficiency_ratio": round(efficiency, 3),
        "ema_slope_atr": round(slope_atr, 4),
        "separation_atr": round(separation, 3),
        "closed_bars": len(candles),
    }

    if not (stacked_up or stacked_down):
        reasons.append(
            f"EMA 20/50/200 are not stacked ({fast:.2f}/{mid:.2f}/{slow:.2f}) — no trend."
        )
        return TimeframeRead(candles.timeframe, "neutral", 0.0, reasons, data)

    if efficiency < settings.signal_min_efficiency:
        reasons.append(
            f"Efficiency ratio {efficiency:.2f} is below {settings.signal_min_efficiency} — "
            "the market is ranging, not trending."
        )
        return TimeframeRead(candles.timeframe, "neutral", 0.0, reasons, data)

    bias: Bias = "bullish" if stacked_up else "bearish"
    # The EMA50 must be moving the same way the stack points.
    if (bias == "bullish" and slope_atr <= 0) or (bias == "bearish" and slope_atr >= 0):
        reasons.append(
            f"EMA 50 slope ({slope_atr:+.3f} ATR/bar) contradicts the stack — trend stalling."
        )
        return TimeframeRead(candles.timeframe, "neutral", 0.0, reasons, data)

    strength = min(
        1.0,
        0.4 * min(1.0, separation / 1.5)
        + 0.3 * min(1.0, efficiency / 0.6)
        + 0.3 * min(1.0, abs(slope_atr) / 0.15),
    )
    reasons.append(
        f"M15 EMA 20/50/200 stacked {'up' if stacked_up else 'down'} with price "
        f"{'above' if stacked_up else 'below'} the 200; EMA50 slope {slope_atr:+.3f} ATR/bar, "
        f"efficiency ratio {efficiency:.2f}."
    )
    return TimeframeRead(candles.timeframe, bias, strength, reasons, data)


def _swings(candles: Candles) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Pivot highs and lows, with each swing counted once."""
    highs, lows = indicators.swing_points(candles.high, candles.low, SWING_REACH)
    separation = SWING_REACH * 2 + 1
    return (
        indicators.distinct_swings(highs, min_separation=separation, keep="high"),
        indicators.distinct_swings(lows, min_separation=separation, keep="low"),
    )


# --- M5: structure and momentum -----------------------------------------------


def read_structure(candles: Candles, settings: Settings) -> TimeframeRead:
    """Swing structure (higher highs and lows, or lower ones) plus RSI 14.

    Structure is what price actually did; RSI is only allowed to confirm it, so
    a momentum reading on its own can never produce a signal.
    """
    closes = candles.close
    swing_highs, swing_lows = _swings(candles)
    rsi = indicators.rsi(closes, RSI_PERIOD)
    ema_fast = indicators.ema(closes, EMA_FAST)
    ema_mid = indicators.ema(closes, EMA_MID)

    rsi_value = rsi[-1]
    fast, mid = ema_fast[-1], ema_mid[-1]

    if len(swing_highs) < 2 or len(swing_lows) < 2 or rsi_value is None or fast is None:
        return TimeframeRead(
            candles.timeframe,
            "neutral",
            0.0,
            ["Not enough closed structure (need at least two swings each side)."],
        )

    last_highs = [price for _, price in swing_highs[-2:]]
    last_lows = [price for _, price in swing_lows[-2:]]
    higher_highs = last_highs[-1] > last_highs[-2]
    higher_lows = last_lows[-1] > last_lows[-2]
    lower_highs = last_highs[-1] < last_highs[-2]
    lower_lows = last_lows[-1] < last_lows[-2]

    rsi_prev = rsi[-2] if len(rsi) > 1 and rsi[-2] is not None else rsi_value
    rsi_rising = rsi_value >= rsi_prev

    data = {
        "swing_high": round(last_highs[-1], 5),
        "previous_swing_high": round(last_highs[-2], 5),
        "swing_low": round(last_lows[-1], 5),
        "previous_swing_low": round(last_lows[-2], 5),
        "rsi": round(rsi_value, 2),
        "rsi_rising": rsi_rising,
        "ema_20": round(fast, 5),
        "ema_50": round(mid, 5) if mid is not None else None,
        "closed_bars": len(candles),
    }
    reasons: list[str] = []

    bullish_structure = higher_highs and higher_lows
    bearish_structure = lower_highs and lower_lows

    if not (bullish_structure or bearish_structure):
        reasons.append(
            "M5 structure is mixed — no consecutive higher highs and lows, or lower ones."
        )
        return TimeframeRead(candles.timeframe, "neutral", 0.0, reasons, data)

    bias: Bias = "bullish" if bullish_structure else "bearish"

    # Momentum has to agree with the structure, and must not already be spent.
    if bias == "bullish":
        if rsi_value < 50:
            reasons.append(f"M5 RSI {rsi_value:.1f} is below 50 — momentum contradicts structure.")
            return TimeframeRead(candles.timeframe, "neutral", 0.0, reasons, data)
        if rsi_value >= settings.strategy_rsi_overbought:
            reasons.append(
                f"M5 RSI {rsi_value:.1f} is over-extended (>= "
                f"{settings.strategy_rsi_overbought}) — a poor place to join."
            )
            return TimeframeRead(candles.timeframe, "neutral", 0.0, reasons, data)
    else:
        if rsi_value > 50:
            reasons.append(f"M5 RSI {rsi_value:.1f} is above 50 — momentum contradicts structure.")
            return TimeframeRead(candles.timeframe, "neutral", 0.0, reasons, data)
        if rsi_value <= settings.strategy_rsi_oversold:
            reasons.append(
                f"M5 RSI {rsi_value:.1f} is over-extended (<= "
                f"{settings.strategy_rsi_oversold}) — a poor place to join."
            )
            return TimeframeRead(candles.timeframe, "neutral", 0.0, reasons, data)

    ema_agrees = mid is None or (fast > mid if bias == "bullish" else fast < mid)
    distance = abs(rsi_value - 50) / 25
    strength = min(1.0, 0.6 + 0.25 * min(1.0, distance) + (0.15 if ema_agrees else 0.0))

    reasons.append(
        f"M5 structure is {'higher highs and higher lows' if bullish_structure else 'lower highs and lower lows'} "
        f"({last_lows[-2]:.2f} → {last_lows[-1]:.2f} on the lows); RSI {rsi_value:.1f}"
        f"{' rising' if rsi_rising else ' easing'}, EMA20 "
        f"{'above' if ema_agrees and bias == 'bullish' else 'below' if ema_agrees else 'against'} EMA50."
    )
    return TimeframeRead(candles.timeframe, bias, strength, reasons, data)


# --- M1: the entry trigger ----------------------------------------------------


def read_trigger(candles: Candles, direction: Direction, settings: Settings) -> TimeframeRead:
    """A pullback to EMA20 followed by a reclaim, in the direction already agreed.

    This is deliberately the last thing consulted and is only ever asked about a
    direction the higher timeframes have already settled, so it can time an
    entry but never choose one.
    """
    closes = candles.close
    ema_fast = indicators.ema(closes, EMA_FAST)
    rsi = indicators.rsi(closes, RSI_PERIOD)
    atr = indicators.atr(candles.high, candles.low, closes, ATR_PERIOD)

    fast = ema_fast[-1]
    rsi_value = rsi[-1]
    atr_value = atr[-1] or 0.0

    if fast is None or rsi_value is None or atr_value <= 0:
        return TimeframeRead(
            candles.timeframe, "neutral", 0.0, ["Not enough closed M1 history for a trigger."]
        )

    lookback = min(settings.strategy_trigger_lookback, len(closes) - 1)
    window = range(len(closes) - lookback, len(closes))
    close, previous_close = closes[-1], closes[-2]
    prev_ema = ema_fast[-2]
    rsi_prev = rsi[-2] if rsi[-2] is not None else rsi_value

    data = {
        "close": round(close, 5),
        "ema_20": round(fast, 5),
        "rsi": round(rsi_value, 2),
        "atr": round(atr_value, 5),
        "lookback": lookback,
        "closed_bars": len(candles),
    }
    reasons: list[str] = []

    if direction == "BUY":
        # Did price actually come back to the average before turning up again?
        pulled_back = any(
            ema_fast[i] is not None and candles.low[i] <= ema_fast[i] + atr_value * 0.25
            for i in window
        )
        reclaimed = close > fast and (
            prev_ema is None or previous_close <= prev_ema or any(
                ema_fast[i] is not None and closes[i] <= ema_fast[i] for i in window
            )
        )
        momentum = rsi_value > 50 and rsi_value >= rsi_prev
        conditions = {"pullback": pulled_back, "reclaim": reclaimed, "rsi_turning_up": momentum}
    elif direction == "SELL":
        pulled_back = any(
            ema_fast[i] is not None and candles.high[i] >= ema_fast[i] - atr_value * 0.25
            for i in window
        )
        reclaimed = close < fast and (
            prev_ema is None or previous_close >= prev_ema or any(
                ema_fast[i] is not None and closes[i] >= ema_fast[i] for i in window
            )
        )
        momentum = rsi_value < 50 and rsi_value <= rsi_prev
        conditions = {"pullback": pulled_back, "reclaim": reclaimed, "rsi_turning_down": momentum}
    else:
        return TimeframeRead(candles.timeframe, "neutral", 0.0, ["No direction to trigger on."])

    data["conditions"] = conditions
    met = sum(1 for value in conditions.values() if value)

    if met < len(conditions):
        missing = [name for name, value in conditions.items() if not value]
        reasons.append(f"M1 trigger incomplete — missing: {', '.join(missing)}.")
        return TimeframeRead(candles.timeframe, "neutral", 0.0, reasons, data)

    bias: Bias = "bullish" if direction == "BUY" else "bearish"
    # A trigger close to the average is a better entry than one already extended.
    stretch = abs(close - fast) / atr_value
    strength = max(0.4, min(1.0, 1.0 - stretch / 3))
    reasons.append(
        f"M1 pulled back to EMA20 and closed {'above' if direction == 'BUY' else 'below'} it "
        f"at {close:.2f} ({stretch:.2f} ATR away), RSI {rsi_value:.1f} turning "
        f"{'up' if direction == 'BUY' else 'down'}."
    )
    return TimeframeRead(candles.timeframe, bias, strength, reasons, data)


# --- stops, targets and scoring ------------------------------------------------


def stop_from_structure(
    *,
    direction: Direction,
    entry: float,
    structure: Candles,
    atr_value: float,
    settings: Settings,
    digits: int,
) -> tuple[float, str]:
    """Place the stop beyond the last swing that would have to break, plus ATR.

    Clamped into a band of ATR so neither a very tight swing nor a single wild
    bar produces a stop the position sizing cannot live with.
    """
    swing_highs, swing_lows = _swings(structure)
    buffer = atr_value * settings.strategy_sl_atr_buffer
    minimum = atr_value * settings.strategy_sl_min_atr
    maximum = atr_value * settings.strategy_sl_max_atr

    if direction == "BUY":
        candidates = [price for _, price in swing_lows if price < entry]
        anchor = max(candidates) if candidates else entry - minimum
        distance = (entry - anchor) + buffer
        note = "last M5 swing low" if candidates else "ATR floor (no swing low below entry)"
    else:
        candidates = [price for _, price in swing_highs if price > entry]
        anchor = min(candidates) if candidates else entry + minimum
        distance = (anchor - entry) + buffer
        note = "last M5 swing high" if candidates else "ATR ceiling (no swing high above entry)"

    clamped = max(minimum, min(maximum, distance))
    if clamped != distance:
        note += f", clamped to {clamped / atr_value:.1f} ATR"

    stop = entry - clamped if direction == "BUY" else entry + clamped
    return round(stop, digits), note


def targets_from_risk(
    *, direction: Direction, entry: float, stop: float, settings: Settings, digits: int
) -> tuple[dict[str, float], dict[str, float]]:
    """TP1/2/3 as configurable multiples of the risk distance."""
    risk = abs(entry - stop)
    ratios = {
        "tp1": settings.strategy_tp1_r,
        "tp2": settings.strategy_tp2_r,
        "tp3": settings.strategy_tp3_r,
    }
    sign = 1 if direction == "BUY" else -1
    targets = {
        name: round(entry + sign * risk * ratio, digits) for name, ratio in ratios.items()
    }
    return targets, {name: round(ratio, 2) for name, ratio in ratios.items()}


def score(reads: dict[str, TimeframeRead]) -> float:
    """0-100 from the three timeframes, weighted by the job each one does."""
    total = sum(WEIGHTS[name] * read.strength for name, read in reads.items())
    return round(total, 1)


# --- the engine ---------------------------------------------------------------


def evaluate(
    *,
    symbol: str,
    trend_candles: Candles,
    structure_candles: Candles,
    trigger_candles: Candles,
    bid: float,
    ask: float,
    digits: int,
    settings: Settings,
) -> dict[str, Any]:
    """Run the full strategy and return one BUY / SELL / NO_TRADE signal.

    Callers supply closed candles and the live quote; this function does no I/O
    and invents no prices.
    """
    timestamp = datetime.now(tz=timezone.utc)

    def no_trade(reasons: list[str], reads: dict[str, TimeframeRead]) -> dict[str, Any]:
        return _signal(
            symbol=symbol,
            direction="NO_TRADE",
            signal_score=score(reads) if len(reads) == 3 else 0.0,
            entry=None,
            stop_loss=None,
            targets=None,
            ratios=None,
            reads=reads,
            reasons=reasons,
            timestamp=timestamp,
            settings=settings,
        )

    # Requirement: enough closed history, or no opinion at all.
    minimums = {
        "trend": (trend_candles, EMA_SLOW + 10),
        "structure": (structure_candles, 60),
        "trigger": (trigger_candles, 60),
    }
    for name, (candles, needed) in minimums.items():
        if len(candles) < needed:
            return no_trade(
                [
                    f"Insufficient closed {candles.timeframe} data: {len(candles)} bars, "
                    f"need {needed} for the {name} read."
                ],
                {},
            )

    trend = read_trend(trend_candles, settings)
    if trend.bias == "neutral":
        return no_trade(trend.reasons, {})

    direction: Direction = "BUY" if trend.bias == "bullish" else "SELL"

    structure = read_structure(structure_candles, settings)
    if not structure.confirms(direction):
        return no_trade(
            [
                f"{trend_candles.timeframe} is {trend.bias} but "
                f"{structure_candles.timeframe} structure is {structure.bias} — "
                "timeframes disagree.",
                *trend.reasons,
                *structure.reasons,
            ],
            {},
        )

    trigger = read_trigger(trigger_candles, direction, settings)
    if not trigger.confirms(direction):
        return no_trade(
            [
                f"{trend_candles.timeframe} and {structure_candles.timeframe} agree on "
                f"{direction}, but the {trigger_candles.timeframe} entry trigger has not fired.",
                *trigger.reasons,
            ],
            {},
        )

    reads = {"trend": trend, "structure": structure, "trigger": trigger}
    total = score(reads)
    if total < settings.strategy_min_score:
        return no_trade(
            [
                f"All three timeframes agree on {direction} but the signal scores "
                f"{total}, below the {settings.strategy_min_score} threshold.",
                *trend.reasons,
                *structure.reasons,
                *trigger.reasons,
            ],
            reads,
        )

    # Entry is the price the order would actually fill at — never a candle close.
    entry = ask if direction == "BUY" else bid
    atr_value = float(trend.data.get("atr") or 0.0)
    stop, stop_note = stop_from_structure(
        direction=direction,
        entry=entry,
        structure=structure_candles,
        atr_value=atr_value,
        settings=settings,
        digits=digits,
    )
    targets, ratios = targets_from_risk(
        direction=direction, entry=entry, stop=stop, settings=settings, digits=digits
    )

    reasons = [
        *trend.reasons,
        *structure.reasons,
        *trigger.reasons,
        f"Stop placed beyond the {stop_note} ({abs(entry - stop):.2f} away, "
        f"{abs(entry - stop) / atr_value:.1f} ATR).",
        f"Targets at {settings.strategy_tp1_r}R / {settings.strategy_tp2_r}R / "
        f"{settings.strategy_tp3_r}R of that risk.",
    ]

    return _signal(
        symbol=symbol,
        direction=direction,
        signal_score=total,
        entry=round(entry, digits),
        stop_loss=stop,
        targets=targets,
        ratios=ratios,
        reads=reads,
        reasons=reasons,
        timestamp=timestamp,
        settings=settings,
    )


def _signal(
    *,
    symbol: str,
    direction: Direction,
    signal_score: float,
    entry: float | None,
    stop_loss: float | None,
    targets: dict[str, float] | None,
    ratios: dict[str, float] | None,
    reads: dict[str, TimeframeRead],
    reasons: list[str],
    timestamp: datetime,
    settings: Settings,
) -> dict[str, Any]:
    """Assemble the signal payload. Every field is present on every verdict."""
    confirmation = {
        role: read.as_dict() for role, read in reads.items()
    }
    aligned = bool(reads) and all(read.confirms(direction) for read in reads.values())

    return {
        "symbol": symbol,
        "direction": direction,
        "signal_score": signal_score,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": targets or {"tp1": None, "tp2": None, "tp3": None},
        "risk_reward": ratios or {"tp1": None, "tp2": None, "tp3": None},
        "trend": {
            "primary": reads["trend"].bias if "trend" in reads else "neutral",
            "trend_timeframe": settings.strategy_trend_timeframe,
            "structure_timeframe": settings.strategy_structure_timeframe,
            "trigger_timeframe": settings.strategy_trigger_timeframe,
        },
        "reasons": reasons,
        "timeframe_confirmation": {
            "aligned": aligned,
            "roles": confirmation,
        },
        "timestamp": timestamp,
        "min_score": settings.strategy_min_score,
        # Which target the order proposal will carry, since MT5 takes one TP.
        "order_target": settings.strategy_order_tp,
    }
