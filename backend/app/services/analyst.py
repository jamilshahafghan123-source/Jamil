"""AI market analyst.

Contract with the model, enforced in code rather than requested politely:

1. The model receives ONLY the deterministic snapshot from indicators.py —
   real bid/ask, real indicator values, real swing levels. It is never asked
   to recall or estimate a price.
2. Its output is constrained to a JSON schema (structured outputs).
3. Every price it returns is then re-validated against the live tick before
   the signal is persisted. Anything outside a sane band is rejected and
   downgraded to NO_TRADE — the model cannot smuggle an invented price
   through, because a number that didn't come from the snapshot won't
   survive `validate_against_market`.

The analyst has no access to the executor and no path to the broker. It
returns a proposal; the risk engine decides what happens to it.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from ..config import settings

log = logging.getLogger("analyst")

SYSTEM_PROMPT = """You are a disciplined intraday market analyst for XAUUSD (gold) on MetaTrader 5.

You will receive a JSON snapshot of real market data computed from actual broker \
price bars: the live bid/ask, and for each of the M1, M5, M15 and H1 timeframes \
the closes, EMA(20), EMA(50), RSI(14), ATR(14), detected trend, market structure, \
clustered support and resistance levels, breakout and pullback state, and \
liquidity zones.

Rules you must follow:

- Use ONLY numbers present in the snapshot. Never invent, estimate, round from \
memory, or recall a price, level, or indicator value. If a level you want is not \
in the snapshot, do not use it.
- Every price you output (entry, stop_loss, take_profit) must be at or very near a \
level that appears in the snapshot, or within the current bid/ask.
- Prefer the higher timeframes (H1, M15) for directional bias and the lower ones \
(M5, M1) for timing.
- If the timeframes disagree, the spread is wide, or structure is unclear, return \
action "NO_TRADE". A missed trade costs nothing; a bad one costs money. NO_TRADE is \
a good answer and you should use it often.
- stop_loss must sit beyond invalidating structure, not at an arbitrary distance.
- Set confidence honestly: 0-100, where above 80 means multi-timeframe confluence \
with a clean level to trade against.
- reason must be one short paragraph a trader can check against the snapshot.

