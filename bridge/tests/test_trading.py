from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from tests.conftest import AUTH


def _open_position(client, **overrides):
    payload = {"symbol": "EURUSD", "side": "buy", "volume": 0.10}
    payload.update(overrides)
    return client.post("/api/v1/orders", json=payload, headers=AUTH)


def test_market_buy_opens_a_position(client, mt5):
    response = _open_position(client, sl=1.0800, tp=1.0900, comment="entry")
    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["retcode"] == 10009
    assert body["retcode_description"] == "Request completed"

    sent = mt5.state.sent_requests[-1]
    assert sent["action"] == mt5.TRADE_ACTION_DEAL
    assert sent["type"] == mt5.ORDER_TYPE_BUY
    assert sent["price"] == 1.08508  # buys fill at the ask
    assert sent["sl"] == 1.08 and sent["tp"] == 1.09
    assert sent["magic"] == 999001
    assert sent["comment"] == "fastapi-bridge:entry"
    assert sent["type_filling"] == mt5.ORDER_FILLING_FOK  # EURUSD advertises FOK

    positions = client.get("/api/v1/positions", headers=AUTH).json()
    assert len(positions) == 1
    assert positions[0]["side"] == "buy"
    assert positions[0]["volume"] == 0.10


def test_market_sell_fills_at_the_bid(client, mt5):
    _open_position(client, side="sell")
    sent = mt5.state.sent_requests[-1]
    assert sent["type"] == mt5.ORDER_TYPE_SELL
    assert sent["price"] == 1.085


def test_filling_mode_follows_the_symbol(client, mt5):
    _open_position(client, symbol="GBPUSD")
    assert mt5.state.sent_requests[-1]["type_filling"] == mt5.ORDER_FILLING_IOC


def test_volume_is_snapped_to_the_symbol_step(client, mt5):
    _open_position(client, volume=0.123)
    assert mt5.state.sent_requests[-1]["volume"] == 0.12


def test_volume_below_symbol_minimum_is_rejected(client):
    response = _open_position(client, volume=0.001)
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"


def test_volume_above_configured_cap_is_rejected(client, mt5):
    response = _open_position(client, volume=2.5)  # MAX_VOLUME=2.0 in the test env
    assert response.status_code == 403
    assert response.json()["error"] == "trading_not_allowed"
    assert mt5.state.sent_requests == []


def test_preflight_check_stops_the_order_before_it_is_sent(client, mt5):
    """order_check() gates order_send(): a failed check never reaches the market."""
    settings = get_settings()
    settings.max_volume = 10.0  # let the request through to the (fake) terminal
    try:
        response = _open_position(client, volume=6.0)
    finally:
        settings.max_volume = 2.0

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "trade_rejected"
    assert body["details"]["stage"] == "order_check"
    assert body["details"]["retcode"] == 10019
    assert body["details"]["retcode_description"] == "Not enough money to complete the request"
    assert mt5.state.sent_requests == []


def test_accepted_order_reports_its_preflight(client):
    body = _open_position(client).json()
    assert body["preflight"]["retcode"] == 0
    assert body["preflight"]["margin_free"] == 9930.0


def test_server_rejection_maps_to_400_with_retcode(client_factory, mt5):
    """With the pre-flight off, the trade server's own rejection is reported."""
    direct = client_factory(PREFLIGHT_ORDER_CHECK="false", MAX_VOLUME="10.0")
    response = _open_position(direct, volume=6.0)

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "trade_rejected"
    assert body["details"]["retcode"] == 10019
    assert "stage" not in body["details"]
    assert len(mt5.state.sent_requests) == 1


def test_dry_run_validates_without_sending(client, mt5):
    response = _open_position(client, dry_run=True)
    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True and body["dry_run"] is True
    assert mt5.state.sent_requests == []
    assert mt5.state.positions == {}


def test_market_order_rejects_a_price(client):
    response = _open_position(client, price=1.085)
    assert response.status_code == 422


def test_pending_order_requires_a_price(client):
    response = _open_position(client, type="limit")
    assert response.status_code == 422


def test_pending_limit_order_lifecycle(client, mt5):
    response = _open_position(client, type="limit", price=1.0700, volume=0.20)
    assert response.status_code == 201
    body = response.json()
    assert body["retcode"] == 10008
    assert body["success"] is True
    ticket = body["order"]

    sent = mt5.state.sent_requests[-1]
    assert sent["action"] == mt5.TRADE_ACTION_PENDING
    assert sent["type"] == mt5.ORDER_TYPE_BUY_LIMIT
    assert sent["type_time"] == mt5.ORDER_TIME_GTC

    orders = client.get("/api/v1/orders", headers=AUTH).json()
    assert [o["ticket"] for o in orders] == [ticket]

    cancelled = client.delete(f"/api/v1/orders/{ticket}", headers=AUTH)
    assert cancelled.status_code == 200
    assert cancelled.json()["success"] is True
    assert client.get("/api/v1/orders", headers=AUTH).json() == []


