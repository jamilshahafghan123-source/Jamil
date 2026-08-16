"""The analysis pipeline, end to end through GET /signal."""

from __future__ import annotations

import pytest

from tests import series
from tests.conftest import AUTH

GOLD = "XAUUSD"


@pytest.fixture
def signal_client(client_factory):
    return client_factory(RISK_ENABLED="true")


def load(mt5, rows, *, bid=None, ask=None):
    """Put a candle series behind XAUUSD, with quotes to match its last close."""
    mt5.state.rates[GOLD] = rows
    close = rows[-1]["close"]
    mt5.state.quotes[GOLD] = (bid or close - 0.15, ask or close + 0.15)


def get(client, **params):
    query = {"symbol": GOLD, **params}
    response = client.get("/api/v1/signal", params=query, headers=AUTH)
    assert response.status_code == 200, response.text
    return response.json()


def test_every_stage_reports_in_order(signal_client, mt5):
    load(mt5, series.uptrend())
    body = get(signal_client)

    assert list(body["stages"]) == ["trend", "support_resistance", "momentum", "volatility"]
    for stage in body["stages"].values():
        assert -1 <= stage["bias"] <= 1
        assert 0 <= stage["strength"] <= 1
        assert stage["note"]
    assert body["symbol"] == GOLD
    assert body["decision"] in {"trade", "no_trade"}


def test_trending_series_is_read_as_trending_with_realistic_indicators(signal_client, mt5):
    """Guards the fixture as much as the code: a series that only ever rises
    pins RSI at 100 and produces no pivots, quietly hollowing out the stages."""
    load(mt5, series.uptrend())
    stages = get(signal_client)["stages"]

    assert stages["trend"]["trending"] is True
    assert stages["trend"]["efficiency_ratio"] > 0.25
    assert 40 < stages["momentum"]["rsi"] < 95  # pullbacks, not a straight line
    # Both sides present, so the support/resistance stage has a real opinion.
    assert stages["support_resistance"]["support"] is not None
    assert stages["support_resistance"]["resistance"] is not None
    assert stages["support_resistance"]["strength"] > 0


def test_uptrend_produces_a_long_setup(signal_client, mt5):
    load(mt5, series.uptrend())
    body = get(signal_client)

    assert body["stages"]["trend"]["direction"] == "buy"
    setup = body["setup"]
    assert setup is not None
    assert setup["side"] == "buy"
    assert setup["stop_loss"] < setup["entry"] < setup["take_profit"]
    assert setup["reward_ratio"] > 0


def test_downtrend_produces_a_short_setup(signal_client, mt5):
    load(mt5, series.downtrend())
    body = get(signal_client)

    assert body["stages"]["trend"]["direction"] == "sell"
    setup = body["setup"]
    assert setup is not None
    assert setup["side"] == "sell"
    assert setup["take_profit"] < setup["entry"] < setup["stop_loss"]


def test_a_trade_decision_carries_a_sized_proposal(signal_client, mt5):
    load(mt5, series.uptrend())
    body = get(signal_client)

    if body["decision"] != "trade":
        pytest.skip(f"series did not clear the threshold: {body['reasons'][0]}")

    proposal = body["proposal"]
    assert proposal["symbol"] == GOLD
    assert proposal["volume"] > 0
    assert proposal["sl"] and proposal["tp"]
    assert body["risk"]["passed"] is True
    assert body["confidence"] >= body["min_confidence"]


def test_the_proposal_is_accepted_by_the_orders_endpoint(signal_client, mt5):
    """What the pipeline proposes must be something the risk policy accepts."""
    load(mt5, series.uptrend())
    body = get(signal_client)
    if body["decision"] != "trade":
        pytest.skip("no trade proposed for this series")

    response = signal_client.post("/api/v1/orders", json=body["proposal"], headers=AUTH)
    assert response.status_code == 201, response.text
    assert response.json()["risk"]["enabled"] is True


def test_choppy_market_yields_no_trade(signal_client, mt5):
    load(mt5, series.choppy())
    body = get(signal_client)

    assert body["decision"] == "no_trade"
    assert body["proposal"] is None
    assert body["reasons"]


def test_extreme_volatility_blocks_any_setup(signal_client, mt5):
    load(mt5, series.volatility_spike())
    body = get(signal_client)

    assert body["stages"]["volatility"]["regime"] == "extreme"
    assert body["stages"]["volatility"]["tradable"] is False
    assert body["decision"] == "no_trade"
    assert body["setup"] is None
    assert "wild" in body["reasons"][0]


def test_the_pipeline_never_sends_an_order(signal_client, mt5):
    load(mt5, series.uptrend())
    get(signal_client)
    assert mt5.state.sent_requests == []


def test_confidence_threshold_is_respected(client_factory, mt5):
    load(mt5, series.uptrend())
    strict = client_factory(RISK_ENABLED="true", SIGNAL_MIN_CONFIDENCE="99")
    body = get(strict)

    assert body["decision"] == "no_trade"
    assert body["proposal"] is None
    assert "below the 99.0 threshold" in body["reasons"][0]


def test_risk_manager_can_veto_a_confident_setup(signal_client, mt5):
    """Two open positions: the setup stands, the risk manager still says no."""
    load(mt5, series.uptrend())
    order = {
        "symbol": GOLD, "side": "buy", "volume": 0.10, "type": "market",
        "sl": round(mt5.state.quotes[GOLD][1] - 4, 2),
        "tp": round(mt5.state.quotes[GOLD][1] + 8, 2),
    }
    for _ in range(2):
        assert signal_client.post("/api/v1/orders", json=order, headers=AUTH).status_code == 201

    body = get(signal_client)
    if body["setup"] is None:
        pytest.skip("no setup to veto")

    assert body["decision"] == "no_trade"
    assert body["risk"]["passed"] is False
    assert body["risk"]["rule"] == "max_positions"
    # The proposal is still reported, so the desk can show what was blocked.
    assert body["proposal"] is not None


def test_short_history_is_rejected_clearly(signal_client, mt5):
    load(mt5, series.uptrend(bars=40))
    response = signal_client.get(
        "/api/v1/signal", params={"symbol": GOLD, "candles": 60}, headers=AUTH
    )
    assert response.status_code == 422
    assert "at least 60" in response.json()["message"]


def test_unknown_symbol_is_a_404(signal_client):
    response = signal_client.get(
        "/api/v1/signal", params={"symbol": "NOPE"}, headers=AUTH
    )
    assert response.status_code == 404
