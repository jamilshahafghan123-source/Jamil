"""J Gold AI internal demo engine (sections 8-11, 39).

The load-bearing test in this file is the isolation one: no demo path may
reach MT5, the executor or any broker. Everything else is arithmetic that
has to be right before a customer trusts a number on screen.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base, get_db
from app.main import app
from app.models import (
    DemoAccount,
    DemoPosition,
    DemoPositionSide,
    DemoTrade,
    RiskSettings,
    Subscription,
    SubscriptionStatus,
    TradeSource,
    User,
    UserRole,
)
from app.security import create_access_token
from app.services import demo_engine, instruments
from app.services.demo_engine import DemoError, Quote

GOLD = instruments.get("XAUUSD")


# ------------------------------------------------------------ isolation


FORBIDDEN = ("mt5", "mt5_client", "executor", "bridge", "order_send",
             "BrokerAdapter", "subprocess", "close_all", "execute_signal")


def _referenced_names(path: str) -> set[str]:
    """Identifiers a module actually references, ignoring prose.

    Scanning raw text would match the word "executor" inside a docstring
    explaining that there is no executor, which is exactly the sentence a
    correct module should contain.
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            names.update((node.module or "").split("."))
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            for a in node.names:
                names.update(a.name.split("."))
    return names


def test_demo_engine_cannot_reach_a_broker():
    """The property that makes this a *simulator*.

    If a future edit references the executor or the bridge here, this
    fails — the guarantee does not rest on present good behaviour.
    """
    referenced = _referenced_names("app/services/demo_engine.py")
    for forbidden in FORBIDDEN:
        assert forbidden not in referenced, (
            f"demo engine references {forbidden!r}"
        )


