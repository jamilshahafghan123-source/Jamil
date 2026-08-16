"""The autonomous loop: its gates, its cadence, and what it does with a signal."""

from __future__ import annotations

import asyncio

import pytest

from tests import series
from tests.conftest import AUTH

GOLD = "XAUUSD"


def load(mt5, rates):
    """Multi-timeframe fixture plus a matching quote."""
    mt5.state.rates[GOLD] = rates
    price = series.last_close(rates)
    mt5.state.quotes[GOLD] = (round(price - 0.15, 2), round(price + 0.15, 2))
    return price


@pytest.fixture
def trending(mt5):
    load(mt5, series.xauusd_bullish())
    return mt5


def bot_client(client_factory, **env):
    settings = {
        "RISK_ENABLED": "true",
        "BOT_ENABLED": "true",
        "BOT_POLL_SECONDS": "1",
        "BOT_MODE": "interval",
        **env,
    }
    return client_factory(**settings)


def wait_for(client, predicate, timeout=6.0):
    """Poll /bot/status until the bot has done the thing, or give up."""
    import time

    deadline = time.time() + timeout
    status = client.get("/bot/status", headers=AUTH).json()
    while time.time() < deadline:
        if predicate(status):
            return status
        time.sleep(0.1)
        status = client.get("/bot/status", headers=AUTH).json()
    return status


# --- gates --------------------------------------------------------------------


def test_bot_is_disabled_by_default(client_factory, trending):
    default = client_factory(RISK_ENABLED="true")
    response = default.post("/bot/start", json={}, headers=AUTH)

    assert response.status_code == 403
    assert response.json()["error"] == "bot_not_allowed"
    assert default.get("/bot/status", headers=AUTH).json()["running"] is False


def test_dry_run_is_the_default_even_when_enabled(client_factory, trending):
    client = bot_client(client_factory)
    status = client.get("/bot/status", headers=AUTH).json()
    assert status["enabled"] is True
    assert status["dry_run"] is True


def test_bot_refuses_to_start_on_a_live_account(client_factory, mt5):
    load(mt5, series.xauusd_bullish())
    mt5.state.trade_mode = mt5.ACCOUNT_TRADE_MODE_REAL
    client = bot_client(client_factory)

    response = client.post("/bot/start", json={}, headers=AUTH)
    assert response.status_code == 403
    assert response.json()["error"] == "trading_not_allowed"


def test_start_is_not_repeatable_while_running(client_factory, trending):
    client = bot_client(client_factory)
    assert client.post("/bot/start", json={}, headers=AUTH).status_code == 200

    second = client.post("/bot/start", json={}, headers=AUTH)
    assert second.status_code == 403
    assert "already running" in second.json()["message"]
    client.post("/bot/stop", headers=AUTH)


def test_start_and_stop_move_the_status(client_factory, trending):
    client = bot_client(client_factory)

    started = client.post("/bot/start", json={}, headers=AUTH).json()
    assert started["running"] is True
    assert started["symbol"] == GOLD
    assert started["started_at"]

    stopped = client.post("/bot/stop", headers=AUTH).json()
    assert stopped["running"] is False
    assert stopped["stopped_at"]


def test_stopping_a_stopped_bot_is_a_no_op(client_factory, trending):
    client = bot_client(client_factory)
    assert client.post("/bot/stop", headers=AUTH).status_code == 200
    assert client.post("/bot/stop", headers=AUTH).json()["running"] is False


def test_start_can_override_the_symbol_and_timeframe(client_factory, trending):
    client = bot_client(client_factory)
    started = client.post(
        "/bot/start", json={"symbol": "xauusd", "timeframe": "m5"}, headers=AUTH
    ).json()

    assert started["symbol"] == GOLD  # normalised
    assert started["timeframe"] == "M5"
    client.post("/bot/stop", headers=AUTH)


def test_start_cannot_switch_off_dry_run(client_factory, trending):
    """The API deliberately has no lever to loosen the config's safety setting."""
    client = bot_client(client_factory)
    response = client.post("/bot/start", json={"dry_run": False}, headers=AUTH)
    assert response.status_code == 422


# --- behaviour ----------------------------------------------------------------


def test_f_dry_run_records_the_strategy_signal_without_sending_it(
    client_factory, trending, mt5
):
    """BOT_DRY_RUN=true: the XAUUSD strategy runs for real, no order is placed."""
    client = bot_client(client_factory)
    client.post("/bot/start", json={}, headers=AUTH)

    status = wait_for(client, lambda s: bool(s["trades"]))
    client.post("/bot/stop", headers=AUTH)

    assert status["trades"], "the bot never reached a decision"
    trade = status["trades"][0]
    assert trade["executed"] is False
    assert trade["side"] == "buy"
    assert trade["symbol"] == GOLD
    assert trade["sl"] and trade["tp"], "the strategy's stop and target are recorded"
    assert "dry run" in trade["detail"]
    # The whole point: nothing reached the terminal, and no position exists.
    assert mt5.state.sent_requests == []
    assert mt5.state.positions == {}


