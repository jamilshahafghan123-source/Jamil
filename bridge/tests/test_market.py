from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.conftest import AUTH


def test_health_needs_no_auth(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_reports_demo_account(client):
    response = client.get("/health/ready", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "connected": True,
        "login": 5031234,
        "trade_mode": "demo",
        "is_demo": True,
        "live_trading_allowed": False,
        "detail": None,
    }


def test_missing_api_key_is_rejected(client):
    assert client.get("/api/v1/candles?symbol=EURUSD").status_code == 401


def test_wrong_api_key_is_rejected(client):
    response = client.get("/api/v1/account", headers={"X-API-Key": "nope"})
    assert response.status_code == 403


def test_second_configured_key_works(client):
    response = client.get("/api/v1/account", headers={"X-API-Key": "test-key-two"})
    assert response.status_code == 200


def test_bearer_token_is_accepted(client):
    response = client.get(
        "/api/v1/account", headers={"Authorization": "Bearer test-key-one"}
    )
    assert response.status_code == 200


def test_wrong_bearer_token_is_rejected(client):
    response = client.get("/api/v1/account", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 403


def test_account_snapshot(client):
    body = client.get("/api/v1/account", headers=AUTH).json()
    assert body["login"] == 5031234
    assert body["is_demo"] is True
    assert body["currency"] == "USD"


def test_candles_default_query(client):
    response = client.get(
        "/api/v1/candles", params={"symbol": "EURUSD", "timeframe": "M15", "count": 10},
        headers=AUTH,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "EURUSD"
    assert body["count"] == 10
    assert len(body["candles"]) == 10

    first, second = body["candles"][0], body["candles"][1]
    assert set(first) == {
        "time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume",
    }
    # Oldest first, 15 minutes apart.
    t0 = datetime.fromisoformat(first["time"])
    t1 = datetime.fromisoformat(second["time"])
    assert t1 - t0 == timedelta(minutes=15)
    assert first["high"] >= first["open"] >= first["low"]


def test_candles_range_query(client):
    end = datetime.now(tz=timezone.utc).replace(microsecond=0)
    start = end - timedelta(hours=5)
    response = client.get(
        "/api/v1/candles",
        params={
            "symbol": "EURUSD",
            "timeframe": "H1",
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        headers=AUTH,
    )
    assert response.status_code == 200
    assert response.json()["count"] == 5


def test_candles_reject_inverted_range(client):
    end = datetime.now(tz=timezone.utc)
    response = client.get(
        "/api/v1/candles",
        params={
            "symbol": "EURUSD",
            "timeframe": "H1",
            "start": end.isoformat(),
            "end": (end - timedelta(hours=1)).isoformat(),
        },
        headers=AUTH,
    )
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"


def test_unknown_symbol_is_404(client):
    response = client.get(
        "/api/v1/candles", params={"symbol": "NOPEUSD", "timeframe": "M5"}, headers=AUTH
    )
    assert response.status_code == 404
    assert response.json()["error"] == "symbol_not_found"


def test_unsupported_timeframe_is_422(client):
    response = client.get(
        "/api/v1/candles", params={"symbol": "EURUSD", "timeframe": "M7"}, headers=AUTH
    )
    assert response.status_code == 422


def test_symbols_search_and_detail(client):
    rows = client.get("/api/v1/symbols", params={"search": "GBP"}, headers=AUTH).json()
    assert [row["name"] for row in rows] == ["GBPUSD"]

    detail = client.get("/api/v1/symbols/EURUSD", headers=AUTH).json()
    assert detail["digits"] == 5
    assert detail["volume_step"] == 0.01


def test_hidden_symbol_gets_selected_into_market_watch(client, mt5):
    assert mt5.state.symbols["GBPUSD"].visible is False
    response = client.get("/api/v1/tick/GBPUSD", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["bid"] == 1.26400
    assert mt5.state.symbols["GBPUSD"].visible is True


def test_tick_path_alias(client):
    singular = client.get("/api/v1/tick/EURUSD", headers=AUTH)
    plural = client.get("/api/v1/ticks/EURUSD", headers=AUTH)
    assert singular.status_code == plural.status_code == 200
    assert singular.json()["ask"] == plural.json()["ask"] == 1.08508


def test_terminal_failure_surfaces_as_503(client, mt5):
    mt5.shutdown()
    mt5.state.initialize_ok = False
    response = client.get("/api/v1/account", headers=AUTH)
    assert response.status_code == 503
    assert response.json()["error"] == "terminal_unavailable"


def test_session_reconnects_after_the_terminal_comes_back(client, mt5):
    mt5.shutdown()  # terminal closed underneath a live session
    mt5.state.initialize_ok = False
    assert client.get("/api/v1/account", headers=AUTH).status_code == 503

    mt5.state.initialize_ok = True  # terminal restarted
    response = client.get("/api/v1/account", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["login"] == 5031234