def test_demo_engine_imports_nothing_that_executes():
    import ast
    from pathlib import Path

    tree = ast.parse(Path("app/services/demo_engine.py").read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
        elif isinstance(node, ast.Import):
            imported.extend(a.name for a in node.names)
    for name in imported:
        assert "executor" not in name
        assert "mt5" not in name


def test_demo_router_never_calls_the_executor():
    """The router may read a price from the bridge; it may never execute."""
    referenced = _referenced_names("app/routers/demo.py")
    for forbidden in ("executor", "execute_signal", "close_all", "order_send",
                      "close_position_broker"):
        assert forbidden not in referenced


# ----------------------------------------------------------- arithmetic


def test_value_per_price_unit_comes_from_instrument_metadata():
    """1.00 lot of gold moving $1.00 is $100, derived, not hard-coded."""
    assert GOLD.value_per_price_unit(1.0) == pytest.approx(100.0)
    assert GOLD.value_per_price_unit(0.1) == pytest.approx(10.0)


def test_buy_profit_and_loss():
    account = DemoAccount(id=1, starting_balance=100000.0, balance=100000.0,
                          currency="USD")
    position = demo_engine.open_position(
        account, symbol="XAUUSD", side=DemoPositionSide.BUY, volume=1.0,
        quote=Quote(bid=3000.00, ask=3000.30),
    )
    assert position.entry_price == 3000.30  # bought at the ask

    # Price up $10: closes at the bid, so the spread is a real cost.
    up = demo_engine.position_pnl(position, Quote(bid=3010.00, ask=3010.30), GOLD)
    assert up == pytest.approx((3010.00 - 3000.30) * 100, abs=0.01)

    down = demo_engine.position_pnl(position, Quote(bid=2990.00, ask=2990.30), GOLD)
    assert down < 0


def test_sell_profit_is_the_mirror():
    account = DemoAccount(id=1, starting_balance=100000.0, balance=100000.0)
    position = demo_engine.open_position(
        account, symbol="XAUUSD", side=DemoPositionSide.SELL, volume=1.0,
        quote=Quote(bid=3000.00, ask=3000.30),
    )
    assert position.entry_price == 3000.00  # sold at the bid
    profit = demo_engine.position_pnl(position, Quote(bid=2990.00, ask=2990.30), GOLD)
    assert profit == pytest.approx((3000.00 - 2990.30) * 100, abs=0.01)


def test_closing_moves_the_balance_by_exactly_the_realised_amount():
    account = DemoAccount(id=1, starting_balance=100000.0, balance=100000.0)
    position = demo_engine.open_position(
        account, symbol="XAUUSD", side=DemoPositionSide.BUY, volume=0.1,
        quote=Quote(bid=3000.00, ask=3000.00),
    )
    trade = demo_engine.close_position(
        account, position, Quote(bid=3010.00, ask=3010.00)
    )
    assert trade.realized_pnl == pytest.approx(100.0, abs=0.01)
    assert account.balance == pytest.approx(100100.0, abs=0.01)


def test_a_second_instrument_uses_its_own_specification():
    """The reason value is not hard-coded: EURUSD is nothing like gold."""
    eur = instruments.get("EURUSD")
    assert eur.value_per_price_unit(1.0) == pytest.approx(100000.0)
    assert eur.value_per_price_unit(1.0) != GOLD.value_per_price_unit(1.0)


# ----------------------------------------------------------- validation


@pytest.mark.parametrize("volume", [0, -1, 0.001, 1000.0, float("nan")])
def test_invalid_volume_is_rejected(volume):
    account = DemoAccount(id=1, starting_balance=100000.0, balance=100000.0)
    with pytest.raises(DemoError):
        demo_engine.open_position(
            account, symbol="XAUUSD", side=DemoPositionSide.BUY, volume=volume,
            quote=Quote(bid=3000.0, ask=3000.0),
        )


def test_a_stop_on_the_wrong_side_is_rejected():
    account = DemoAccount(id=1, starting_balance=100000.0, balance=100000.0)
    with pytest.raises(DemoError):
        demo_engine.open_position(
            account, symbol="XAUUSD", side=DemoPositionSide.BUY, volume=0.1,
            quote=Quote(bid=3000.0, ask=3000.0), stop_loss=3100.0,
        )
    with pytest.raises(DemoError):
        demo_engine.open_position(
            account, symbol="XAUUSD", side=DemoPositionSide.SELL, volume=0.1,
            quote=Quote(bid=3000.0, ask=3000.0), take_profit=3100.0,
        )


def test_a_symbol_that_is_not_enabled_cannot_be_traded():
    account = DemoAccount(id=1, starting_balance=100000.0, balance=100000.0)
    with pytest.raises(instruments.InstrumentNotTradableError):
        demo_engine.open_position(
            account, symbol="BTCUSD", side=DemoPositionSide.BUY, volume=0.1,
            quote=Quote(bid=60000.0, ask=60000.0),
        )


def test_only_gold_is_enabled_today():
    enabled = [i.symbol for i in instruments.all_instruments() if i.tradable]
    assert enabled == ["XAUUSD"]


# ------------------------------------------------------------ stops/targets


def test_stop_and_target_trigger_on_the_closing_price_not_the_mid():
    """A stop that only fires on the mid is a stop that lies."""
    position = DemoPosition(
        account_id=1, symbol="XAUUSD", side=DemoPositionSide.BUY, volume=1.0,
        entry_price=3000.0, stop_loss=2990.0, take_profit=3020.0,
        source=TradeSource.MANUAL,
    )
    # Bid at the stop: a buy closes at the bid, so this triggers.
    assert demo_engine.stop_or_target_hit(
        position, Quote(bid=2990.0, ask=2990.4)
    ) == "STOP_LOSS"
    assert demo_engine.stop_or_target_hit(
        position, Quote(bid=3020.0, ask=3020.4)
    ) == "TAKE_PROFIT"
    assert demo_engine.stop_or_target_hit(
        position, Quote(bid=3005.0, ask=3005.4)
    ) is None


# -------------------------------------------------------------- snapshot


def test_equity_is_balance_plus_floating():
    account = DemoAccount(id=1, starting_balance=100000.0, balance=100000.0,
                          currency="USD")
    position = DemoPosition(
        account_id=1, symbol="XAUUSD", side=DemoPositionSide.BUY, volume=1.0,
        entry_price=3000.0, source=TradeSource.MANUAL,
    )
    snap = demo_engine.snapshot(
        account, [position], {"XAUUSD": Quote(bid=3005.0, ask=3005.0)}
    )
    assert snap.floating_pnl == pytest.approx(500.0)
    assert snap.equity == pytest.approx(100500.0)
    assert snap.realized_pnl == pytest.approx(0.0)


def test_an_unpriced_position_contributes_zero_not_a_guess():
    account = DemoAccount(id=1, starting_balance=100000.0, balance=100000.0)
    position = DemoPosition(
        account_id=1, symbol="XAUUSD", side=DemoPositionSide.BUY, volume=1.0,
        entry_price=3000.0, source=TradeSource.MANUAL,
    )
    snap = demo_engine.snapshot(account, [position], {})
    assert snap.floating_pnl == 0.0
    assert snap.equity == account.balance


def test_snapshot_always_says_it_is_virtual():
    account = DemoAccount(id=1, starting_balance=100000.0, balance=100000.0)
    payload = demo_engine.snapshot(account, [], {}).as_dict()
    assert payload["account_type"] == "J_GOLD_AI_DEMO"
    assert payload["virtual_money"] is True
    assert payload["withdrawable"] is False


# ------------------------------------------------------------- API tests


@pytest_asyncio.fixture
async def env(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        alice = User(email="alice@example.com", password_hash="x",
                     role=UserRole.CUSTOMER, is_active=True)
        bob = User(email="bob@example.com", password_hash="x",
                   role=UserRole.CUSTOMER, is_active=True)
        db.add_all([alice, bob])
        await db.commit()
        for u in (alice, bob):
            await db.refresh(u)
            db.add(RiskSettings(user_id=u.id))
            db.add(Subscription(user_id=u.id, status=SubscriptionStatus.ACTIVE,
                                plan="monthly", current_period_end=None))
        await db.commit()
        tokens = {"alice": create_access_token(str(alice.id)),
                  "bob": create_access_token(str(bob.id))}

    async def override_db():
        async with Session() as session:
            yield session

    app.dependency_overrides[get_db] = override_db

    # A stub price. The engine never fetches one itself; this stands in for
    # the router's single call, so no test opens a socket.
    class StubMT5:
        async def tick(self):
            return {"bid": 3000.00, "ask": 3000.20}

        async def connected(self):
            return True

    monkeypatch.setattr("app.routers.demo.mt5", StubMT5())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        yield {"client": client, "tokens": tokens, "Session": Session,
               "alice": alice, "bob": bob}
    app.dependency_overrides.clear()
    await engine.dispose()


def _h(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.mark.asyncio
async def test_account_is_created_with_the_default_balance(env):
    r = await env["client"].get("/api/demo/account", headers=_h(env["tokens"]["alice"]))
    assert r.status_code == 200
    body = r.json()
    assert body["account"]["balance"] == 100000.0
    assert body["account"]["virtual_money"] is True
    assert body["account"]["withdrawable"] is False


@pytest.mark.asyncio
async def test_open_and_close_a_demo_position(env):
    client, h = env["client"], _h(env["tokens"]["alice"])
    opened = await client.post("/api/demo/positions", headers=h,
                               json={"symbol": "XAUUSD", "side": "BUY",
                                     "volume": 0.1})
    assert opened.status_code == 200
    pid = opened.json()["position"]["id"]

    closed = await client.post(f"/api/demo/positions/{pid}/close", headers=h)
    assert closed.status_code == 200

    trades = await client.get("/api/demo/trades", headers=h)
    assert len(trades.json()) == 1
    assert trades.json()[0]["account_type"] == "J_GOLD_AI_DEMO"


@pytest.mark.asyncio
async def test_one_customers_demo_account_is_invisible_to_another(env):
    client = env["client"]
    opened = await client.post("/api/demo/positions", headers=_h(env["tokens"]["alice"]),
                               json={"symbol": "XAUUSD", "side": "BUY", "volume": 0.1})
    pid = opened.json()["position"]["id"]

    # Bob cannot see it...
    bob_account = await client.get("/api/demo/account", headers=_h(env["tokens"]["bob"]))
    assert bob_account.json()["positions"] == []

    # ...nor close it.
    stolen = await client.post(f"/api/demo/positions/{pid}/close",
                               headers=_h(env["tokens"]["bob"]))
    assert stolen.status_code == 404


@pytest.mark.asyncio
async def test_maintenance_blocks_opening_but_not_closing(env):
    """The asymmetry, end to end."""
    from app.services import maintenance

    client, h = env["client"], _h(env["tokens"]["alice"])
    opened = await client.post("/api/demo/positions", headers=h,
                               json={"symbol": "XAUUSD", "side": "BUY",
                                     "volume": 0.1})
    pid = opened.json()["position"]["id"]

    maintenance.enter("Database restore")
    blocked = await client.post("/api/demo/positions", headers=h,
                                json={"symbol": "XAUUSD", "side": "BUY",
                                      "volume": 0.1})
    assert blocked.status_code == 503

    # Closing stays available: never trap someone in a trade.
    closed = await client.post(f"/api/demo/positions/{pid}/close", headers=h)
    assert closed.status_code == 200


@pytest.mark.asyncio
async def test_reset_requires_confirmation_and_clears_only_demo_rows(env):
    client, h = env["client"], _h(env["tokens"]["alice"])
    await client.post("/api/demo/positions", headers=h,
                      json={"symbol": "XAUUSD", "side": "BUY", "volume": 0.1})

    unconfirmed = await client.post("/api/demo/reset", headers=h, json={})
    assert unconfirmed.status_code == 400

    done = await client.post("/api/demo/reset", headers=h, json={"confirm": True})
    assert done.status_code == 200
    assert done.json()["balance"] == 100000.0

    after = await client.get("/api/demo/account", headers=h)
    assert after.json()["positions"] == []

    # The user, their subscription and their risk settings are untouched.
    async with env["Session"]() as db:
        assert (await db.execute(select(User))).scalars().all()
        assert (await db.execute(select(Subscription))).scalars().all()
        assert (await db.execute(select(RiskSettings))).scalars().all()


@pytest.mark.asyncio
async def test_a_coming_soon_symbol_is_refused_over_the_api(env):
    r = await env["client"].post("/api/demo/positions",
                                 headers=_h(env["tokens"]["alice"]),
                                 json={"symbol": "BTCUSD", "side": "BUY",
                                       "volume": 0.1})
    assert r.status_code == 400
    assert "not available" in r.text.lower()


@pytest.mark.asyncio
async def test_instruments_list_shows_planned_markets_without_pricing_them(env):
    r = await env["client"].get("/api/demo/instruments",
                                headers=_h(env["tokens"]["alice"]))
    grouped = r.json()["by_asset_class"]
    tradable = [i for group in grouped.values() for i in group if i["tradable"]]
    assert [i["symbol"] for i in tradable] == ["XAUUSD"]
    # Nothing carries a price.
    for group in grouped.values():
        for item in group:
            assert "price" not in item and "bid" not in item


@pytest.mark.asyncio
async def test_unauthenticated_cannot_touch_the_demo_account(env):
    for method, path in (("GET", "/api/demo/account"), ("POST", "/api/demo/reset"),
                         ("GET", "/api/demo/trades")):
        r = await env["client"].request(method, path, json={})
        assert r.status_code == 401


# ------------------------------------------------- AI Assist separation


def test_ai_assist_panel_has_no_execution_call():
    """Section 41: AI Assist fills a ticket, it never places an order.

    Asserted against the component's AST: the panel may call analysis, and
    must not call any order path. If a future edit wires one in, this fails.
    """
    import re
    from pathlib import Path

    source = Path("../frontend/src/components/AIPanel.tsx").read_text(encoding="utf-8")
    # Every api.* call the component makes.
    calls = set(re.findall(r"\bapi\.(\w+)", source))
    assert calls <= {"runAnalysis"}, f"AI panel calls {calls - {'runAnalysis'}}"
    for forbidden in ("demoOpen", "execute", "demoClose", "placeOrder"):
        assert forbidden not in source


def test_ai_setup_is_recorded_as_assisted_not_manual():
    """An assisted trade must be distinguishable in history."""
    from pathlib import Path

    source = Path("../frontend/src/pages/TradingWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    assert 'aiSetup ? "AI_ASSIST" : "MANUAL"' in source


def test_clearing_ai_overlays_touches_only_ai_state():
    """Section 22: clearing AI overlays must not delete customer content."""
    from pathlib import Path

    source = Path("../frontend/src/pages/TradingWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    clear_block = source.split("// Clears AI overlays only")[1][:300]
    assert "setAnalysis(null)" in clear_block
    assert "setAiSetup(null)" in clear_block
    # Nothing belonging to the user is reset here.
    for user_state in ("setStopLoss", "setTakeProfit", "setVolume", "setBars"):
        assert user_state not in clear_block
