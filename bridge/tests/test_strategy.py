"""The XAUUSD multi-timeframe strategy engine.

Scenario coverage the engine has to earn:

    A  bullish XAUUSD market      -> BUY
    B  bearish XAUUSD market      -> SELL
    C  conflicting timeframes     -> NO_TRADE
    D  insufficient data          -> NO_TRADE
"""

from __future__ import annotations

import pytest

from app.analysis import strategy
from app.analysis.strategy import Candles
from app.config import Settings
from tests import series

SYMBOL = "XAUUSD"
REQUIRED_FIELDS = {
    "symbol",
    "direction",
    "signal_score",
    "entry",
    "stop_loss",
    "take_profit",
    "risk_reward",
    "trend",
    "reasons",
    "timeframe_confirmation",
    "timestamp",
}


@pytest.fixture
def settings():
    return Settings(api_keys="test")


def run(rates, settings, *, price=None, digits=2):
    """Evaluate the engine against a multi-timeframe fixture."""
    current = price if price is not None else series.last_close(rates)
    return strategy.evaluate(
        symbol=SYMBOL,
        trend_candles=Candles.from_rows("M15", rates[series.TF_M15]),
        structure_candles=Candles.from_rows("M5", rates[series.TF_M5]),
        trigger_candles=Candles.from_rows("M1", rates[series.TF_M1]),
        bid=current - 0.15,
        ask=current + 0.15,
        digits=digits,
        settings=settings,
    )


# --- A: bullish market --------------------------------------------------------


def test_a_bullish_market_produces_a_buy(settings):
    signal = run(series.xauusd_bullish(), settings)

    assert signal["direction"] == "BUY"
    assert signal["signal_score"] >= settings.strategy_min_score
    assert signal["trend"]["primary"] == "bullish"
    assert signal["timeframe_confirmation"]["aligned"] is True
    # A long must be structured as a long.
    assert signal["stop_loss"] < signal["entry"]
    assert (
        signal["entry"]
        < signal["take_profit"]["tp1"]
        < signal["take_profit"]["tp2"]
        < signal["take_profit"]["tp3"]
    )


def test_a_buy_confirms_on_all_three_timeframes(settings):
    roles = run(series.xauusd_bullish(), settings)["timeframe_confirmation"]["roles"]

    assert set(roles) == {"trend", "structure", "trigger"}
    assert roles["trend"]["timeframe"] == "M15"
    assert roles["structure"]["timeframe"] == "M5"
    assert roles["trigger"]["timeframe"] == "M1"
    assert all(role["bias"] == "bullish" for role in roles.values())


# --- B: bearish market --------------------------------------------------------


def test_b_bearish_market_produces_a_sell(settings):
    signal = run(series.xauusd_bearish(), settings)

    assert signal["direction"] == "SELL"
    assert signal["signal_score"] >= settings.strategy_min_score
    assert signal["trend"]["primary"] == "bearish"
    assert signal["timeframe_confirmation"]["aligned"] is True
    assert signal["stop_loss"] > signal["entry"]
    assert (
        signal["entry"]
        > signal["take_profit"]["tp1"]
        > signal["take_profit"]["tp2"]
        > signal["take_profit"]["tp3"]
    )


# --- C: conflicting timeframes ------------------------------------------------


def test_c_conflicting_timeframes_produce_no_trade(settings):
    signal = run(series.xauusd_conflicting(), settings)

    assert signal["direction"] == "NO_TRADE"
    assert signal["entry"] is None and signal["stop_loss"] is None
    assert "disagree" in signal["reasons"][0]
    assert signal["timeframe_confirmation"]["aligned"] is False


def test_c_a_lone_trigger_is_not_a_signal(settings):
    """Requirement: never trade because one indicator crossed.

    The M1 trigger fires on the bullish series, but with a directionless M15 the
    engine must not reach it at all.
    """
    rates = series.xauusd_bullish()
    rates[series.TF_M15] = series.choppy(bars=300)
    signal = run(rates, settings)

    assert signal["direction"] == "NO_TRADE"
    assert "ranging" in signal["reasons"][0] or "not stacked" in signal["reasons"][0]


# --- D: insufficient data -----------------------------------------------------


def test_d_insufficient_history_produces_no_trade(settings):
    signal = run(series.xauusd_thin(), settings)

    assert signal["direction"] == "NO_TRADE"
    assert "Insufficient closed M15 data" in signal["reasons"][0]
    assert signal["signal_score"] == 0.0


@pytest.mark.parametrize("timeframe", [series.TF_M5, series.TF_M1])
def test_d_thin_lower_timeframes_also_produce_no_trade(settings, timeframe):
    rates = series.xauusd_bullish()
    rates[timeframe] = rates[timeframe][-20:]
    signal = run(rates, settings)

    assert signal["direction"] == "NO_TRADE"
    assert "Insufficient closed" in signal["reasons"][0]


# --- the signal contract ------------------------------------------------------


