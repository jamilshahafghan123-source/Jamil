"""The analysis pipeline.

    market data -> trend -> support/resistance -> momentum -> volatility
                -> setup -> confidence -> risk manager -> TRADE / NO TRADE

Every stage returns its own numbers and a plain-language note, so the verdict can
always be traced back to what produced it.

This module **proposes**; it never sends anything. The result carries a ready
order (side, volume, entry, SL, TP) that a human — or a caller that explicitly
decides to — passes to POST /orders, which re-runs the whole risk policy anyway.

The confidence score is a transparent weighted blend of the stage scores, not a
learned model. Swap `score_confidence` for a model call if you want one; the
pipeline around it does not change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import Settings
from ..errors import InvalidRequestError
from ..mt5 import market, risk
from ..mt5.session import MT5Session
from . import indicators

# How much each stage contributes to the confidence score.
WEIGHTS = {
    "trend": 0.35,
    "momentum": 0.30,
    "support_resistance": 0.20,
    "volatility": 0.15,
}

RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 30.0


@dataclass
class Stage:
    """One step of the pipeline: a directional read plus why."""

    name: str
    # -1 (fully bearish) .. +1 (fully bullish); 0 means no opinion.
    bias: float
    # 0 .. 1, how strongly this stage holds that view.
    strength: float
    note: str
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "bias": round(self.bias, 3),
            "strength": round(self.strength, 3),
            "direction": "buy" if self.bias > 0 else "sell" if self.bias < 0 else "flat",
            "note": self.note,
            **self.data,
        }


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


# --- stages -------------------------------------------------------------------


def analyse_trend(closes: list[float], atr_value: float, min_efficiency: float) -> Stage:
    ema_fast = indicators.ema(closes, 20)
    ema_slow = indicators.ema(closes, 50)
    ema_long = indicators.ema(closes, 200)

    fast, slow = ema_fast[-1], ema_slow[-1]
    long = ema_long[-1] if len(closes) >= 200 else None
    price = closes[-1]

    if fast is None or slow is None or atr_value <= 0:
        return Stage("trend", 0.0, 0.0, "Not enough history to read a trend.")

    # Separation and slope, both measured in ATR so they compare across symbols.
    separation = (fast - slow) / atr_value
    slope = indicators.slope_per_bar(ema_fast, 10)
    slope_atr = (slope / atr_value) if slope is not None else 0.0

    bias = _clamp(separation * 0.8 + slope_atr * 4)
    strength = min(1.0, abs(bias))

    # The 200 EMA either backs the read or argues with it.
    if long is not None:
        above_long = price > long
        if (bias > 0) != above_long:
            strength *= 0.6

    # Moving averages cannot tell a trend from an oscillation; the efficiency
    # ratio can. A market retracing its own steps is not trending, however
    # convincingly the EMAs have separated.
    efficiency = indicators.efficiency_ratio(closes, 30) or 0.0
    trending = efficiency >= min_efficiency
    strength *= min(1.0, efficiency / 0.5)

    direction = "rising" if bias > 0.15 else "falling" if bias < -0.15 else "sideways"
    return Stage(
        "trend",
        bias,
        strength,
        f"EMA20 {'above' if separation > 0 else 'below'} EMA50 by "
        f"{abs(separation):.2f} ATR; price action {direction}; efficiency ratio "
        f"{efficiency:.2f}" + ("" if trending else " — ranging, not trending") + ".",
        {
            "ema_20": round(fast, 5),
            "ema_50": round(slow, 5),
            "ema_200": round(long, 5) if long is not None else None,
            "separation_atr": round(separation, 3),
            "efficiency_ratio": round(efficiency, 3),
            "trending": trending,
        },
    )


def analyse_support_resistance(
    highs: list[float], lows: list[float], price: float, atr_value: float
) -> Stage:
    swing_highs, swing_lows = indicators.swing_points(highs, lows, reach=2)
    tolerance = atr_value * 0.5

    resistances = [
        level
        for level in indicators.cluster_levels(swing_highs, tolerance)
        if float(level["price"]) > price
    ]
    supports = [
        level
        for level in indicators.cluster_levels(swing_lows, tolerance)
        if float(level["price"]) < price
    ]

    nearest_resistance = min(resistances, key=lambda l: float(l["price"])) if resistances else None
    nearest_support = max(supports, key=lambda l: float(l["price"])) if supports else None

    if not nearest_resistance or not nearest_support or atr_value <= 0:
        return Stage(
            "support_resistance",
            0.0,
            0.0,
            "No clear levels on both sides of price yet.",
            {
                "support": float(nearest_support["price"]) if nearest_support else None,
                "resistance": float(nearest_resistance["price"]) if nearest_resistance else None,
            },
        )

    support = float(nearest_support["price"])
    resistance = float(nearest_resistance["price"])
    room_up = (resistance - price) / atr_value
    room_down = (price - support) / atr_value

    # Sitting just under resistance is a poor long; just above support, a poor short.
    total = room_up + room_down
    bias = _clamp((room_up - room_down) / total) if total > 0 else 0.0
    strength = min(1.0, total / 6)

    return Stage(
        "support_resistance",
        bias,
        strength,
        f"Support {support:.5g} ({room_down:.1f} ATR below), resistance "
        f"{resistance:.5g} ({room_up:.1f} ATR above).",
        {
            "support": round(support, 5),
            "support_touches": int(nearest_support["touches"]),
            "resistance": round(resistance, 5),
            "resistance_touches": int(nearest_resistance["touches"]),
            "room_up_atr": round(room_up, 2),
            "room_down_atr": round(room_down, 2),
        },
    )


def analyse_momentum(closes: list[float]) -> Stage:
    rsi_series = indicators.rsi(closes, 14)
    _, _, histogram = indicators.macd(closes)

    rsi_value = rsi_series[-1]
    hist = histogram[-1]
    hist_prev = histogram[-2] if len(histogram) > 1 else None

    if rsi_value is None or hist is None:
        return Stage("momentum", 0.0, 0.0, "Not enough history for RSI/MACD.")

    rsi_bias = _clamp((rsi_value - 50) / 25)
    hist_bias = _clamp(hist / (abs(closes[-1]) * 0.001)) if closes[-1] else 0.0
    bias = _clamp(rsi_bias * 0.5 + hist_bias * 0.5)

    stretched = rsi_value >= RSI_OVERBOUGHT or rsi_value <= RSI_OVERSOLD
    rising = hist_prev is not None and hist > hist_prev
    strength = min(1.0, abs(bias))
    if stretched:
        # Overbought/oversold: the move is real but a poor place to join.
        strength *= 0.5

    return Stage(
        "momentum",
        bias,
        strength,
        f"RSI {rsi_value:.1f}"
        + (" (overbought)" if rsi_value >= RSI_OVERBOUGHT else "")
        + (" (oversold)" if rsi_value <= RSI_OVERSOLD else "")
        + f", MACD histogram {'expanding' if rising else 'contracting'}.",
        {
            "rsi": round(rsi_value, 2),
            "macd_histogram": round(hist, 6),
            "overbought": rsi_value >= RSI_OVERBOUGHT,
            "oversold": rsi_value <= RSI_OVERSOLD,
        },
    )


def analyse_volatility(
    atr_series: list[float | None], price: float, settings: Settings
) -> Stage:
    atr_value = atr_series[-1]
    if not atr_value or price <= 0:
        return Stage("volatility", 0.0, 0.0, "ATR unavailable.")

    percentile = indicators.percentile_rank(atr_series[-200:], atr_value)
    atr_pct = atr_value / price * 100
    extreme = percentile > settings.signal_max_volatility_percentile

    regime = (
        "extreme" if extreme else "elevated" if percentile > 70 else "quiet" if percentile < 30 else "normal"
    )

    # Volatility has no direction: it either supports taking a setup or it doesn't.
    strength = 0.0 if extreme else 1.0 - abs(percentile - 50) / 100

    return Stage(
        "volatility",
        0.0,
        strength,
        f"ATR {atr_value:.5g} ({atr_pct:.2f}% of price), {regime} for recent history"
        + (" — too wild to trade." if extreme else "."),
        {
            "atr": round(atr_value, 5),
            "atr_pct_of_price": round(atr_pct, 3),
            "percentile": round(percentile, 1),
            "regime": regime,
            "tradable": not extreme,
        },
    )


# --- setup + confidence -------------------------------------------------------


def build_setup(
    *,
    stages: dict[str, Stage],
    bid: float,
    ask: float,
    atr_value: float,
    digits: int,
    settings: Settings,
) -> dict[str, Any] | None:
    """Turn agreeing stages into an entry, stop loss and take profit."""
    trend = stages["trend"]
    momentum = stages["momentum"]
    volatility = stages["volatility"]

    if not volatility.data.get("tradable", False):
        return None
    if not trend.data.get("trending", False):
        return None
    if trend.bias == 0 or momentum.bias == 0:
        return None
    # Trend and momentum must point the same way.
    if (trend.bias > 0) != (momentum.bias > 0):
        return None

    side = "buy" if trend.bias > 0 else "sell"
    entry = ask if side == "buy" else bid
    distance = atr_value * settings.signal_sl_atr_multiple

    if side == "buy":
        stop = entry - distance
        target = entry + distance * settings.signal_reward_ratio
    else:
        stop = entry + distance
        target = entry - distance * settings.signal_reward_ratio

    # Keep the target on the near side of the level that would block it.
    levels = stages["support_resistance"].data
    blocker = levels.get("resistance") if side == "buy" else levels.get("support")
    capped = False
    if blocker:
        if side == "buy" and blocker < target:
            target, capped = float(blocker), True
        elif side == "sell" and blocker > target:
            target, capped = float(blocker), True

    risk_distance = abs(entry - stop)
    reward_distance = abs(target - entry)
    if risk_distance <= 0 or reward_distance <= 0:
        return None

    return {
        "side": side,
        "entry": round(entry, digits),
        "stop_loss": round(stop, digits),
        "take_profit": round(target, digits),
        "risk_distance": round(risk_distance, digits),
        "reward_distance": round(reward_distance, digits),
        "reward_ratio": round(reward_distance / risk_distance, 2),
        "target_capped_by_level": capped,
    }


def score_confidence(stages: dict[str, Stage], side: str) -> float:
    """Weighted blend of the stages, as a 0-100 score for the proposed side."""
    wanted = 1 if side == "buy" else -1
    total = 0.0

    for name, weight in WEIGHTS.items():
        stage = stages[name]
        if name == "volatility":
            # Directionless: contributes conviction, not a view.
            total += weight * stage.strength
            continue
        agrees = (stage.bias > 0 and wanted > 0) or (stage.bias < 0 and wanted < 0)
        total += weight * stage.strength * (1 if agrees else -1)

    return round(max(0.0, min(1.0, (total + 1) / 2)) * 100, 1)


# --- pipeline -----------------------------------------------------------------


async def generate(
    session: MT5Session,
    settings: Settings,
    *,
    symbol: str,
    timeframe: str | None = None,
    candles: int | None = None,
) -> dict[str, Any]:
    """Run the full pipeline for one symbol and return TRADE / NO TRADE."""
    timeframe = (timeframe or settings.signal_timeframe).upper()
    count = candles or settings.signal_candles

    symbol_info = await market.ensure_symbol(session, symbol)
    rows = await market.get_candles(
        session, symbol=symbol, timeframe=timeframe, count=count
    )
    if len(rows) < 60:
        raise InvalidRequestError(
            f"Only {len(rows)} candles available for {symbol} {timeframe}; "
            "the pipeline needs at least 60.",
            details={"symbol": symbol, "timeframe": timeframe, "candles": len(rows)},
        )

    highs = [row["high"] for row in rows]
    lows = [row["low"] for row in rows]
    closes = [row["close"] for row in rows]

    atr_series = indicators.atr(highs, lows, closes, settings.signal_atr_period)
    atr_value = atr_series[-1] or 0.0

    tick = await market.get_tick(session, symbol)
    bid, ask = float(tick["bid"]), float(tick["ask"])
    price = closes[-1]
    digits = int(symbol_info.get("digits", 5))

    stages = {
        "trend": analyse_trend(closes, atr_value, settings.signal_min_efficiency),
        "support_resistance": analyse_support_resistance(highs, lows, price, atr_value),
        "momentum": analyse_momentum(closes),
        "volatility": analyse_volatility(atr_series, price, settings),
    }

    setup = build_setup(
        stages=stages,
        bid=bid,
        ask=ask,
        atr_value=atr_value,
        digits=digits,
        settings=settings,
    )

    result: dict[str, Any] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "candles": len(rows),
        "as_of": rows[-1]["time"],
        "price": {"bid": bid, "ask": ask, "atr": round(atr_value, digits)},
        "stages": {name: stage.as_dict() for name, stage in stages.items()},
        "min_confidence": settings.signal_min_confidence,
        "executed": False,
    }

    if setup is None:
        return {
            **result,
            "decision": "no_trade",
            "confidence": 0.0,
            "reasons": [_no_setup_reason(stages)],
            "setup": None,
            "proposal": None,
        }

    confidence = score_confidence(stages, setup["side"])
    reasons = [stage.note for stage in stages.values()]

    if confidence < settings.signal_min_confidence:
        return {
            **result,
            "decision": "no_trade",
            "confidence": confidence,
            "reasons": [
                f"Confidence {confidence} is below the {settings.signal_min_confidence} "
                "threshold.",
                *reasons,
            ],
            "setup": setup,
            "proposal": None,
        }

    # Size the position from the risk budget, then put the whole thing through
    # the same policy that guards POST /orders.
    account = await session.run(lambda mt5: mt5.account_info())
    balance = float(account.balance) if account else 0.0
    volume = risk.suggested_volume(
        entry=setup["entry"],
        stop_loss=setup["stop_loss"],
        balance=balance,
        settings=settings,
        symbol_info=symbol_info,
    )

    if not volume:
        return {
            **result,
            "decision": "no_trade",
            "confidence": confidence,
            "reasons": [
                "No volume fits the risk budget for this stop distance.",
                *reasons,
            ],
            "setup": setup,
            "proposal": None,
        }

    proposal = {
        "symbol": symbol,
        "side": setup["side"],
        "type": "market",
        "volume": volume,
        "sl": setup["stop_loss"],
        "tp": setup["take_profit"],
    }

    try:
        assessment = await risk.evaluate_order(
            session,
            settings,
            symbol=symbol,
            side=setup["side"],
            volume=volume,
            entry=setup["entry"],
            sl=setup["stop_loss"],
            tp=setup["take_profit"],
            symbol_info=symbol_info,
        )
    except risk.RiskRejectedError as rejection:
        return {
            **result,
            "decision": "no_trade",
            "confidence": confidence,
            "reasons": [f"Risk manager: {rejection.message}", *reasons],
            "setup": setup,
            "proposal": proposal,
            "risk": {"passed": False, **rejection.details},
        }

    return {
        **result,
        "decision": "trade",
        "confidence": confidence,
        "reasons": reasons,
        "setup": setup,
        "proposal": proposal,
        "risk": {"passed": True, **assessment},
    }


def _no_setup_reason(stages: dict[str, Stage]) -> str:
    volatility = stages["volatility"]
    if not volatility.data.get("tradable", True):
        return volatility.note
    trend, momentum = stages["trend"], stages["momentum"]
    if not trend.data.get("trending", True):
        return (
            "The market is ranging, not trending (efficiency ratio "
            f"{trend.data.get('efficiency_ratio')}) — no trend setup."
        )
    if trend.bias == 0 or momentum.bias == 0:
        return "No directional read from trend or momentum."
    if (trend.bias > 0) != (momentum.bias > 0):
        return (
            f"Trend is {'bullish' if trend.bias > 0 else 'bearish'} while momentum is "
            f"{'bullish' if momentum.bias > 0 else 'bearish'} — no agreement, no setup."
        )
    return "No setup met the entry conditions."
