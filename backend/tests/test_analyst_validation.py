"""Tests for the no-invented-data guarantee and the indicator engine.

The point of `validate_against_market` is that a price the model made up
cannot reach the risk engine. These tests are what make that a property of
the system rather than a claim in a prompt.
"""

import math

from app.services.analyst import validate_against_market
from app.services.indicators import analyze_timeframe, build_snapshot, cluster, ema, rsi

SNAPSHOT = {
    "symbol": "XAUUSD",
    "bid": 2500.00,
    "ask": 2500.30,
    "spread_points": 30.0,
    "timeframes": [
        {"timeframe": "M15", "atr14": 5.0},
        {"timeframe": "H1", "atr14": 8.0},
    ],
}


def signal(**over):
    base = {
        "action": "BUY",
        "entry": 2500.0,
        "stop_loss": 2490.0,
        "take_profit": 2520.0,
        "confidence": 80,
        "reason": "test",
    }
    base.update(over)
    return {"signal": base, "warnings": []}


def test_valid_signal_passes_and_gets_rr():
    result, problems = validate_against_market(signal(), SNAPSHOT)
    assert problems == []
    assert result["signal"]["action"] == "BUY"
    assert result["signal"]["risk_reward"] == 2.0


def test_invented_entry_far_from_market_is_rejected():
    """The core guarantee: a hallucinated price cannot get through."""
    # Band = max(3 * 8.0 ATR, 1% of 2500) = 25.0
    result, problems = validate_against_market(signal(entry=1850.0), SNAPSHOT)
    assert problems
    assert result["signal"]["action"] == "NO_TRADE"
    assert "not a level from the snapshot" in problems[0]


def test_buy_with_stop_above_entry_rejected():
    result, problems = validate_against_market(
        signal(stop_loss=2510.0), SNAPSHOT
    )
    assert result["signal"]["action"] == "NO_TRADE"
    assert any("stop_loss" in p for p in problems)


def test_sell_direction_enforced():
    ok, problems = validate_against_market(
        signal(action="SELL", entry=2500.0, stop_loss=2510.0, take_profit=2480.0),
        SNAPSHOT,
    )
    assert problems == []
    assert ok["signal"]["risk_reward"] == 2.0

    bad, problems = validate_against_market(
        signal(action="SELL", entry=2500.0, stop_loss=2490.0, take_profit=2520.0),
        SNAPSHOT,
    )
    assert bad["signal"]["action"] == "NO_TRADE"
    assert problems


def test_actionable_signal_missing_levels_is_rejected():
    result, problems = validate_against_market(signal(stop_loss=None), SNAPSHOT)
    assert result["signal"]["action"] == "NO_TRADE"
    assert "missing entry/stop_loss/take_profit" in problems[0]


def test_no_trade_passes_through_untouched():
    result, problems = validate_against_market(
        signal(action="NO_TRADE", entry=None, stop_loss=None, take_profit=None),
        SNAPSHOT,
    )
    assert problems == []
    assert result["signal"]["action"] == "NO_TRADE"


def test_out_of_range_confidence_is_zeroed():
    result, problems = validate_against_market(signal(confidence=250), SNAPSHOT)
    assert result["signal"]["confidence"] == 0
    assert problems


# ---------------------------------------------------------- indicators


def make_bars(n=120, start=2400.0, step=1.0):
    """A clean uptrend: every bar closes above the last."""
    bars = []
    price = start
    for i in range(n):
        o = price
        c = price + step
        bars.append(
            {
                "time": f"2026-01-01T{i // 60:02d}:{i % 60:02d}:00+00:00",
                "open": o,
                "high": max(o, c) + 0.5,
                "low": min(o, c) - 0.5,
                "close": c,
                "tick_volume": 100,
                "spread": 30,
            }
        )
        price = c
    return bars


def test_ema_tracks_a_constant_series():
    import numpy as np

    values = np.array([100.0] * 50)
    assert ema(values, 20)[-1] == 100.0


def test_rsi_is_100_on_a_pure_uptrend():
    import numpy as np

    closes = np.array([100.0 + i for i in range(60)])
    assert rsi(closes, 14) == 100.0


def test_rsi_neutral_on_insufficient_data():
    import numpy as np

    assert rsi(np.array([100.0, 101.0]), 14) == 50.0


def test_cluster_merges_nearby_levels():
    merged = cluster([2500.0, 2500.4, 2500.2, 2530.0], tolerance=1.0)
    # The three near 2500 collapse into one, strongest (most touches) first.
    assert merged[0] == 2500.2
    assert 2530.0 in merged


def test_analyze_timeframe_detects_an_uptrend():
    res = analyze_timeframe("M15", make_bars())
    assert res is not None
    assert res.trend == "UP"
    assert res.rsi14 > 70
    assert res.atr14 > 0
    assert res.last_close == 2520.0


def test_analyze_timeframe_needs_enough_bars():
    assert analyze_timeframe("M15", make_bars(10)) is None


def test_build_snapshot_shape_and_confluence():
    tick = {
        "symbol": "XAUUSD",
        "bid": 2519.9,
        "ask": 2520.1,
        "spread_points": 20.0,
        "time": "2026-01-01T00:00:00+00:00",
    }
    snap = build_snapshot(
        "XAUUSD", tick, {tf: make_bars() for tf in ("M1", "M5", "M15", "H1")}
    )
    assert snap["symbol"] == "XAUUSD"
    assert snap["bid"] == 2519.9
    assert len(snap["timeframes"]) == 4
    # All four timeframes trending up -> confluence pinned at +1.
    assert math.isclose(snap["confluence_score"], 1.0)


def test_snapshot_contains_only_real_numbers():
    """Everything the AI sees must be finite and derived from the bars."""
    tick = {
        "symbol": "XAUUSD",
        "bid": 2519.9,
        "ask": 2520.1,
        "spread_points": 20.0,
        "time": "2026-01-01T00:00:00+00:00",
    }
    snap = build_snapshot("XAUUSD", tick, {"M15": make_bars()})
    for tf in snap["timeframes"]:
        for key in ("last_close", "ema_fast", "ema_slow", "rsi14", "atr14"):
            assert math.isfinite(tf[key]), f"{key} is not finite"
        for lvl in tf["support"] + tf["resistance"]:
            assert math.isfinite(lvl)
