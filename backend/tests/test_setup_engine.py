"""Tests for the deterministic setup engine.

These pin the rules that make the analyst trustworthy: the timeframe
hierarchy, the geometric invariants of a tradeable setup, and the fact that
confidence is an auditable sum rather than an opinion.
"""

from app.services.setup_engine import WEIGHTS, build_setup


def _tf(name, trend, *, close=2500.0, atr=5.0, **over):
    """A minimal but complete timeframe block, shaped like indicators.py.

    Levels are deliberately asymmetric in the trend's favour — near support
    and distant resistance in an uptrend — because that is what a tradeable
    setup looks like. Equidistant levels give R:R below 1 and the engine is
    right to reject them.
    """
    near, far = 6.0, 26.0
    sup_dist, res_dist = (near, far) if trend == "UP" else (far, near)
    base = {
        "timeframe": name,
        "role": "",
        "bars_analyzed": 300,
        "last_close": close,
        "ema_fast": close - 1.0,
        "ema_slow": close - 2.0,
        "ema200": close - 5.0,
        "rsi14": 58.0 if trend == "UP" else 42.0,
        "atr14": atr,
        "adx14": 28.0,
        "trend": trend,
        "structure": "HH-HL" if trend == "UP" else "LH-LL",
        "regime": "TRENDING",
        "momentum": "RISING" if trend == "UP" else "FALLING",
        "macd_hist": 0.4 if trend == "UP" else -0.4,
        "support": [close - sup_dist],
        "resistance": [close + res_dist],
        "support_levels": [
            {"price": close - sup_dist, "strength": "HIGH", "touches": 3,
             "reason": "3 swing low rejections clustered here", "distance": sup_dist}
        ],
        "resistance_levels": [
            {"price": close + res_dist, "strength": "HIGH", "touches": 3,
             "reason": "3 swing high rejections clustered here", "distance": res_dist}
        ],
        "structure_detail": {
            "pattern": "HIGHER_HIGH_HIGHER_LOW" if trend == "UP" else "LOWER_HIGH_LOWER_LOW",
            "bos": False, "choch": False, "description": "structure",
        },
        "bos": False,
        "choch": False,
        "breakout": "NONE",
        "breakout_confirmed": False,
        "breakout_level": 0.0,
        "pullback": "NONE",
        "liquidity": [
            {"low": close + res_dist + 2.0, "high": close + res_dist + 3.0,
             "label": "equal_highs"},
            {"low": close - sup_dist - 3.0, "high": close - sup_dist - 2.0,
             "label": "equal_lows"},
        ],
        "volume": {"type": "TICK_VOLUME", "current": 900.0, "average": 600.0,
                   "relative": 1.5, "trend": "EXPANDING", "state": "HIGH"},
        "range_high": close + res_dist,
        "range_low": close - sup_dist,
    }
    base.update(over)
    return base


def _snapshot(trends: dict, close=2500.0, spread=20.0):
    tfs = [_tf(name, trend, close=close) for name, trend in trends.items()]

    def group(names):
        present = [t for t in tfs if t["timeframe"] in names]
        ups = sum(1 for t in present if t["trend"] == "UP")
        downs = sum(1 for t in present if t["trend"] == "DOWN")
        bias = ("BULLISH" if ups > downs else "BEARISH" if downs > ups
                else "RANGE" if present else "UNKNOWN")
        return {"bias": bias, "timeframes": [t["timeframe"] for t in present],
                "agree": bool(present) and (ups == 0 or downs == 0)}

    major, inter = group(("D1", "H4")), group(("H1", "M30"))
    return {
        "symbol": "XAUUSD",
        "bid": close - 0.1, "ask": close + 0.1, "spread_points": spread,
        "timeframes": tfs,
        "session_levels": [],
        "confluence_score": 0.0,
        "hierarchy": {
            "major": major, "intermediate": inter,
            "setup": group(("M15", "M5")), "refinement": group(("M1",)),
            "higher_aligned": (major["bias"] == inter["bias"]
                               and major["bias"] in ("BULLISH", "BEARISH")),
        },
    }


class Risk:
    min_rr = 1.5
    min_confidence = 50
    max_spread_points = 50


# --------------------------------------------------------- hierarchy rules


def test_full_bullish_alignment_produces_a_buy():
    snap = _snapshot({"D1": "UP", "H4": "UP", "H1": "UP", "M30": "UP",
                      "M15": "UP", "M5": "UP", "M1": "UP"})
    setup = build_setup(snap, Risk())
    assert setup["action"] == "BUY"
    assert setup["confidence"] > 0


def test_lower_timeframe_pullback_does_not_flip_an_aligned_uptrend():
    """The rule the spec calls out: M15 turning down inside a bullish D1/H4/H1
    is a pullback, not a sell signal."""
    snap = _snapshot({"D1": "UP", "H4": "UP", "H1": "UP", "M30": "UP",
                      "M15": "DOWN", "M5": "DOWN", "M1": "DOWN"})
    setup = build_setup(snap, Risk())
    assert setup["action"] != "SELL"
    joined = " ".join(setup["reasons"]).lower()
    assert "pullback" in joined


