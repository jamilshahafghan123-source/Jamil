"""Deterministic trade-setup engine.

This is where the BUY / SELL / NO_TRADE decision is actually made. Every
number it produces — entry zone, trigger, stop loss, the three targets, the
risk/reward, and the confidence score — is derived arithmetically from the
real bars in the snapshot built by `indicators.py`.

Why this is not the AI's job:

* A confidence score the model picks is a number with no provenance. Here it
  is a sum of named components a trader can audit line by line.
* Entry, stop and target must sit on real structure. Computing them from the
  detected swings and ATR means they cannot be anything else.
* The analysis still works when the AI is unavailable. `analyst.py` layers a
  plain-language explanation on top of this; it never replaces the numbers.

The engine proposes. It has no path to the broker: `risk_engine.evaluate`
still gates everything, and this module deliberately re-states the same
limits as *reasons* so the UI can explain a rejection before an order is
ever attempted.
"""

from __future__ import annotations

from typing import Any

# Confidence budget. The parts sum to 100 so the score is always explainable.
WEIGHTS = {
    "trend_alignment": 25,
    "structure": 20,
    "momentum": 15,
    "risk_reward": 15,
    "volume": 10,
    "levels": 10,
    "liquidity": 5,
}

# Timeframes used for entry timing, in order of preference.
SETUP_TFS = ("M15", "M5")


def _tf(snapshot: dict, name: str) -> dict | None:
    for t in snapshot.get("timeframes", []):
        if t.get("timeframe") == name:
            return t
    return None


def _first_tf(snapshot: dict, names: tuple[str, ...]) -> dict | None:
    for n in names:
        t = _tf(snapshot, n)
        if t:
            return t
    return None


def _no_trade(reason: str, reasons: list[str], warnings: list[str]) -> dict:
    return {
        "action": "NO_TRADE",
        "stage": "WATCH",
        "confidence": 0,
        "confidence_components": {},
        "entry_low": None,
        "entry_high": None,
        "trigger": None,
        "trigger_text": "",
        "stop_loss": None,
        "stop_loss_reason": "",
        "take_profit_1": None,
        "take_profit_2": None,
        "take_profit_3": None,
        "targets": [],
        "risk_reward": None,
        "invalidation": "",
        "next_target": None,
        "next_target_reason": "",
        "summary": reason,
        "reasons": reasons,
        "warnings": warnings,
        "blocking_reason": reason,
    }


def _direction(snapshot: dict) -> tuple[str, list[str], list[str]]:
    """Resolve direction under the timeframe hierarchy.

    The rule that matters: a lower timeframe may *time* an entry but may not
    reverse the major trend on its own. A setup-timeframe disagreement inside
    an aligned higher trend is a pullback — which is an opportunity in the
    trend's direction, not a signal against it.
    """
    h = snapshot.get("hierarchy") or {}
    major = (h.get("major") or {}).get("bias", "UNKNOWN")
    inter = (h.get("intermediate") or {}).get("bias", "UNKNOWN")
    setup = (h.get("setup") or {}).get("bias", "UNKNOWN")

    reasons: list[str] = []
    warnings: list[str] = []

    directional = ("BULLISH", "BEARISH")

    # Both higher groups agree -> that is the direction, full stop.
    if major in directional and major == inter:
        reasons.append(f"Major (D1/H4) and intermediate (H1/M30) trends are both {major.lower()}.")
        if setup in directional and setup != major:
            reasons.append(
                f"Setup timeframes (M15/M5) are {setup.lower()}, which inside an "
                f"aligned {major.lower()} trend reads as a pullback, not a reversal."
            )
        return major, reasons, warnings

    # Major is directional, intermediate merely ranging -> the major trend
    # still leads. A ranging H1 inside a trending D1/H4 is a pause, not a
    # contradiction, and refusing to trade it would ignore the hierarchy.
    if major in directional and inter not in directional:
        reasons.append(
            f"Major (D1/H4) trend is {major.lower()}; the intermediate (H1/M30) "
            f"picture is {inter.lower()}, read as a pause within the major trend."
        )
        warnings.append(
            "Intermediate timeframes are not confirming — expect slower follow-through."
        )
        return major, reasons, warnings

    # Major is unclear -> the intermediate trend leads, with less conviction.
    if major not in directional and inter in directional:
        reasons.append(
            f"Major structure is {major.lower()}; the intermediate (H1/M30) trend "
            f"is {inter.lower()} and leads with reduced conviction."
        )
        warnings.append("No confirmed higher-timeframe trend — position size accordingly.")
        return inter, reasons, warnings

    # Major and intermediate actively disagree -> stand aside.
    if major in directional and inter in directional and major != inter:
        warnings.append(
            f"Major trend is {major.lower()} but the intermediate trend is "
            f"{inter.lower()} — conflicting timeframes."
        )
        return "NONE", reasons, warnings

    warnings.append("No directional agreement across the timeframe hierarchy.")
    return "NONE", reasons, warnings


