"""AI market analyst.

Division of labour, enforced in code rather than requested politely:

* `indicators.py` measures the market from real bars.
* `setup_engine.py` decides BUY / SELL / NO_TRADE and computes every price —
  entry zone, trigger, stop, the three targets — and the confidence score
  from named, auditable components.
* This module asks the model for one thing only: a plain-language
  explanation of what the deterministic engine already decided.

The model's structured output contains **no numbers that reach a trade**. It
cannot invent a price, move a stop, or inflate a confidence score, because
those fields are not in its schema. Anything it does return still passes
through `validate_against_market` before persistence.

The analyst has no access to the executor and no path to the broker. It
returns a proposal; the risk engine decides what happens to it.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from ..config import settings
from .setup_engine import build_setup

log = logging.getLogger("analyst")

SYSTEM_PROMPT = """You are the market-commentary layer of a XAUUSD (gold) analysis dashboard on MetaTrader 5.

A deterministic engine has already measured the market from real broker bars and already decided the trade. You will receive both: the measured snapshot (bid/ask, per-timeframe EMA/RSI/MACD/ADX/ATR, market structure, ranked support and resistance, liquidity zones, tick volume) and the computed setup (action, entry zone, trigger, stop loss, three targets, risk/reward, confidence and its components).

Your only job is to explain that decision in clear language a trader can check.

Rules:

- Do NOT propose a different action, price, level, or confidence. The decision is already made. You are describing it, not revising it.
- Use ONLY numbers that appear in the input. Never estimate, round from memory, or recall a price.
- Write plainly. Two to four sentences for the explanation. Say what the market is doing, what would confirm the setup, and what would invalidate it. No jargon walls.
- Tick volume is a count of price changes, not traded contracts. Never call it institutional or exchange volume.
- Liquidity zones are inferred from equal highs/lows and session extremes. Call them "potential liquidity", never claim visibility into real order flow.
- If the action is NO_TRADE, explain what specifically is missing and what would have to happen before a trade becomes valid.