def test_conflicting_major_and_intermediate_is_no_trade():
    snap = _snapshot({"D1": "UP", "H4": "UP", "H1": "DOWN", "M30": "DOWN",
                      "M15": "DOWN", "M5": "DOWN", "M1": "DOWN"})
    setup = build_setup(snap, Risk())
    assert setup["action"] == "NO_TRADE"
    assert "disagree" in (setup["blocking_reason"] or "").lower()


def test_major_leads_when_intermediate_is_ranging():
    snap = _snapshot({"D1": "UP", "H4": "UP", "H1": "RANGE", "M30": "RANGE",
                      "M15": "UP", "M5": "UP", "M1": "UP"})
    setup = build_setup(snap, Risk())
    assert setup["action"] == "BUY"
    assert any("pause" in w.lower() or "not confirming" in w.lower()
               for w in setup["warnings"])


# ------------------------------------------------------------- invariants


def test_buy_stop_sits_below_the_entry_zone_and_targets_above():
    snap = _snapshot({"D1": "UP", "H4": "UP", "H1": "UP", "M30": "UP",
                      "M15": "UP", "M5": "UP", "M1": "UP"})
    s = build_setup(snap, Risk())
    assert s["action"] == "BUY"
    assert s["stop_loss"] < s["entry_low"] <= s["entry_high"]
    for t in s["targets"]:
        assert t["price"] > s["entry_high"]
        assert t["risk_reward"] > 0


def test_sell_stop_sits_above_the_entry_zone_and_targets_below():
    snap = _snapshot({"D1": "DOWN", "H4": "DOWN", "H1": "DOWN", "M30": "DOWN",
                      "M15": "DOWN", "M5": "DOWN", "M1": "DOWN"})
    s = build_setup(snap, Risk())
    assert s["action"] == "SELL"
    assert s["stop_loss"] > s["entry_high"] >= s["entry_low"]
    for t in s["targets"]:
        assert t["price"] < s["entry_low"]


def test_three_targets_are_ordered_away_from_entry():
    snap = _snapshot({"D1": "UP", "H4": "UP", "H1": "UP", "M30": "UP",
                      "M15": "UP", "M5": "UP", "M1": "UP"})
    s = build_setup(snap, Risk())
    prices = [t["price"] for t in s["targets"]]
    assert len(prices) == 3
    assert prices == sorted(prices)
    rrs = [t["risk_reward"] for t in s["targets"]]
    assert rrs == sorted(rrs)


# ------------------------------------------------------------- confidence


def test_confidence_is_the_sum_of_its_published_components():
    snap = _snapshot({"D1": "UP", "H4": "UP", "H1": "UP", "M30": "UP",
                      "M15": "UP", "M5": "UP", "M1": "UP"})
    s = build_setup(snap, Risk())
    assert s["confidence"] == sum(s["confidence_components"].values())
    assert set(s["confidence_components"]) <= set(WEIGHTS)
    for name, value in s["confidence_components"].items():
        assert 0 <= value <= WEIGHTS[name]


def test_confidence_never_exceeds_one_hundred():
    snap = _snapshot({"D1": "UP", "H4": "UP", "H1": "UP", "M30": "UP",
                      "M15": "UP", "M5": "UP", "M1": "UP"})
    s = build_setup(snap, Risk())
    assert 0 <= s["confidence"] <= 100


# ------------------------------------------------------------------ gates


def test_no_market_data_is_no_trade_and_never_a_setup():
    s = build_setup({"symbol": "XAUUSD", "timeframes": []}, Risk())
    assert s["action"] == "NO_TRADE"
    assert "unavailable" in s["blocking_reason"].lower()
    assert s["entry_low"] is None and s["stop_loss"] is None


def test_wide_spread_blocks_the_setup():
    snap = _snapshot({"D1": "UP", "H4": "UP", "H1": "UP", "M30": "UP",
                      "M15": "UP", "M5": "UP", "M1": "UP"}, spread=500.0)
    s = build_setup(snap, Risk())
    assert s["action"] == "NO_TRADE"
    assert "spread" in s["blocking_reason"].lower()


def test_confidence_below_the_configured_minimum_blocks_but_keeps_the_levels():
    snap = _snapshot({"D1": "UP", "H4": "UP", "H1": "UP", "M30": "UP",
                      "M15": "UP", "M5": "UP", "M1": "UP"})
    scored = build_setup(snap, Risk())["confidence"]

    # Demand one point more than this setup can earn, whatever it scored.
    class Strict(Risk):
        min_confidence = scored + 1

    s = build_setup(snap, Strict())
    assert s["action"] == "NO_TRADE"
    assert "confidence" in s["blocking_reason"].lower()
    # The analysis is still useful to watch even when it is not tradeable.
    assert s["entry_low"] is not None and s["stop_loss"] is not None


def test_risk_reward_below_minimum_blocks():
    class Strict(Risk):
        min_rr = 99.0

    snap = _snapshot({"D1": "UP", "H4": "UP", "H1": "UP", "M30": "UP",
                      "M15": "UP", "M5": "UP", "M1": "UP"})
    s = build_setup(snap, Strict())
    assert s["action"] == "NO_TRADE"
    assert "risk/reward" in s["blocking_reason"].lower()
