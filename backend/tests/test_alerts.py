"""Alert evaluation and ownership (section 62)."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base, get_db
from app.main import app
from app.models import (
    Alert, AlertKind, RiskSettings, Subscription, SubscriptionStatus, User,
    UserRole,
)
from app.security import create_access_token
from app.services import alerts as engine
from app.services.alerts import MarketState


def _alert(**over) -> Alert:
    base = dict(kind=AlertKind.PRICE_ABOVE, symbol="XAUUSD", threshold=3000.0,
                enabled=True, repeatable=False, trigger_count=0)
    base.update(over)
    return Alert(**base)


# ------------------------------------------------- no fake delivery

def test_no_delivery_channel_exists_that_is_not_connected():
    """Section 62 forbids faking email, SMS or push.

    The honest way to honour that is to have no representation of them:
    no enum member, no field, no adapter. This checks the model itself,
    so adding one later means deliberately failing this test.
    """
    members = set(AlertKind.__members__)
    for absent in ("EMAIL", "SMS", "PUSH", "WEBHOOK", "TELEGRAM"):
        assert absent not in members
    assert not hasattr(Alert, "channel")
    assert not hasattr(Alert, "delivery")
    assert not hasattr(Alert, "phone")


# -------------------------------------------------------- evaluation

def test_a_price_alert_fires_only_once_the_level_is_passed():
    alert = _alert()
    assert engine.evaluate(alert, MarketState("XAUUSD", price=3010.0))
    assert engine.evaluate(alert, MarketState("XAUUSD", price=2990.0)) is None
    assert engine.evaluate(alert, MarketState("XAUUSD", price=3000.0)) is None


def test_an_unknown_price_never_fires_an_alert():
    """A feed outage must not look like a market move."""
    alert = _alert()
    assert engine.evaluate(alert, MarketState("XAUUSD", price=None)) is None


def test_a_crossing_needs_both_sides():
    """One price is a position, not a move."""
    alert = _alert(kind=AlertKind.PRICE_CROSSES, threshold=3000.0)
    assert engine.evaluate(alert, MarketState("XAUUSD", price=3010.0)) is None
    assert engine.evaluate(
        alert, MarketState("XAUUSD", price=3010.0, previous_price=2990.0))
    # Crossing downward counts too.
    assert engine.evaluate(
        alert, MarketState("XAUUSD", price=2990.0, previous_price=3010.0))
    # No cross when both sides are above.
    assert engine.evaluate(
        alert, MarketState("XAUUSD", price=3020.0, previous_price=3010.0)) is None


def test_a_one_shot_alert_stays_quiet_after_firing():
    """A level crossed once must not shout on every tick after it."""
    alert = _alert(trigger_count=1, repeatable=False)
    assert engine.evaluate(alert, MarketState("XAUUSD", price=3010.0)) is None
    repeatable = _alert(trigger_count=1, repeatable=True)
    assert engine.evaluate(repeatable, MarketState("XAUUSD", price=3010.0))


def test_a_disabled_alert_never_fires():
    assert engine.evaluate(
        _alert(enabled=False), MarketState("XAUUSD", price=3010.0)) is None


def test_an_alert_ignores_other_symbols():
    assert engine.evaluate(_alert(), MarketState("XAGUSD", price=3010.0)) is None


def test_an_ai_signal_alert_needs_an_actual_change():
    alert = _alert(kind=AlertKind.AI_SIGNAL_CHANGE, threshold=None)
    same = MarketState("XAUUSD", ai_signal="BUY", previous_ai_signal="BUY")
    assert engine.evaluate(alert, same) is None
    changed = MarketState("XAUUSD", ai_signal="SELL", previous_ai_signal="BUY")
    assert "BUY to SELL" in engine.evaluate(alert, changed)


def test_a_session_alert_can_be_scoped_to_one_session():
    alert = _alert(kind=AlertKind.SESSION_OPEN, threshold=None, session="LONDON")
    assert engine.evaluate(alert, MarketState(
        "XAUUSD", session="TOKYO", session_opening=True)) is None
    assert engine.evaluate(alert, MarketState(
        "XAUUSD", session="LONDON", session_opening=True))


def test_a_stop_loss_alert_ignores_a_take_profit_close():
    alert = _alert(kind=AlertKind.STOP_LOSS_HIT, threshold=None)
    tp = MarketState("XAUUSD", closed_position={"reason": "TAKE_PROFIT", "pnl": 40})
    assert engine.evaluate(alert, tp) is None
    sl = MarketState("XAUUSD", closed_position={"reason": "STOP_LOSS", "pnl": -20})
    message = engine.evaluate(alert, sl)
    assert "stop loss" in message and "-20" in message


def test_evaluation_is_pure_and_repeatable():
    alert = _alert()
    state = MarketState("XAUUSD", price=3010.0)
    first = engine.evaluate(alert, state)
    for _ in range(10):
        assert engine.evaluate(alert, state) == first
    assert alert.trigger_count == 0   # evaluation mutates nothing


# ------------------------------------------------------------- API

@pytest_asyncio.fixture
async def env():
    engine_db = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine_db.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine_db, expire_on_commit=False)
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
        bobs = Alert(user_id=bob.id, kind=AlertKind.PRICE_ABOVE,
                     symbol="XAUUSD", threshold=3100.0)
        db.add(bobs)
        await db.commit()
        await db.refresh(bobs)
        tokens = {"alice": create_access_token(str(alice.id)),
                  "bob": create_access_token(str(bob.id))}

    async def override_db():
        async with Session() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        yield {"client": client, "tokens": tokens, "bob_alert": bobs.id,
               "Session": Session, "alice_id": alice.id, "bob_id": bob.id}
    app.dependency_overrides.clear()
    await engine_db.dispose()


def _h(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.mark.asyncio
async def test_a_customer_sees_only_their_own_alerts(env):
    r = await env["client"].get("/api/alerts", headers=_h(env["tokens"]["alice"]))
    assert r.json()["alerts"] == []
    r = await env["client"].get("/api/alerts", headers=_h(env["tokens"]["bob"]))
    assert len(r.json()["alerts"]) == 1


@pytest.mark.asyncio
async def test_another_customers_alert_cannot_be_deleted_or_toggled(env):
    for path, method in ((f"/api/alerts/{env['bob_alert']}", "delete"),
                         (f"/api/alerts/{env['bob_alert']}/enabled?enabled=false", "post"),
                         (f"/api/alerts/{env['bob_alert']}/acknowledge", "post")):
        r = await getattr(env["client"], method)(path, headers=_h(env["tokens"]["alice"]))
        assert r.status_code == 404, path


@pytest.mark.asyncio
async def test_an_alert_that_could_never_fire_is_refused(env):
    """A price alert with no level is not an alert."""
    r = await env["client"].post("/api/alerts", headers=_h(env["tokens"]["alice"]),
                                 json={"kind": "PRICE_ABOVE", "symbol": "XAUUSD"})
    assert r.status_code == 400
    assert "needs a level" in r.json()["detail"]

    r = await env["client"].post("/api/alerts", headers=_h(env["tokens"]["alice"]),
                                 json={"kind": "SESSION_OPEN", "symbol": "XAUUSD"})
    assert r.status_code == 400
    assert "needs a session" in r.json()["detail"]


@pytest.mark.asyncio
async def test_an_unknown_alert_type_is_refused(env):
    r = await env["client"].post("/api/alerts", headers=_h(env["tokens"]["alice"]),
                                 json={"kind": "SEND_SMS", "symbol": "XAUUSD"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_the_kinds_endpoint_states_delivery_is_in_app_only(env):
    r = await env["client"].get("/api/alerts/kinds", headers=_h(env["tokens"]["alice"]))
    payload = r.json()
    assert payload["delivery"] == "IN_APP"
    assert "not connected" in payload["delivery_note"]
    assert {k["kind"] for k in payload["kinds"]} == {k.value for k in AlertKind}


@pytest.mark.asyncio
async def test_re_enabling_a_one_shot_alert_arms_it_again(env):
    created = await env["client"].post(
        "/api/alerts", headers=_h(env["tokens"]["alice"]),
        json={"kind": "PRICE_ABOVE", "symbol": "XAUUSD", "threshold": 3000})
    alert_id = created.json()["id"]

    async with env["Session"]() as db:
        row = await db.get(Alert, alert_id)
        row.trigger_count = 1
        row.enabled = False
        await db.commit()

    r = await env["client"].post(f"/api/alerts/{alert_id}/enabled?enabled=true",
                                 headers=_h(env["tokens"]["alice"]))
    assert r.json()["trigger_count"] == 0


# ------------------------------------------- dispatch: the missing caller


@pytest.mark.asyncio
async def test_dispatch_fires_a_matching_alert_and_records_it(env):
    """Every piece of this existed and nothing called evaluate().

    trigger_count stayed at zero forever, so an alert was a promise
    rather than a feature. This asserts the whole write: the count, the
    message, the timestamp and the unacknowledged state the panel reads.
    """
    from app.services import alerts as engine

    async with env["Session"]() as db:
        row = Alert(user_id=env["alice_id"], kind=AlertKind.AI_SIGNAL_CHANGE,
                    symbol="XAUUSD", enabled=True, repeatable=True)
        db.add(row)
        await db.commit()
        await db.refresh(row)

        fired = await engine.dispatch(
            db, user_id=env["alice_id"],
            market=engine.MarketState(symbol="XAUUSD", ai_signal="BUY",
                                      previous_ai_signal="NO_TRADE"),
        )
        assert len(fired) == 1
        await db.refresh(row)
        assert row.trigger_count == 1
        assert "NO_TRADE to BUY" in row.last_message
        assert row.acknowledged is False
        assert row.triggered_at is not None


@pytest.mark.asyncio
async def test_dispatch_notifies_on_every_actionable_transition(env):
    """The four transitions that matter, and the three that must stay quiet."""
    from app.services import alerts as engine

    async def transition(previous: str, current: str) -> int:
        async with env["Session"]() as db:
            row = Alert(user_id=env["alice_id"], kind=AlertKind.AI_SIGNAL_CHANGE,
                        symbol="XAUUSD", enabled=True, repeatable=True)
            db.add(row)
            await db.commit()
            fired = await engine.dispatch(
                db, user_id=env["alice_id"],
                market=engine.MarketState(symbol="XAUUSD", ai_signal=current,
                                          previous_ai_signal=previous),
            )
            await db.delete(row)
            await db.commit()
            return len(fired)

    for previous, current in (("NO_TRADE", "BUY"), ("NO_TRADE", "SELL"),
                              ("BUY", "SELL"), ("SELL", "BUY")):
        assert await transition(previous, current) == 1, (previous, current)

    for repeated in ("BUY", "SELL", "NO_TRADE"):
        assert await transition(repeated, repeated) == 0, repeated


@pytest.mark.asyncio
async def test_dispatch_never_reaches_another_customers_alerts(env):
    """Scoped by query, not by a check afterwards."""
    from app.services import alerts as engine

    async with env["Session"]() as db:
        mine = Alert(user_id=env["alice_id"], kind=AlertKind.AI_SIGNAL_CHANGE,
                     symbol="XAUUSD", enabled=True, repeatable=True)
        theirs = Alert(user_id=env["bob_id"],
                       kind=AlertKind.AI_SIGNAL_CHANGE, symbol="XAUUSD",
                       enabled=True, repeatable=True)
        db.add_all([mine, theirs])
        await db.commit()
        await db.refresh(theirs)

        fired = await engine.dispatch(
            db, user_id=env["alice_id"],
            market=engine.MarketState(symbol="XAUUSD", ai_signal="BUY",
                                      previous_ai_signal="NO_TRADE"),
        )
        assert len(fired) == 1
        await db.refresh(theirs)
        assert theirs.trigger_count == 0


@pytest.mark.asyncio
async def test_a_disabled_alert_is_not_dispatched(env):
    from app.services import alerts as engine

    async with env["Session"]() as db:
        row = Alert(user_id=env["alice_id"], kind=AlertKind.AI_SIGNAL_CHANGE,
                    symbol="XAUUSD", enabled=False, repeatable=True)
        db.add(row)
        await db.commit()
        fired = await engine.dispatch(
            db, user_id=env["alice_id"],
            market=engine.MarketState(symbol="XAUUSD", ai_signal="BUY",
                                      previous_ai_signal="NO_TRADE"),
        )
    assert fired == []


def test_the_analysis_path_dispatches_alerts():
    """The caller has to be on the path that produces signals.

    Wired into run_analysis rather than the bot loop, so a customer gets
    the same notification whether the bot found the setup or they pressed
    Run analysis — one path, not two implementations.
    """
    import inspect

    from app.services import bot

    source = inspect.getsource(bot.run_analysis)
    assert "alerts.dispatch" in source
    assert "previous_ai_signal" in source
    # A notification must never cost the signal that was just recorded.
    tail = source.split("alerts.dispatch")[1]
    assert "except Exception" in tail


@pytest.mark.asyncio
async def test_the_whole_runtime_path_through_the_api(env):
    """Create through HTTP, fire, and read back what the panel reads.

    The unit tests above prove the rule and the write. This proves the
    fields the Alerts panel actually renders come back changed over the
    real endpoints.
    """
    from app.services import alerts as service

    client, h = env["client"], _h(env["tokens"]["alice"])

    created = await client.post("/api/alerts", headers=h, json={
        "kind": "AI_SIGNAL_CHANGE", "symbol": "XAUUSD", "repeatable": True,
    })
    assert created.status_code == 201, created.text
    alert_id = created.json()["id"]

    before = (await client.get("/api/alerts", headers=h)).json()
    row = next(a for a in before["alerts"] if a["id"] == alert_id)
    assert row["enabled"] is True
    assert row["trigger_count"] == 0
    assert row["last_message"] == ""
    assert before["unacknowledged"] == 0

    async with env["Session"]() as db:
        fired = await service.dispatch(
            db, user_id=env["alice_id"],
            market=service.MarketState(symbol="XAUUSD", ai_signal="BUY",
                                       previous_ai_signal="NO_TRADE"),
        )
    assert len(fired) == 1

    after = (await client.get("/api/alerts", headers=h)).json()
    row = next(a for a in after["alerts"] if a["id"] == alert_id)
    assert row["trigger_count"] == 1
    assert "NO_TRADE to BUY" in row["last_message"]
    assert row["acknowledged"] is False
    assert row["triggered_at"] is not None
    assert after["unacknowledged"] == 1, "the panel's badge count"

    acked = await client.post(f"/api/alerts/{alert_id}/acknowledge", headers=h)
    assert acked.status_code == 200
    settled = (await client.get("/api/alerts", headers=h)).json()
    assert settled["unacknowledged"] == 0