def test_live_mode_sends_the_order_through_the_normal_path(
    client_factory, trending, mt5
):
    client = bot_client(client_factory, BOT_DRY_RUN="false")
    client.post("/bot/start", json={}, headers=AUTH)

    status = wait_for(client, lambda s: any(t["executed"] for t in s["trades"]))
    client.post("/bot/stop", headers=AUTH)

    executed = [t for t in status["trades"] if t["executed"]]
    assert executed, "the bot never sent an order"
    assert "retcode 10009" in executed[0]["detail"]

    # It went out as a normal order: same magic, stops attached, position open.
    sent = mt5.state.sent_requests[-1]
    assert sent["symbol"] == GOLD
    assert sent["sl"] and sent["tp"]
    assert len(mt5.state.positions) >= 1


def test_a_no_trade_verdict_is_recorded_and_nothing_is_sent(
    client_factory, mt5
):
    load(mt5, series.xauusd_conflicting())
    client = bot_client(client_factory, BOT_DRY_RUN="false")
    client.post("/bot/start", json={}, headers=AUTH)

    status = wait_for(client, lambda s: any(e["kind"] == "no_trade" for e in s["events"]))
    client.post("/bot/stop", headers=AUTH)

    assert any(e["kind"] == "no_trade" for e in status["events"])
    assert status["last_decision"]["decision"] == "no_trade"
    assert mt5.state.sent_requests == []


def test_the_risk_policy_still_governs_the_bot(client_factory, trending, mt5):
    """Position limit already used: the bot's orders are refused, not sent."""
    order = {"symbol": GOLD, "side": "buy", "volume": 0.10, "type": "market",
             "sl": round(mt5.state.quotes[GOLD][1] - 4, 2),
             "tp": round(mt5.state.quotes[GOLD][1] + 8, 2)}
    client = bot_client(client_factory, BOT_DRY_RUN="false")
    for _ in range(2):
        assert client.post("/api/v1/orders", json=order, headers=AUTH).status_code == 201
    before = len(mt5.state.sent_requests)

    client.post("/bot/start", json={}, headers=AUTH)
    status = wait_for(client, lambda s: s["last_decision"] is not None)
    client.post("/bot/stop", headers=AUTH)

    # It looked, it was refused, and it sent nothing beyond the two seeded orders.
    assert len(mt5.state.sent_requests) == before
    assert status["last_decision"] is not None


def test_daily_trade_cap_stands_the_bot_down(client_factory, trending, mt5):
    client = bot_client(client_factory, BOT_DRY_RUN="false", BOT_MAX_TRADES_PER_DAY="1")
    client.post("/bot/start", json={}, headers=AUTH)

    status = wait_for(client, lambda s: any(e["kind"] == "capped" for e in s["events"]))
    client.post("/bot/stop", headers=AUTH)

    assert any(e["kind"] == "capped" for e in status["events"])
    assert status["trades_today"] <= 1


def test_bar_mode_waits_for_a_candle_to_close(client_factory, trending, mt5):
    """In bar mode the bot must not act on the bar that was already forming."""
    client = bot_client(client_factory, BOT_MODE="bar", BOT_DRY_RUN="false")
    client.post("/bot/start", json={}, headers=AUTH)

    status = wait_for(client, lambda s: any(e["kind"] == "waiting" for e in s["events"]))
    client.post("/bot/stop", headers=AUTH)

    assert any(e["kind"] == "waiting" for e in status["events"])
    # No new bar arrived during the test, so nothing was traded.
    assert mt5.state.sent_requests == []


def test_stopping_leaves_open_positions_alone(client_factory, trending, mt5):
    client = bot_client(client_factory, BOT_DRY_RUN="false")
    client.post("/bot/start", json={}, headers=AUTH)
    wait_for(client, lambda s: any(t["executed"] for t in s["trades"]))
    open_before = len(mt5.state.positions)

    client.post("/bot/stop", headers=AUTH)
    assert len(mt5.state.positions) == open_before


def test_status_needs_auth(client_factory, trending):
    client = bot_client(client_factory)
    assert client.get("/bot/status").status_code == 401


@pytest.mark.anyio
async def test_engine_survives_a_failing_iteration(monkeypatch):
    """A bad tick logs and keeps watching rather than killing the loop."""
    from app.bot import engine as engine_module
    from app.config import Settings

    settings = Settings(bot_enabled=True, bot_poll_seconds=1, risk_allowed_symbols=GOLD)
    bot = engine_module.TradingBot(session=None, settings=settings)  # type: ignore[arg-type]

    calls = {"n": 0}

    async def boom(*_args, **_kwargs):
        calls["n"] += 1
        raise RuntimeError("terminal hiccup")

    monkeypatch.setattr(bot, "_tick", boom)
    bot._stopping.clear()
    task = asyncio.create_task(bot._run())
    await asyncio.sleep(0.05)
    bot._stopping.set()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert calls["n"] >= 1
    assert any(event["kind"] == "error" for event in bot._events)


@pytest.fixture
def anyio_backend():
    return "asyncio"