You do not place trades and cannot change the setup."""

# Structured-output schema. Deliberately text-only: there is no field here
# the model could use to alter a price, a level, or the confidence score.
NARRATIVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["headline", "explanation", "timeframe_notes"],
    "properties": {
        "headline": {
            "type": "string",
            "description": "One sentence stating what gold is doing right now.",
        },
        "explanation": {
            "type": "string",
            "description": (
                "Two to four plain sentences: the market read, what confirms the "
                "setup, and what invalidates it."
            ),
        },
        "timeframe_notes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["timeframe", "note"],
                "properties": {
                    "timeframe": {
                        "type": "string",
                        "enum": ["M1", "M5", "M15", "M30", "H1", "H4", "D1"],
                    },
                    "note": {"type": "string"},
                },
            },
        },
    },
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


def _deterministic_summary(setup: dict, snapshot: dict) -> str:
    """Readable summary built without the model, used as the fallback.

    The dashboard must stay useful when the AI is unconfigured or down, so
    the narrative degrades to this rather than to an empty panel.
    """
    h = snapshot.get("hierarchy") or {}
    major = (h.get("major") or {}).get("bias", "UNKNOWN").lower()
    inter = (h.get("intermediate") or {}).get("bias", "UNKNOWN").lower()
    action = setup.get("action", "NO_TRADE")

    if action == "NO_TRADE":
        return setup.get("blocking_reason") or setup.get("summary") or (
            "No high-quality setup right now."
        )

    side = "long" if action == "BUY" else "short"
    return (
        f"Gold is {major} on the higher timeframes and {inter} on the intermediate "
        f"ones. The engine reads a {side} setup with entry between "
        f"{setup['entry_low']} and {setup['entry_high']}, confirmed on a "
        f"{setup['trigger_text']}. Stop sits at {setup['stop_loss']} "
        f"({setup['stop_loss_reason']}), first target {setup['take_profit_1']} "
        f"at {setup['risk_reward']}R. {setup['invalidation']}"
    )


def _assemble(setup: dict, snapshot: dict, narrative: dict | None) -> dict:
    """Merge the deterministic setup and the optional narrative into one payload."""
    tfs = snapshot.get("timeframes", [])
    setup_tf = next(
        (t for t in tfs if t["timeframe"] in ("M15", "M5")), tfs[0] if tfs else {}
    )
    h = snapshot.get("hierarchy") or {}
    major_bias = (h.get("major") or {}).get("bias", "UNKNOWN")
    action = setup.get("action", "NO_TRADE")

    bias = (
        "BULLISH" if major_bias == "BULLISH"
        else "BEARISH" if major_bias == "BEARISH"
        else "NEUTRAL"
    )

    notes = {n["timeframe"]: n["note"] for n in (narrative or {}).get("timeframe_notes", [])}
    timeframes = [
        {
            "timeframe": t["timeframe"],
            "role": t.get("role", ""),
            "trend": t["trend"],
            "structure": (t.get("structure_detail") or {}).get("pattern", t.get("structure", "")),
            "structure_text": (t.get("structure_detail") or {}).get("description", ""),
            "regime": t.get("regime", "UNKNOWN"),
            "momentum": t.get("momentum", "NEUTRAL"),
            "rsi14": t.get("rsi14"),
            "adx14": t.get("adx14"),
            "atr14": t.get("atr14"),
            "ema20": t.get("ema_fast"),
            "ema50": t.get("ema_slow"),
            "ema200": t.get("ema200"),
            "macd_hist": t.get("macd_hist"),
            "bos": t.get("bos", False),
            "choch": t.get("choch", False),
            "breakout": t.get("breakout", "NONE"),
            "breakout_confirmed": t.get("breakout_confirmed", False),
            "pullback": t.get("pullback", "NONE"),
            "support": t.get("support", []),
            "resistance": t.get("resistance", []),
            "support_levels": t.get("support_levels", []),
            "resistance_levels": t.get("resistance_levels", []),
            "liquidity": t.get("liquidity", []),
            "volume": t.get("volume", {}),
            "notes": notes.get(t["timeframe"], ""),
        }
        for t in tfs
    ]

    liq = setup_tf.get("liquidity") or []
    price = setup_tf.get("last_close") or 0.0
    return {
        "symbol": snapshot.get("symbol", ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": settings.ANALYST_MODEL if narrative else "deterministic-engine",
        "bias": bias,
        "headline": (narrative or {}).get("headline", ""),
        "summary": (narrative or {}).get("explanation")
        or _deterministic_summary(setup, snapshot),
        "market": {
            "price": round(float(price), 2),
            "bid": snapshot.get("bid"),
            "ask": snapshot.get("ask"),
            "spread_points": snapshot.get("spread_points"),
            "trend": bias,
            "regime": setup_tf.get("regime", "UNKNOWN"),
            "momentum": setup_tf.get("momentum", "NEUTRAL"),
            "volatility": setup_tf.get("atr14", 0.0),
            "confluence_score": snapshot.get("confluence_score", 0.0),
        },
        "hierarchy": h,
        "structure": setup_tf.get("structure_detail", {}),
        "levels": {
            "support": setup_tf.get("support_levels", []),
            "resistance": setup_tf.get("resistance_levels", []),
            "session": snapshot.get("session_levels", []),
            "liquidity_above": [z for z in liq if (z["low"] + z["high"]) / 2 >= price],
            "liquidity_below": [z for z in liq if (z["low"] + z["high"]) / 2 < price],
        },
        "volume": setup_tf.get("volume", snapshot.get("volume", {})),
        "setup": setup,
        "timeframes": timeframes,
        # Legacy fields the existing dashboard and Signal model already read.
        "entry_zones": (
            [{"low": setup["entry_low"], "high": setup["entry_high"], "label": "AI entry zone"}]
            if setup.get("entry_low") is not None
            else []
        ),
        "signal": {
            "action": action,
            # Midpoint of the zone whenever one exists — including on
            # NO_TRADE, where it is the level to watch rather than to trade.
            "entry": (
                round((setup["entry_low"] + setup["entry_high"]) / 2, 2)
                if setup.get("entry_low") is not None
                and setup.get("entry_high") is not None
                else None
            ),
            "stop_loss": setup.get("stop_loss"),
            "take_profit": setup.get("take_profit_1"),
            "risk_reward": setup.get("risk_reward"),
            "confidence": setup.get("confidence", 0),
            "reason": (narrative or {}).get("explanation")
            or _deterministic_summary(setup, snapshot),
        },
        "reasons": setup.get("reasons", []),
        "warnings": setup.get("warnings", []),
    }


async def _narrate(setup: dict, snapshot: dict) -> dict | None:
    """Ask the model to explain the setup. Returns None if unavailable.

    Never raises: a commentary outage must not stop the analysis, because
    every number the trader needs was already computed without the model.
    """
    if not settings.ANTHROPIC_API_KEY:
        return None
    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        return None

    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    payload = {"measured_market": snapshot, "computed_setup": setup}
    user_content = (
        "Explain this XAUUSD analysis. Every number below was measured from real "
        "broker bars or computed by the deterministic engine just now. Do not "
        "change any of them.\n\n"
        f"```json\n{json.dumps(payload, indent=2, default=str)}\n```"
    )

    try:
        response = await client.messages.create(
            model=settings.ANALYST_MODEL,
            max_tokens=settings.ANALYST_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            output_config={
                "effort": settings.ANALYST_EFFORT,
                "format": {"type": "json_schema", "schema": NARRATIVE_SCHEMA},
            },
            messages=[{"role": "user", "content": user_content}],
        )
    except Exception as e:  # network, auth, rate limit, overload
        log.warning("analyst narration unavailable: %s", type(e).__name__)
        return None

    # A refusal is a successful HTTP 200 with empty/partial content — check
    # stop_reason before touching response.content.
    if response.stop_reason == "refusal":
        detail = getattr(response, "stop_details", None)
        log.warning(
            "analyst declined narration (category=%s)",
            getattr(detail, "category", None) if detail else None,
        )
        return None

    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.error("analyst returned non-JSON despite schema: %s", text[:300])
        return None


async def analyze(
    snapshot: dict, risk_settings: Any | None = None
) -> tuple[dict, list[str]]:
    """Run the full analysis. Returns (analysis, validation_problems).

    The deterministic engine decides everything. The model only narrates, and
    the result is validated against the live tick regardless — defence in
    depth, even though no model-produced number reaches the signal.
    """
    setup = build_setup(snapshot, risk_settings)
    narrative = await _narrate(setup, snapshot)
    result = _assemble(setup, snapshot, narrative)
    result, problems = validate_against_market(result, snapshot)
    return result, problems