def _confidence(
    snapshot: dict, direction: str, setup_tf: dict, rr: float | None
) -> tuple[int, dict[str, int]]:
    """Transparent confidence. Each component is earned, never assumed."""
    h = snapshot.get("hierarchy") or {}
    tfs = snapshot.get("timeframes", [])
    want = "UP" if direction == "BUY" else "DOWN"
    comp: dict[str, int] = {}

    # --- trend alignment: share of timeframes pointing the right way
    if tfs:
        agree = sum(1 for t in tfs if t.get("trend") == want)
        comp["trend_alignment"] = round(WEIGHTS["trend_alignment"] * agree / len(tfs))
    else:
        comp["trend_alignment"] = 0
    if h.get("higher_aligned"):
        comp["trend_alignment"] = min(
            WEIGHTS["trend_alignment"], comp["trend_alignment"] + 4
        )

    # --- structure: pattern agreement, BOS adds, CHOCH against us subtracts
    pattern = (setup_tf.get("structure_detail") or {}).get("pattern", "UNCLEAR")
    bullish_pat = pattern == "HIGHER_HIGH_HIGHER_LOW"
    bearish_pat = pattern == "LOWER_HIGH_LOWER_LOW"
    score = 0
    if (direction == "BUY" and bullish_pat) or (direction == "SELL" and bearish_pat):
        score = WEIGHTS["structure"]
    elif pattern in ("RANGE", "CONSOLIDATION"):
        score = WEIGHTS["structure"] // 3
    if setup_tf.get("bos"):
        score = min(WEIGHTS["structure"], score + 3)
    if setup_tf.get("choch"):
        score = max(0, score - 8)
    comp["structure"] = score

    # --- momentum: MACD histogram sign plus RSI position
    mom = setup_tf.get("momentum", "NEUTRAL")
    rsi = float(setup_tf.get("rsi14") or 50.0)
    score = 0
    if (direction == "BUY" and mom == "RISING") or (direction == "SELL" and mom == "FALLING"):
        score = WEIGHTS["momentum"]
    elif mom == "NEUTRAL":
        score = WEIGHTS["momentum"] // 3
    # An exhausted oscillator is a reason for less confidence, not more.
    if direction == "BUY" and rsi > 78:
        score = max(0, score - 5)
    if direction == "SELL" and rsi < 22:
        score = max(0, score - 5)
    comp["momentum"] = score

    # --- risk/reward, scaled between 1.0R and 3.0R
    if rr is None:
        comp["risk_reward"] = 0
    else:
        scaled = (min(rr, 3.0) - 1.0) / 2.0
        comp["risk_reward"] = max(0, round(WEIGHTS["risk_reward"] * scaled))

    # --- volume confirmation (tick volume — an activity proxy, nothing more)
    vol = setup_tf.get("volume") or {}
    rel = float(vol.get("relative") or 0.0)
    if rel >= 1.5:
        comp["volume"] = WEIGHTS["volume"]
    elif rel >= 1.1:
        comp["volume"] = round(WEIGHTS["volume"] * 0.6)
    elif rel >= 0.8:
        comp["volume"] = round(WEIGHTS["volume"] * 0.3)
    else:
        comp["volume"] = 0

    # --- levels: is there a real level to trade against?
    levels = (
        setup_tf.get("support_levels") if direction == "BUY"
        else setup_tf.get("resistance_levels")
    ) or []
    if levels:
        best = levels[0].get("strength", "LOW")
        comp["levels"] = {
            "HIGH": WEIGHTS["levels"],
            "MEDIUM": round(WEIGHTS["levels"] * 0.6),
        }.get(best, round(WEIGHTS["levels"] * 0.3))
    else:
        comp["levels"] = 0

    # --- liquidity: a target pool in front of the trade
    comp["liquidity"] = WEIGHTS["liquidity"] if (setup_tf.get("liquidity") or []) else 0

    total = max(0, min(100, sum(comp.values())))
    return total, comp


