"""The strategy wired to live data, position sizing and the risk manager.

    E  risk manager rejects the proposal -> no order is sent
"""

from __future__ import annotations

import pytest

from tests import series
from tests.conftest import AUTH

GOLD = "XAUUSD"


@pytest.fixture
def signal_client(client_factory):
    return client_factory(RISK_ENABLED="true")


def load(mt5, rates):
    """Put a multi-timeframe fixture behind XAUUSD, with a matching quote."""
    mt5.state.rates[GOLD] = rates
    price = series.last_close(rates)
    mt5.state.quotes[GOLD] = (round(price - 0.15, 2), round(price + 0.15, 2))
    return price


def get(client, **params):
    response = client.get("/api/v1/signal", params={"symbol": GOLD, **params}, headers=AUTH)
    assert response.status_code == 200, response.text
    return response.json()


# --- the endpoint contract ----------------------------------------------------


def test_bullish_market_is_reported_as_a_buy(signal_client, mt5):
    load(mt5, series.xauusd_bullish())
    body = get(signal_client)

    assert body["direction"] == "BUY"
    assert body["decision"] == "trade"
    assert body["signal_score"] >= body["min_score"]
    assert body["timeframe_confirmation"]["aligned"] is True
    assert body["risk"]["passed"] is True


def test_bearish_market_is_reported_as_a_sell(signal_client, mt5):
    load(mt5, series.xauusd_bearish())
    body = get(signal_client)

    assert body["direction"] == "SELL"
    assert body["proposal"]["side"] == "sell"


def test_the_proposal_is_sized_from_the_risk_budget(signal_client, mt5):
    load(mt5, series.xauusd_bullish())
    body = get(signal_client)

    proposal = body["proposal"]
    assert proposal["symbol"] == GOLD
    assert proposal["volume"] > 0
    assert proposal["sl"] == body["stop_loss"]
    # An MT5 order carries one target; the configured one.
    assert proposal["tp"] == body["take_profit"][body["order_target"]]


def test_the_proposal_is_accepted_by_the_orders_endpoint(signal_client, mt5):
    """What the strategy proposes must be something the risk policy accepts."""
    load(mt5, series.xauusd_bullish())
    body = get(signal_client)

    response = signal_client.post("/api/v1/orders", json=body["proposal"], headers=AUTH)
    assert response.status_code == 201, response.text
    assert response.json()["risk"]["enabled"] is True


def test_conflicting_timeframes_report_no_trade(signal_client, mt5):
    load(mt5, series.xauusd_conflicting())
    body = get(signal_client)

    assert body["direction"] == "NO_TRADE"
    assert body["decision"] == "no_trade"
    assert body["proposal"] is None


def test_the_pipeline_never_sends_an_order(signal_client, mt5):
    load(mt5, series.xauusd_bullish())
    get(signal_client)
    assert mt5.state.sent_requests == []


def test_unknown_symbol_is_a_404(signal_client):
    assert signal_client.get(
        "/api/v1/signal", params={"symbol": "NOPE"}, headers=AUTH
    ).status_code == 404


# --- closed candles -----------------------------------------------------------


def test_the_forming_bar_is_excluded(signal_client, mt5):
    """Requirement: confirm on closed candles only.

    A violent bar is appended to every timeframe as the one still forming. If
    the engine read it, the verdict would flip; it must not.
    """
    rates = series.xauusd_bullish()
    load(mt5, rates)
    before = get(signal_client)
    assert before["direction"] == "BUY"

    crash_times = {}
    for timeframe, rows in rates.items():
        last = dict(rows[-1])
        crash = last["close"] - 60
        crash_times[timeframe] = last["time"] + 60
        rows.append(
            {**last, "time": crash_times[timeframe], "open": last["close"],
             "high": last["close"], "low": crash, "close": crash}
        )
    load(mt5, rates)

    after = get(signal_client)

    # A 60-dollar collapse on every timeframe would end any long. It does not,
    # because the bar it lives on has not closed.
    assert after["direction"] == "BUY", "the forming bar leaked into the decision"
    # The newest bar the engine used is the one before the crash, not the crash.
    from datetime import datetime, timezone

    newest_used = datetime.fromisoformat(after["as_of"].replace("Z", "+00:00"))
    crash_bar = datetime.fromtimestamp(crash_times[series.TF_M15], tz=timezone.utc)
    assert newest_used < crash_bar
    assert before["direction"] == after["direction"]


@pytest.mark.anyio
async def test_closed_candles_helper_drops_the_newest_bar(mt5):
    from app.analysis import signal as pipeline
    from app.config import get_settings
    from app.mt5.session import MT5Session

    rates = series.xauusd_bullish()
    mt5.state.rates[GOLD] = rates
    session = MT5Session(get_settings())
    await session.connect()
    try:
        closed = await pipeline.closed_candles(
            session, symbol=GOLD, timeframe="M5", count=50
        )
        injected = rates[series.TF_M5]
        assert closed.close[-1] == pytest.approx(injected[-2]["close"])
        assert closed.close[-1] != pytest.approx(injected[-1]["close"])
    finally:
        await session.shutdown()


# --- E: the risk manager has the final word -----------------------------------


def test_e_risk_manager_rejection_produces_no_order(signal_client, mt5):
    """A perfectly good setup, refused because the position limit is used."""
    price = load(mt5, series.xauusd_bullish())
    seed = {
        "symbol": GOLD, "side": "buy", "volume": 0.10, "type": "market",
        "sl": round(price - 4, 2), "tp": round(price + 8, 2),
    }
    for _ in range(2):
        assert signal_client.post("/api/v1/orders", json=seed, headers=AUTH).status_code == 201
    sent_before = len(mt5.state.sent_requests)

    body = get(signal_client)

    # The strategy still says BUY - it is the risk manager that says no.
    assert body["direction"] == "BUY"
    assert body["decision"] == "no_trade"
    assert body["risk"]["passed"] is False
    assert body["risk"]["rule"] == "max_positions"
    assert "Risk manager" in body["reasons"][0]
    # The proposal is still reported so the desk can show what was blocked.
    assert body["proposal"] is not None
    # Nothing left the bridge.
    assert len(mt5.state.sent_requests) == sent_before


def test_e_a_blocked_proposal_is_also_refused_by_the_orders_endpoint(signal_client, mt5):
    price = load(mt5, series.xauusd_bullish())
    seed = {
        "symbol": GOLD, "side": "buy", "volume": 0.10, "type": "market",
        "sl": round(price - 4, 2), "tp": round(price + 8, 2),
    }
    for _ in range(2):
        signal_client.post("/api/v1/orders", json=seed, headers=AUTH)

    body = get(signal_client)
    response = signal_client.post("/api/v1/orders", json=body["proposal"], headers=AUTH)

    assert response.status_code == 403
    assert response.json()["details"]["rule"] == "max_positions"


@pytest.fixture
def anyio_backend():
    return "asyncio"