You do not place trades. A separate risk-management layer decides whether \
anything you propose is executed, and it may reject or resize it."""

# Structured-output schema. `strict`-style: no additional properties.
ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "bias",
        "summary",
        "timeframes",
        "entry_zones",
        "signal",
        "warnings",
    ],
    "properties": {
        "bias": {"type": "string", "enum": ["BULLISH", "BEARISH", "NEUTRAL"]},
        "summary": {"type": "string"},
        "timeframes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "timeframe",
                    "trend",
                    "structure",
                    "support",
                    "resistance",
                    "breakout",
                    "pullback",
                    "liquidity",
                    "notes",
                ],
                "properties": {
                    "timeframe": {"type": "string", "enum": ["M1", "M5", "M15", "H1"]},
                    "trend": {"type": "string", "enum": ["UP", "DOWN", "RANGE"]},
                    "structure": {"type": "string"},
                    "support": {"type": "array", "items": {"type": "number"}},
                    "resistance": {"type": "array", "items": {"type": "number"}},
                    "breakout": {
                        "type": "string",
                        "enum": ["UP", "DOWN", "NONE"],
                    },
                    "pullback": {
                        "type": "string",
                        "enum": ["BULLISH", "BEARISH", "NONE"],
                    },
                    "liquidity": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["low", "high", "label"],
                            "properties": {
                                "low": {"type": "number"},
                                "high": {"type": "number"},
                                "label": {"type": "string"},
                            },
                        },
                    },
                    "notes": {"type": "string"},
                },
            },
        },
        "entry_zones": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["low", "high", "label"],
                "properties": {
                    "low": {"type": "number"},
                    "high": {"type": "number"},
                    "label": {"type": "string"},
                },
            },
        },
        "signal": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "action",
                "entry",
                "stop_loss",
                "take_profit",
                "confidence",
                "reason",
            ],
            "properties": {
                "action": {"type": "string", "enum": ["BUY", "SELL", "NO_TRADE"]},
                "entry": {"type": ["number", "null"]},
                "stop_loss": {"type": ["number", "null"]},
                "take_profit": {"type": ["number", "null"]},
                "confidence": {"type": "integer"},
                "reason": {"type": "string"},
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
}


def _no_trade(reason: str, warnings: list[str] | None = None) -> dict:
    return {
        "bias": "NEUTRAL",
        "summary": reason,
        "timeframes": [],
        "entry_zones": [],
        "signal": {
            "action": "NO_TRADE",
            "entry": None,
            "stop_loss": None,
            "take_profit": None,
            "confidence": 0,
            "reason": reason,
        },
        "warnings": warnings or [],
    }


def validate_against_market(result: dict, snapshot: dict) -> tuple[dict, list[str]]:
    """Re-check every model-produced price against real market data.

    Returns the (possibly downgraded) result and the list of violations.
    A violation always downgrades the signal to NO_TRADE — we never "fix up"
    a price the model got wrong, because a corrected price is still a price
    nobody decided to trade.
    """
    problems: list[str] = []
    sig = result.get("signal") or {}
    action = sig.get("action", "NO_TRADE")

    if action == "NO_TRADE":
        return result, problems

    bid = float(snapshot["bid"])
    ask = float(snapshot["ask"])
    mid = (bid + ask) / 2.0

    # Widest ATR across timeframes bounds how far a sane level can sit.
    atrs = [tf.get("atr14", 0.0) for tf in snapshot.get("timeframes", [])]
    max_atr = max(atrs) if atrs else 0.0
    # Entry must be within 3 ATR (or 1% of price if ATR is unusable).
    band = max(max_atr * 3.0, mid * 0.01)

    entry = sig.get("entry")
    sl = sig.get("stop_loss")
    tp = sig.get("take_profit")

    if entry is None or sl is None or tp is None:
        problems.append("actionable signal missing entry/stop_loss/take_profit")
    else:
        entry, sl, tp = float(entry), float(sl), float(tp)

        if abs(entry - mid) > band:
            problems.append(
                f"entry {entry} is {abs(entry - mid):.2f} from market {mid:.2f} "
                f"(max allowed {band:.2f}) — not a level from the snapshot"
            )
        if abs(sl - mid) > band * 2:
            problems.append(f"stop_loss {sl} implausibly far from market {mid:.2f}")
        if abs(tp - mid) > band * 4:
            problems.append(f"take_profit {tp} implausibly far from market {mid:.2f}")

        if action == "BUY":
            if sl >= entry:
                problems.append(f"BUY stop_loss {sl} must be below entry {entry}")
            if tp <= entry:
                problems.append(f"BUY take_profit {tp} must be above entry {entry}")
        elif action == "SELL":
            if sl <= entry:
                problems.append(f"SELL stop_loss {sl} must be above entry {entry}")
            if tp >= entry:
                problems.append(f"SELL take_profit {tp} must be below entry {entry}")

        if not problems:
            risk = abs(entry - sl)
            reward = abs(tp - entry)
            if risk <= 0:
                problems.append("zero-distance stop loss")
            else:
                sig["risk_reward"] = round(reward / risk, 2)

    conf = sig.get("confidence", 0)
    if not isinstance(conf, int) or not 0 <= conf <= 100:
        problems.append(f"confidence {conf!r} out of range")
        sig["confidence"] = 0

    if problems:
        log.warning("AI output rejected: %s", problems)
        result["signal"] = {
            "action": "NO_TRADE",
            "entry": None,
            "stop_loss": None,
            "take_profit": None,
            "confidence": 0,
            "reason": "Signal rejected by market-data validation: "
            + "; ".join(problems),
        }
        result.setdefault("warnings", []).extend(problems)

    return result, problems


async def analyze(snapshot: dict) -> tuple[dict, list[str]]:
    """Run the analyst. Returns (analysis, validation_problems).

    Never raises on model trouble — a trading system that crashes because the
    analyst hiccuped is worse than one that returns NO_TRADE.
    """
    if not settings.ANTHROPIC_API_KEY:
        return _no_trade("AI analyst not configured (ANTHROPIC_API_KEY unset)"), []

    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        return _no_trade("anthropic SDK not installed"), []

    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    user_content = (
        "Analyse this XAUUSD market snapshot. Every number below is real data "
        "measured from broker price bars just now.\n\n"
        f"```json\n{json.dumps(snapshot, indent=2)}\n```"
    )

    try:
        response = await client.messages.create(
            model=settings.ANALYST_MODEL,
            max_tokens=settings.ANALYST_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            output_config={
                "effort": settings.ANALYST_EFFORT,
                "format": {"type": "json_schema", "schema": ANALYSIS_SCHEMA},
            },
            messages=[{"role": "user", "content": user_content}],
        )
    except Exception as e:  # network, auth, rate limit, overload
        log.exception("analyst call failed")
        return _no_trade(f"AI analyst unavailable: {type(e).__name__}"), []

    # A refusal is a successful HTTP 200 with empty/partial content — check
    # stop_reason before touching response.content.
    if response.stop_reason == "refusal":
        detail = getattr(response, "stop_details", None)
        cat = getattr(detail, "category", None) if detail else None
        return _no_trade(f"AI analyst declined the request (category={cat})"), []

    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        return _no_trade("AI analyst returned no content"), []

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        log.error("analyst returned non-JSON despite schema: %s", text[:500])
        return _no_trade("AI analyst returned malformed output"), []

    result, problems = validate_against_market(result, snapshot)
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    result["symbol"] = snapshot["symbol"]
    result["model"] = settings.ANALYST_MODEL
    return result, problems
