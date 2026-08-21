"""Private owner-only conversational market analyst.

This service is READ / ANALYSE / EXPLAIN only.

It can read the same deterministic XAUUSD market snapshot used by the trading
system, but it has no executor import and no path to place, modify or close an
order.

The deterministic setup engine owns all prices and confidence values.  The
language model may explain them conversationally but may not invent or change
them.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..config import settings
from .bot import collect_market_data
from .setup_engine import build_setup

log = logging.getLogger("owner_trader")

ALLOWED_TIMEFRAMES = {"M1", "M5", "M15", "M30", "H1", "H4", "D1"}

SYSTEM_PROMPT = """You are J Gold, the private market-analysis assistant for the owner of the J Gold AI platform.

You are having a direct, natural conversation with the owner while they watch
the live XAUUSD chart.

You receive MEASURED market information and a COMPUTED deterministic setup.
Those facts are authoritative.

You may:
- explain what the market is doing;
- explain BUY, SELL or NO_TRADE;
- explain break of structure (BOS), CHoCH, trend, momentum, EMA relationships,
  FVGs, support, resistance, swings, liquidity and pullbacks;
- explain whether the evidence currently looks more like continuation,
  pullback/retest, failed breakout/reversal, or genuinely unclear;
- say where the deterministic system is watching an entry;
- explain where NOT to enter and what confirmation is still missing;
- explain what would invalidate the current idea;
- answer follow-up questions using the recent conversation.

You must:
- use only numbers and market facts present in the supplied context;
- never invent a price, entry, stop, target, confidence or indicator value;
- never promise that price will go up or down;
- distinguish probability/evidence from certainty;
- never claim a BOS guarantees continuation;
- after BOS, explicitly consider:
    1. immediate continuation,
    2. pullback/retest then continuation,
    3. failed break / reversal,
    4. insufficient evidence;
- when discussing an entry, use only the computed setup's entry zone/trigger;
- if the setup is NO_TRADE, say what needs to happen before it becomes valid;
- never tell the owner that a trade is risk-free;
- never execute, modify or close a trade.

The owner may ask casually, for example:
"what do you think here?"
"after this BOS, continuation or pullback?"
"where would you wait?"
"why no sell?"
"where should I not enter?"

Answer conversationally and directly. Usually 3-7 sentences are enough.
"""


def _tf_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "timeframe": row.get("timeframe"),
        "last_close": row.get("last_close"),
        "trend": row.get("trend"),
        "momentum": row.get("momentum"),
        "regime": row.get("regime"),
        "rsi14": row.get("rsi14"),
        "adx14": row.get("adx14"),
        "atr14": row.get("atr14"),
        "ema20": row.get("ema_fast"),
        "ema50": row.get("ema_slow"),
        "ema200": row.get("ema200"),
        "macd_hist": row.get("macd_hist"),
        "structure": row.get("structure"),
        "structure_detail": row.get("structure_detail"),
        "bos": row.get("bos", False),
        "choch": row.get("choch", False),
        "breakout": row.get("breakout", "NONE"),
        "breakout_confirmed": row.get("breakout_confirmed", False),
        "pullback": row.get("pullback", "NONE"),
        "support_levels": row.get("support_levels", []),
        "resistance_levels": row.get("resistance_levels", []),
        "fvg": row.get("fvg", []),
        "order_blocks": row.get("order_blocks", []),
        "liquidity": row.get("liquidity", []),
        "swings": row.get("swings", []),
    }


def _fallback(question: str, context: dict[str, Any]) -> str:
    tf = context["selected_timeframe"]
    setup = context["setup"]

    action = setup.get("action", "NO_TRADE")
    confidence = setup.get("confidence", 0)

    trend = tf.get("trend", "UNKNOWN")
    momentum = tf.get("momentum", "NEUTRAL")
    bos = bool(tf.get("bos"))
    pullback = tf.get("pullback", "NONE")

    opening = (
        f"On {tf.get('timeframe')}, the measured trend is {trend} and "
        f"momentum is {momentum}."
    )

    if bos:
        opening += " A break of structure is currently detected."

    if pullback and pullback != "NONE":
        opening += f" The engine also detects a {pullback} pullback state."

    if action == "NO_TRADE":
        reason = (
            setup.get("blocking_reason")
            or setup.get("summary")
            or "the complete entry conditions are not confirmed yet"
        )
        return (
            f"{opening} I would not force an entry here. "
            f"The deterministic engine is currently NO_TRADE because {reason}. "
            "After a BOS I would watch whether the broken structure holds on a "
            "retest before treating continuation as confirmed."
        )

    low = setup.get("entry_low")
    high = setup.get("entry_high")
    trigger = setup.get("trigger_text")
    invalidation = setup.get("invalidation")

    return (
        f"{opening} The current deterministic setup is {action} at "
        f"{confidence}% confidence. The system is watching the existing entry "
        f"zone {low} to {high}, with confirmation from {trigger}. "
        f"I would not chase price outside that zone. "
        f"Invalidation: {invalidation}"
    )


async def answer(
    *,
    question: str,
    timeframe: str,
    risk_settings: Any,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    tf_name = timeframe.upper()
    if tf_name not in ALLOWED_TIMEFRAMES:
        tf_name = "M5"

    snapshot = await collect_market_data()
    setup = build_setup(snapshot, risk_settings)

    timeframes = [
        _tf_view(row)
        for row in snapshot.get("timeframes", [])
        if row.get("timeframe") in ALLOWED_TIMEFRAMES
    ]

    selected = next(
        (row for row in timeframes if row.get("timeframe") == tf_name),
        timeframes[0] if timeframes else {"timeframe": tf_name},
    )

    context = {
        "symbol": snapshot.get("symbol", settings.SYMBOL),
        "bid": snapshot.get("bid"),
        "ask": snapshot.get("ask"),
        "spread_points": snapshot.get("spread_points"),
        "selected_timeframe": selected,
        "timeframes": timeframes,
        "hierarchy": snapshot.get("hierarchy", {}),
        "session_levels": snapshot.get("session_levels", []),
        "setup": setup,
    }

    if not settings.ANTHROPIC_API_KEY:
        return {
            "answer": _fallback(question, context),
            "model": "deterministic-owner-fallback",
            "context": context,
        }

    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        return {
            "answer": _fallback(question, context),
            "model": "deterministic-owner-fallback",
            "context": context,
        }

    messages: list[dict[str, str]] = []

    for turn in (history or [])[-10:]:
        role = turn.get("role")
        text = str(turn.get("text", ""))[:2000]
        if role in {"user", "assistant"} and text:
            messages.append({"role": role, "content": text})

    payload = json.dumps(context, default=str)

    messages.append({
        "role": "user",
        "content": (
            f"Owner question: {question}\n\n"
            f"Current measured J Gold market context:\n{payload}"
        ),
    })

    try:
        client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = await client.messages.create(
            model=settings.ANALYST_MODEL,
            max_tokens=min(int(settings.ANALYST_MAX_TOKENS), 1000),
            system=SYSTEM_PROMPT,
            messages=messages,
        )

        text = next(
            (
                block.text
                for block in response.content
                if getattr(block, "type", None) == "text"
            ),
            None,
        )

        if not text:
            raise RuntimeError("empty owner trader response")

        return {
            "answer": text.strip(),
            "model": settings.ANALYST_MODEL,
            "context": context,
        }

    except Exception as exc:
        log.warning("owner trader model unavailable: %s", type(exc).__name__)
        return {
            "answer": _fallback(question, context),
            "model": "deterministic-owner-fallback",
            "context": context,
        }
