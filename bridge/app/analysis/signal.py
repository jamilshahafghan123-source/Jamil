"""Wiring between the strategy engine, the risk manager and the callers.

    closed candles (M15/M5/M1) -> strategy engine -> BUY / SELL / NO_TRADE
                               -> position sizing -> risk manager -> proposal

This module fetches data and applies the existing risk controls to whatever the
strategy decides. It **proposes** and never sends: the returned `proposal` is
handed to `POST /orders` — by a human through the desk, or by the bot — which
re-runs the entire risk policy, the order_check pre-flight and the demo guard.

There is exactly one signal engine and one order path; nothing here duplicates
either.
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import Settings
from ..mt5 import market, risk
from ..mt5.session import MT5Session
from . import strategy
from .strategy import Candles

logger = logging.getLogger(__name__)


async def closed_candles(
    session: MT5Session, *, symbol: str, timeframe: str, count: int
) -> Candles:
    """Fetch `count` **closed** candles.

    `offset=1` skips the bar still forming. That bar repaints until it closes,
    so confirming on it means confirming on a value that has not happened yet.
    """
    rows = await market.get_candles(
        session, symbol=symbol, timeframe=timeframe, count=count, offset=1
    )
    return Candles.from_rows(timeframe, rows)


async def generate(
    session: MT5Session,
    settings: Settings,
    *,
    symbol: str,
    timeframe: str | None = None,
    candles: int | None = None,
) -> dict[str, Any]:
    """Run the strategy for one symbol and size anything it proposes.

    `timeframe` and `candles` are accepted for API compatibility but the engine
    is multi-timeframe by definition: it always reads the trend, structure and
    trigger timeframes from settings.
    """
    symbol_info = await market.ensure_symbol(session, symbol)
    digits = int(symbol_info.get("digits", 5))

    trend = await closed_candles(
        session,
        symbol=symbol,
        timeframe=settings.strategy_trend_timeframe,
        count=settings.strategy_trend_candles,
    )
    structure = await closed_candles(
        session,
        symbol=symbol,
        timeframe=settings.strategy_structure_timeframe,
        count=settings.strategy_structure_candles,
    )
    trigger = await closed_candles(
        session,
        symbol=symbol,
        timeframe=settings.strategy_trigger_timeframe,
        count=settings.strategy_trigger_candles,
    )

    tick = await market.get_tick(session, symbol)
    bid, ask = float(tick["bid"]), float(tick["ask"])

    signal = strategy.evaluate(
        symbol=symbol,
        trend_candles=trend,
        structure_candles=structure,
        trigger_candles=trigger,
        bid=bid,
        ask=ask,
        digits=digits,
        settings=settings,
    )

    signal["price"] = {"bid": bid, "ask": ask}
    signal["as_of"] = trend.time[-1] if len(trend) else None
    # The execution-facing view of the same verdict, for the bot and the desk.
    signal["decision"] = "no_trade" if signal["direction"] == "NO_TRADE" else "trade"
    signal["proposal"] = None
    signal["executed"] = False

    if signal["direction"] == "NO_TRADE":
        return signal

    volume = risk.suggested_volume(
        entry=signal["entry"],
        stop_loss=signal["stop_loss"],
        balance=await _balance(session),
        settings=settings,
        symbol_info=symbol_info,
    )
    if not volume:
        signal["decision"] = "no_trade"
        signal["reasons"] = [
            "No volume fits the risk budget for this stop distance.",
            *signal["reasons"],
        ]
        return signal

    side = "buy" if signal["direction"] == "BUY" else "sell"
    target = signal["take_profit"].get(settings.strategy_order_tp) or signal["take_profit"]["tp2"]
    proposal = {
        "symbol": symbol,
        "side": side,
        "type": "market",
        "volume": volume,
        "sl": signal["stop_loss"],
        "tp": target,
    }
    signal["proposal"] = proposal

    # Same policy that guards POST /orders, run here so a caller can see the
    # verdict before sending anything.
    try:
        assessment = await risk.evaluate_order(
            session,
            settings,
            symbol=symbol,
            side=side,
            volume=volume,
            entry=signal["entry"],
            sl=signal["stop_loss"],
            tp=target,
            symbol_info=symbol_info,
        )
    except risk.RiskRejectedError as rejection:
        signal["decision"] = "no_trade"
        signal["risk"] = {"passed": False, **rejection.details}
        signal["reasons"] = [f"Risk manager: {rejection.message}", *signal["reasons"]]
        return signal

    signal["risk"] = {"passed": True, **assessment}
    return signal


async def _balance(session: MT5Session) -> float:
    account = await session.run(lambda mt5: mt5.account_info())
    return float(account.balance) if account else 0.0