def _targets(
    direction: str,
    entry: float,
    stop: float,
    setup_tf: dict,
    snapshot: dict,
    atr: float,
) -> list[dict]:
    """Three targets from real levels first, ATR projection only as filler."""
    risk = abs(entry - stop)
    sign = 1.0 if direction == "BUY" else -1.0

    pool: list[dict] = []
    key = "resistance_levels" if direction == "BUY" else "support_levels"
    for lv in setup_tf.get(key) or []:
        pool.append({"price": float(lv["price"]), "reason": lv.get("reason", "level")})
    # Session extremes are the levels every desk watches.
    for lv in snapshot.get("session_levels") or []:
        price = float(lv["price"])
        if (direction == "BUY" and price > entry) or (direction == "SELL" and price < entry):
            pool.append({"price": price, "reason": lv.get("reason", lv.get("label", ""))})
    # Liquidity pools sit just beyond swing extremes.
    for z in setup_tf.get("liquidity") or []:
        mid = (float(z["low"]) + float(z["high"])) / 2.0
        if (direction == "BUY" and mid > entry) or (direction == "SELL" and mid < entry):
            pool.append({"price": mid, "reason": f"potential liquidity zone ({z.get('label','')})"})

    # Keep only levels genuinely beyond the entry AND within a plausible
    # distance. A level from stale or mis-scaled higher-timeframe data can
    # otherwise produce a "target" hundreds of points away with an absurd R
    # multiple, so the band is enforced here rather than trusted.
    max_reach = max(atr * 10.0, entry * 0.02, risk * 8.0)
    ahead = [
        p for p in pool
        if risk * 0.4 < (p["price"] - entry) * sign <= max_reach
    ]
    ahead.sort(key=lambda p: abs(p["price"] - entry))

    targets: list[dict] = []
    for p in ahead:
        if len(targets) == 3:
            break
        # Don't stack two targets on top of each other.
        if targets and abs(p["price"] - targets[-1]["price"]) < risk * 0.4:
            continue
        targets.append({"price": round(p["price"], 2), "reason": p["reason"]})

    # Fill any gap with ATR projections, clearly labelled as such. Each filler
    # must extend *beyond* the previous target: a projection computed purely
    # from R can otherwise land nearer than a real level already taken, which
    # would leave TP2 closer than TP1.
    multiples = [1.5, 2.5, 3.5]
    step = max(risk * 0.75, atr * 0.75)
    while len(targets) < 3:
        m = multiples[len(targets)]
        price = entry + sign * max(risk * m, atr * m)
        if targets:
            floor_price = targets[-1]["price"] + sign * step
            price = max(price, floor_price) if sign > 0 else min(price, floor_price)
        targets.append({"price": round(price, 2), "reason": f"{m}R ATR projection"})

    # Safety net: targets must read outward from the entry in trade order.
    targets.sort(key=lambda t: (t["price"] - entry) * sign)
    for t in targets:
        reward = abs(t["price"] - entry)
        t["risk_reward"] = round(reward / risk, 2) if risk > 0 else 0.0
    return targets


