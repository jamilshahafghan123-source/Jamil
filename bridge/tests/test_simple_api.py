"""The compact endpoint surface: /account, /market/{symbol}, /trade/*, etc."""

from __future__ import annotations

import pytest

from tests.conftest import AUTH

GOLD = "XAUUSD"


@pytest.fixture
def simple(client_factory):
    return client_factory(RISK_ENABLED="true")


def buy(**overrides):
    payload = {"symbol": GOLD, "volume": 0.10, "sl": 2397.80, "tp": 2410.00}
    payload.update(overrides)
    return payload


def test_health_needs_no_auth(client):
    assert client.get("/health").status_code == 200


def test_account_returns_the_live_account(simple):
    body = simple.get("/account", headers=AUTH).json()
    assert body["login"] == 5031234
    assert body["balance"] == 10_000.0
    assert body["is_demo"] is True


def test_market_snapshot_bundles_symbol_quote_and_candles(simple):
    body = simple.get(f"/market/{GOLD}", params={"count": 50}, headers=AUTH).json()

    assert body["symbol"] == GOLD
    assert body["digits"] == 2
    assert body["bid"] == 2401.50 and body["ask"] == 2401.80
    assert body["spread_points"] == pytest.approx(30.0)
    assert body["volume_step"] == 0.01
    assert len(body["candles"]) == 50
    assert set(body["candles"][0]) >= {"time", "open", "high", "low", "close"}


def test_market_snapshot_rejects_an_unknown_symbol(simple):
    assert simple.get("/market/NOPE", headers=AUTH).status_code == 404


def test_positions_and_orders_are_empty_to_begin_with(simple):
    assert simple.get("/positions", headers=AUTH).json() == []
    assert simple.get("/orders", headers=AUTH).json() == []


def test_trade_buy_opens_a_long(simple, mt5):
    body = simple.post("/trade/buy", json=buy(), headers=AUTH).json()
    assert body["success"] is True
    assert body["retcode"] == 10009

    sent = mt5.state.sent_requests[-1]
    assert sent["type"] == mt5.ORDER_TYPE_BUY
    assert sent["price"] == 2401.80  # buys fill at the ask

    positions = simple.get("/positions", headers=AUTH).json()
    assert len(positions) == 1 and positions[0]["side"] == "buy"


def test_trade_sell_opens_a_short(simple, mt5):
    body = simple.post(
        "/trade/sell", json=buy(sl=2405.80, tp=2393.00), headers=AUTH
    ).json()
    assert body["success"] is True

    sent = mt5.state.sent_requests[-1]
    assert sent["type"] == mt5.ORDER_TYPE_SELL
    assert sent["price"] == 2401.50  # sells fill at the bid


def test_position_close_takes_a_ticket_in_the_body(simple):
    simple.post("/trade/buy", json=buy(), headers=AUTH)
    ticket = simple.get("/positions", headers=AUTH).json()[0]["ticket"]

    body = simple.post("/position/close", json={"ticket": ticket}, headers=AUTH).json()
    assert body["success"] is True
    assert simple.get("/positions", headers=AUTH).json() == []


def test_partial_close_leaves_the_remainder(simple):
    simple.post("/trade/buy", json=buy(), headers=AUTH)
    ticket = simple.get("/positions", headers=AUTH).json()[0]["ticket"]

    simple.post("/position/close", json={"ticket": ticket, "volume": 0.04}, headers=AUTH)
    remaining = simple.get("/positions", headers=AUTH).json()
    assert len(remaining) == 1
    assert remaining[0]["volume"] == pytest.approx(0.06)


def test_the_compact_surface_obeys_the_same_risk_policy(simple, mt5):
    """No shortcut: /trade/buy is the same policy as POST /api/v1/orders."""
    response = simple.post("/trade/buy", json=buy(volume=0.25), headers=AUTH)
    assert response.status_code == 403
    assert response.json()["details"]["rule"] == "max_lot"
    assert mt5.state.sent_requests == []

    missing_stop = buy()
    missing_stop.pop("sl")
    assert simple.post("/trade/buy", json=missing_stop, headers=AUTH).status_code == 403


def test_the_compact_surface_needs_auth(simple):
    assert simple.get("/account").status_code == 401
    assert simple.post("/trade/buy", json=buy()).status_code == 401


def test_both_surfaces_report_the_same_positions(simple):
    simple.post("/trade/buy", json=buy(), headers=AUTH)
    compact = simple.get("/positions", headers=AUTH).json()
    versioned = simple.get("/api/v1/positions", headers=AUTH).json()
    assert compact == versioned