def test_cancelling_an_unknown_order_is_404(client):
    assert client.delete("/api/v1/orders/424242", headers=AUTH).status_code == 404


def test_close_position_fully(client, mt5):
    _open_position(client)
    ticket = next(iter(mt5.state.positions))

    response = client.post(f"/api/v1/positions/{ticket}/close", json={}, headers=AUTH)
    assert response.status_code == 200
    assert response.json()["success"] is True

    sent = mt5.state.sent_requests[-1]
    assert sent["position"] == ticket
    assert sent["type"] == mt5.ORDER_TYPE_SELL  # closing a long sells at the bid
    assert sent["price"] == 1.085
    assert client.get("/api/v1/positions", headers=AUTH).json() == []


def test_close_position_partially(client, mt5):
    _open_position(client, volume=0.30)
    ticket = next(iter(mt5.state.positions))

    response = client.post(
        f"/api/v1/positions/{ticket}/close", json={"volume": 0.10}, headers=AUTH
    )
    assert response.status_code == 200
    remaining = client.get("/api/v1/positions", headers=AUTH).json()
    assert remaining[0]["volume"] == pytest.approx(0.20)


def test_close_more_than_the_position_holds_is_rejected(client, mt5):
    _open_position(client, volume=0.10)
    ticket = next(iter(mt5.state.positions))
    response = client.post(
        f"/api/v1/positions/{ticket}/close", json={"volume": 0.50}, headers=AUTH
    )
    assert response.status_code == 422


def test_closing_an_unknown_position_is_404(client):
    response = client.post("/api/v1/positions/999999/close", json={}, headers=AUTH)
    assert response.status_code == 404


def test_modify_stops_keeps_the_untouched_level(client, mt5):
    _open_position(client, sl=1.0800, tp=1.0900)
    ticket = next(iter(mt5.state.positions))

    response = client.patch(f"/api/v1/positions/{ticket}", json={"sl": 1.0820}, headers=AUTH)
    assert response.status_code == 200
    sent = mt5.state.sent_requests[-1]
    assert sent["action"] == mt5.TRADE_ACTION_SLTP
    assert sent["sl"] == 1.082
    assert sent["tp"] == 1.09  # unchanged, not cleared

    position = mt5.state.positions[ticket]
    assert (position.sl, position.tp) == (1.082, 1.09)


def test_modify_without_levels_is_rejected(client, mt5):
    _open_position(client)
    ticket = next(iter(mt5.state.positions))
    response = client.patch(f"/api/v1/positions/{ticket}", json={}, headers=AUTH)
    assert response.status_code == 422


def test_deal_history(client):
    _open_position(client)
    deals = client.get("/api/v1/history/deals", params={"symbol": "EURUSD"}, headers=AUTH).json()
    assert len(deals) == 1
    assert deals[0]["symbol"] == "EURUSD"
    assert deals[0]["time"] is not None


def test_live_account_blocks_trading_but_not_market_data(client, mt5):
    mt5.state.trade_mode = mt5.ACCOUNT_TRADE_MODE_REAL
    with TestClient(create_app(get_settings())) as live_client:
        assert live_client.get("/api/v1/candles?symbol=EURUSD", headers=AUTH).status_code == 200

        response = _open_position(live_client)
        assert response.status_code == 403
        body = response.json()
        assert body["error"] == "trading_not_allowed"
        assert body["details"]["account_trade_mode"] == "real"
        assert mt5.state.sent_requests == []


def test_live_trading_override_allows_the_order(client, mt5, monkeypatch):
    mt5.state.trade_mode = mt5.ACCOUNT_TRADE_MODE_REAL
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "true")
    get_settings.cache_clear()
    try:
        with TestClient(create_app(get_settings())) as live_client:
            assert _open_position(live_client).status_code == 201
    finally:
        get_settings.cache_clear()


def test_autotrading_disabled_in_terminal_blocks_orders(client, mt5):
    mt5.state.terminal_trade_allowed = False
    response = _open_position(client)
    assert response.status_code == 403
    assert "AutoTrading" in response.json()["message"]