def build_setup(snapshot: dict, risk_settings: Any | None = None) -> dict:
    """Produce the full structured setup for a snapshot.

    `risk_settings` is the user's RiskSettings row when available. It is read
    only to explain *why* a setup would be rejected — this function never
    relaxes a limit, and the risk engine still runs independently before any
    order is sent.
    """
    reasons: list[str] = []
    warnings: list[str] = []

    tfs = snapshot.get("timeframes") or []
    if not tfs:
        return _no_trade(
            "Market data unavailable — no timeframe could be analysed.", reasons, warnings
        )

    setup_tf = _first_tf(snapshot, SETUP_TFS) or tfs[0]
    bid = float(snapshot.get("bid") or 0.0)
    ask = float(snapshot.get("ask") or 0.0)
    price = (bid + ask) / 2.0 if bid and ask else float(setup_tf.get("last_close") or 0.0)
    atr = float(setup_tf.get("atr14") or 0.0)
    if price <= 0 or atr <= 0:
        return _no_trade(
            "Market data unavailable — no usable price or volatility reading.",
            reasons,
            warnings,
        )

    direction, dir_reasons, dir_warnings = _direction(snapshot)
    reasons.extend(dir_reasons)
    warnings.extend(dir_warnings)

    # ---- hard gates that make any setup pointless ------------------------
    spread = float(snapshot.get("spread_points") or 0.0)
    max_spread = getattr(risk_settings, "max_spread_points", None)
    if max_spread is not None and spread > float(max_spread):
        return _no_trade(
            f"Spread is {spread:.0f} points, above the configured maximum of {max_spread}.",
            reasons,
            warnings,
        )

    if direction == "NONE":
        return _no_trade(
            "Timeframes disagree — no high-quality setup. Waiting for the higher "
            "and intermediate trends to point the same way.",
            reasons,
            warnings,
        )

    action = "BUY" if direction == "BULLISH" else "SELL"
    ema_fast = float(setup_tf.get("ema_fast") or price)

    # Levels are re-filtered against the LIVE price, not the timeframe's last
    # close. The two are normally within a tick of each other, but when they
    # are not (stale bar, gap, slow feed) a "support" sitting above price
    # would otherwise produce an inverted stop.
    if action == "BUY":
        levels = [
            lv for lv in (setup_tf.get("support_levels") or [])
            if float(lv["price"]) < price
        ]
    else:
        levels = [
            lv for lv in (setup_tf.get("resistance_levels") or [])
            if float(lv["price"]) > price
        ]

    # ---- entry zone: near price, pulled toward the fast EMA, width-capped
    # at ~0.8 ATR so it stays an executable zone rather than a whole range.
    max_width = atr * 0.8
    if action == "BUY":
        anchor = min(ema_fast, price)
        low = max(anchor, price - max_width)
        high = price + atr * 0.10
    else:
        anchor = max(ema_fast, price)
        high = min(anchor, price + max_width)
        low = price - atr * 0.10

    entry_low, entry_high = round(min(low, high), 2), round(max(low, high), 2)
    if entry_high - entry_low < atr * 0.15:
        pad = (atr * 0.15 - (entry_high - entry_low)) / 2.0
        entry_low, entry_high = round(entry_low - pad, 2), round(entry_high + pad, 2)
    entry = round((entry_low + entry_high) / 2.0, 2)
    trigger = entry_high if action == "BUY" else entry_low

    # ---- stop loss: beyond invalidating structure, plus an ATR buffer
    # Stop placement: prefer real structure, but only structure that is
    # actually within reach. In a smooth trend the nearest swing can sit many
    # ATR away, and anchoring there would produce a stop no one would take —
    # so beyond that distance the stop becomes volatility-based and says so.
    buffer = atr * 0.5
    reach = atr * 4.0
    tf_name = setup_tf["timeframe"]

    if action == "BUY":
        candidates = [
            float(lv["price"]) for lv in levels
            if 0 <= entry_low - float(lv["price"]) <= reach
        ]
        rng = float(setup_tf.get("range_low") or 0.0)
        if 0.0 < rng < entry_low and entry_low - rng <= reach:
            candidates.append(rng)
        if candidates:
            struct = max(candidates)  # nearest level below the zone
            stop = round(struct - buffer, 2)
            stop_reason = (
                f"below the {tf_name} swing low at {round(struct, 2)} "
                f"plus a {round(buffer, 2)} ATR buffer"
            )
        else:
            stop = round(entry_low - atr * 1.5, 2)
            stop_reason = (
                f"1.5 ATR below the entry zone — no {tf_name} swing low within "
                f"{round(reach, 2)} of price"
            )
    else:
        candidates = [
            float(lv["price"]) for lv in levels
            if 0 <= float(lv["price"]) - entry_high <= reach
        ]
        rng = float(setup_tf.get("range_high") or 0.0)
        if rng > entry_high and rng - entry_high <= reach:
            candidates.append(rng)
        if candidates:
            struct = min(candidates)  # nearest level above the zone
            stop = round(struct + buffer, 2)
            stop_reason = (
                f"above the {tf_name} swing high at {round(struct, 2)} "
                f"plus a {round(buffer, 2)} ATR buffer"
            )
        else:
            stop = round(entry_high + atr * 1.5, 2)
            stop_reason = (
                f"1.5 ATR above the entry zone — no {tf_name} swing high within "
                f"{round(reach, 2)} of price"
            )

    # Hard invariant. If direction, zone and stop do not agree, the inputs are
    # degenerate — say so rather than emitting a setup that cannot be traded.
    if action == "BUY" and not (stop < entry_low <= entry_high):
        return _no_trade(
            "Structure and price disagree — no valid long stop below the entry zone.",
            reasons,
            warnings,
        )
    if action == "SELL" and not (stop > entry_high >= entry_low):
        return _no_trade(
            "Structure and price disagree — no valid short stop above the entry zone.",
            reasons,
            warnings,
        )

    risk_distance = abs(entry - stop)
    if risk_distance <= 0 or risk_distance > atr * 8.0:
        return _no_trade(
            "No valid stop-loss distance could be derived from current structure.",
            reasons,
            warnings,
        )

    targets = _targets(action, entry, stop, setup_tf, snapshot, atr)
    rr = targets[0]["risk_reward"] if targets else None

    confidence, components = _confidence(snapshot, action, setup_tf, rr)

    # ---- stage: how close is this to being actionable right now?
    if action == "BUY":
        in_zone = entry_low <= price <= entry_high
        triggered = price > trigger
    else:
        in_zone = entry_low <= price <= entry_high
        triggered = price < trigger

    if triggered and setup_tf.get("breakout_confirmed"):
        stage = "CONFIRMED_SETUP"
    elif in_zone or triggered:
        stage = "ENTRY_TRIGGER"
    else:
        stage = "WATCH"

    side_word = "below" if action == "BUY" else "above"
    invalidation = f"{tf_name} close {side_word} {stop} invalidates this setup."
    trigger_text = (
        f"{tf_name} close {'above' if action == 'BUY' else 'below'} {trigger}"
    )

    next_target = targets[0]["price"] if targets else None
    next_reason = targets[0]["reason"] if targets else ""

    # ---- evidence ---------------------------------------------------------
    struct_desc = (setup_tf.get("structure_detail") or {}).get("description", "")
    if struct_desc:
        reasons.append(f"{tf_name} structure: {struct_desc}")
    vol = setup_tf.get("volume") or {}
    if vol:
        reasons.append(
            f"Tick volume is {vol.get('state', 'UNKNOWN').lower()} at "
            f"{vol.get('relative', 0)}x the {tf_name} average and {vol.get('trend','steady').lower()}."
        )
    reasons.append(
        f"{tf_name} RSI {setup_tf.get('rsi14')}, ADX {setup_tf.get('adx14')} "
        f"({setup_tf.get('regime', 'UNKNOWN').lower()}), ATR {round(atr, 2)}."
    )
    if setup_tf.get("breakout") != "NONE":
        reasons.append(
            f"Breakout {setup_tf.get('breakout')} at {setup_tf.get('breakout_level')} — "
            + ("confirmed by volume and momentum." if setup_tf.get("breakout_confirmed")
               else "NOT confirmed; treat as provisional.")
        )
    if setup_tf.get("pullback") != "NONE":
        reasons.append(f"{setup_tf.get('pullback').title()} pullback into the fast EMA detected.")

    # ---- configured minimums, surfaced as reasons rather than silently applied
    blocking: str | None = None
    min_rr = getattr(risk_settings, "min_rr", None)
    if min_rr is not None and rr is not None and rr < float(min_rr):
        blocking = f"Risk/reward {rr} is below the configured minimum of {min_rr}."
    min_conf = getattr(risk_settings, "min_confidence", None)
    if blocking is None and min_conf is not None and confidence < int(min_conf):
        blocking = (
            f"Confidence {confidence} is below the configured minimum of {min_conf}."
        )

    if blocking:
        warnings.append(blocking)
        result = _no_trade(blocking, reasons, warnings)
        # Keep the analysis visible even though it is not tradeable — the
        # levels are still real and useful to watch.
        result.update(
            {
                "stage": "WATCH",
                "entry_low": entry_low,
                "entry_high": entry_high,
                "trigger": trigger,
                "trigger_text": trigger_text,
                "stop_loss": stop,
                "stop_loss_reason": stop_reason,
                "take_profit_1": targets[0]["price"] if len(targets) > 0 else None,
                "take_profit_2": targets[1]["price"] if len(targets) > 1 else None,
                "take_profit_3": targets[2]["price"] if len(targets) > 2 else None,
                "targets": targets,
                "risk_reward": rr,
                "invalidation": invalidation,
                "next_target": next_target,
                "next_target_reason": next_reason,
                "confidence": confidence,
                "confidence_components": components,
            }
        )
        return result

    return {
        "action": action,
        "stage": stage,
        "confidence": confidence,
        "confidence_components": components,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "trigger": trigger,
        "trigger_text": trigger_text,
        "stop_loss": stop,
        "stop_loss_reason": stop_reason,
        "take_profit_1": targets[0]["price"] if len(targets) > 0 else None,
        "take_profit_2": targets[1]["price"] if len(targets) > 1 else None,
        "take_profit_3": targets[2]["price"] if len(targets) > 2 else None,
        "targets": targets,
        "risk_reward": rr,
        "invalidation": invalidation,
        "next_target": next_target,
        "next_target_reason": next_reason,
        "summary": "",
        "reasons": reasons,
        "warnings": warnings,
        "blocking_reason": None,
    }