@pytest.mark.parametrize(
    "fixture", ["xauusd_bullish", "xauusd_bearish", "xauusd_conflicting", "xauusd_thin"]
)
def test_every_verdict_carries_every_required_field(settings, fixture):
    signal = run(getattr(series, fixture)(), settings)

    assert REQUIRED_FIELDS <= set(signal)
    assert signal["symbol"] == SYMBOL
    assert signal["direction"] in {"BUY", "SELL", "NO_TRADE"}
    assert set(signal["take_profit"]) == {"tp1", "tp2", "tp3"}
    assert set(signal["risk_reward"]) == {"tp1", "tp2", "tp3"}
    assert signal["reasons"], "a verdict must always explain itself"
    assert signal["timestamp"].tzinfo is not None


def test_direction_is_only_ever_one_of_three_values(settings):
    for fixture in ("xauusd_bullish", "xauusd_bearish", "xauusd_conflicting"):
        assert run(getattr(series, fixture)(), settings)["direction"] in {
            "BUY",
            "SELL",
            "NO_TRADE",
        }


# --- prices, stops and targets ------------------------------------------------


def test_entry_is_the_live_quote_not_a_candle_close(settings):
    """Requirement: do not fabricate prices."""
    rates = series.xauusd_bullish()
    price = series.last_close(rates)
    signal = run(rates, settings, price=price)

    # A buy fills at the ask, exactly as quoted.
    assert signal["entry"] == pytest.approx(price + 0.15, abs=0.005)
    assert signal["entry"] != rates[series.TF_M1][-1]["close"]


def test_stop_sits_beyond_the_last_swing_low_with_atr_headroom(settings):
    rates = series.xauusd_bullish()
    signal = run(rates, settings)
    structure = Candles.from_rows("M5", rates[series.TF_M5])

    lows = [price for _, price in strategy._swings(structure)[1] if price < signal["entry"]]
    assert signal["stop_loss"] < max(lows), "the stop must clear the swing it depends on"

    atr = signal["timeframe_confirmation"]["roles"]["trend"]["atr"]
    distance_atr = (signal["entry"] - signal["stop_loss"]) / atr
    assert settings.strategy_sl_min_atr <= distance_atr <= settings.strategy_sl_max_atr


def test_stop_distance_is_clamped_for_a_far_away_swing(settings):
    """A very distant structure level must not produce an unusable stop."""
    tight = Settings(api_keys="test", strategy_sl_max_atr=1.2)
    signal = run(series.xauusd_bullish(), tight)

    atr = signal["timeframe_confirmation"]["roles"]["trend"]["atr"]
    assert (signal["entry"] - signal["stop_loss"]) / atr <= 1.2 + 1e-9


def test_targets_follow_the_configured_risk_multiples(settings):
    custom = Settings(
        api_keys="test", strategy_tp1_r=0.5, strategy_tp2_r=1.5, strategy_tp3_r=4.0
    )
    signal = run(series.xauusd_bullish(), custom)

    risk = signal["entry"] - signal["stop_loss"]
    assert signal["take_profit"]["tp1"] == pytest.approx(signal["entry"] + risk * 0.5, abs=0.01)
    assert signal["take_profit"]["tp2"] == pytest.approx(signal["entry"] + risk * 1.5, abs=0.01)
    assert signal["take_profit"]["tp3"] == pytest.approx(signal["entry"] + risk * 4.0, abs=0.01)
    assert signal["risk_reward"] == {"tp1": 0.5, "tp2": 1.5, "tp3": 4.0}


def test_score_below_the_threshold_is_no_trade(settings):
    strict = Settings(api_keys="test", strategy_min_score=99)
    signal = run(series.xauusd_bullish(), strict)

    assert signal["direction"] == "NO_TRADE"
    assert "below the 99.0 threshold" in signal["reasons"][0]
    # The score is still reported, so the near-miss is visible.
    assert signal["signal_score"] > 0


def test_overextended_momentum_stands_the_engine_down(settings):
    """RSI already stretched is a poor place to join, however good the trend."""
    lenient = Settings(api_keys="test", strategy_rsi_overbought=55)
    signal = run(series.xauusd_bullish(), lenient)

    assert signal["direction"] == "NO_TRADE"
    assert any("over-extended" in reason for reason in signal["reasons"])


# --- indicator plumbing -------------------------------------------------------


def test_swings_are_counted_once_each():
    """A rounded top prints several pivots; comparing one against itself is not structure."""
    points = [(10, 100.0), (11, 100.2), (12, 100.1), (30, 105.0)]
    merged = indicators_distinct(points, keep="high")

    assert merged == [(11, 100.2), (30, 105.0)]


def indicators_distinct(points, keep):
    from app.analysis import indicators

    return indicators.distinct_swings(points, min_separation=5, keep=keep)


def test_reasons_name_the_timeframe_that_stopped_the_signal(settings):
    signal = run(series.xauusd_conflicting(), settings)
    assert "M15" in signal["reasons"][0] and "M5" in signal["reasons"][0]
