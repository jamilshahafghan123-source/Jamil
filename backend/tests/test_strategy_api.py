"""Strategy ownership and API safety (sections 32-37).

The property that matters: one customer's strategies are unreachable
from another's session, for reading, editing, cloning, enabling and
deleting alike.
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
    RiskSettings, Strategy, StrategyActionMode, Subscription,
    SubscriptionStatus, User, UserRole,
)
from app.security import create_access_token

RULE = {"logic": "AND", "children": [
    {"field": "RSI", "operator": "GT", "value": 55, "period": 14,
     "timeframe": "M15"},
    {"field": "SESSION_ACTIVE", "operator": "IS_TRUE"},
]}


@pytest_asyncio.fixture
async def env():
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
        bobs = Strategy(
            user_id=bob.id, name="Bob's edge", symbol="XAUUSD",
            timeframe="M15", direction="BUY",
            action_mode=StrategyActionMode.ALERT_ONLY, rule=RULE,
        )
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
        yield {"client": client, "tokens": tokens, "Session": Session,
               "bob_strategy": bobs.id}
    app.dependency_overrides.clear()
    await engine.dispose()


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _body(**over):
    body = {"name": "My strategy", "symbol": "XAUUSD", "timeframe": "M15",
            "direction": "BUY", "action_mode": "ALERT_ONLY", "rule": RULE}
    body.update(over)
    return body


# ------------------------------------------------------------ ownership

@pytest.mark.asyncio
async def test_a_customer_sees_only_their_own_strategies(env):
    r = await env["client"].get("/api/strategies", headers=_h(env["tokens"]["alice"]))
    assert r.status_code == 200
    assert r.json() == []

    r = await env["client"].get("/api/strategies", headers=_h(env["tokens"]["bob"]))
    assert [s["name"] for s in r.json()] == ["Bob's edge"]


@pytest.mark.asyncio
async def test_another_customers_strategy_cannot_be_updated(env):
    r = await env["client"].put(
        f"/api/strategies/{env['bob_strategy']}",
        headers=_h(env["tokens"]["alice"]), json=_body(name="hijacked"),
    )
    assert r.status_code == 404
    async with env["Session"]() as db:
        row = await db.get(Strategy, env["bob_strategy"])
        assert row.name == "Bob's edge"


@pytest.mark.asyncio
async def test_another_customers_strategy_cannot_be_deleted(env):
    r = await env["client"].delete(
        f"/api/strategies/{env['bob_strategy']}",
        headers=_h(env["tokens"]["alice"]),
    )
    assert r.status_code == 404
    async with env["Session"]() as db:
        assert await db.get(Strategy, env["bob_strategy"]) is not None


@pytest.mark.asyncio
async def test_another_customers_strategy_cannot_be_cloned(env):
    """Cloning would otherwise be a read of someone else's work."""
    r = await env["client"].post(
        f"/api/strategies/{env['bob_strategy']}/clone",
        headers=_h(env["tokens"]["alice"]),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_another_customers_strategy_cannot_be_enabled(env):
    r = await env["client"].post(
        f"/api/strategies/{env['bob_strategy']}/enabled?enabled=true",
        headers=_h(env["tokens"]["alice"]),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_a_missing_and_a_foreign_strategy_are_indistinguishable(env):
    """Both 404, so this cannot be used to discover that a row exists."""
    foreign = await env["client"].put(
        f"/api/strategies/{env['bob_strategy']}",
        headers=_h(env["tokens"]["alice"]), json=_body())
    missing = await env["client"].put(
        "/api/strategies/99999",
        headers=_h(env["tokens"]["alice"]), json=_body())
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


# ------------------------------------------------------------ safety

@pytest.mark.asyncio
async def test_a_rule_outside_the_vocabulary_is_refused(env):
    for bad in (
        {"field": "__import__", "operator": "GT", "value": 1},
        {"field": "RSI", "operator": "EXEC", "value": 1},
        {"field": "RSI", "operator": "GT", "value": "os.system('id')"},
    ):
        r = await env["client"].post(
            "/api/strategies", headers=_h(env["tokens"]["alice"]),
            json=_body(rule=bad))
        assert r.status_code == 400, bad


@pytest.mark.asyncio
async def test_real_broker_automation_cannot_be_requested(env):
    r = await env["client"].post(
        "/api/strategies", headers=_h(env["tokens"]["alice"]),
        json=_body(action_mode="REAL_AUTO"))
    assert r.status_code == 400
    assert "action mode" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_a_valid_strategy_round_trips_with_a_readable_description(env):
    r = await env["client"].post(
        "/api/strategies", headers=_h(env["tokens"]["alice"]), json=_body())
    assert r.status_code == 201
    payload = r.json()
    assert payload["valid"] is True
    assert payload["description"][0] == "AND"
    assert any("RSI(14)" in line for line in payload["description"])


@pytest.mark.asyncio
async def test_a_clone_starts_disabled(env):
    """Copying a running strategy must not quietly double what it does."""
    created = await env["client"].post(
        "/api/strategies", headers=_h(env["tokens"]["alice"]),
        json=_body(enabled=True))
    r = await env["client"].post(
        f"/api/strategies/{created.json()['id']}/clone",
        headers=_h(env["tokens"]["alice"]))
    assert r.status_code == 201
    assert r.json()["enabled"] is False


@pytest.mark.asyncio
async def test_a_stored_rule_is_revalidated_on_read(env):
    """A row edited directly in the database must not look runnable."""
    async with env["Session"]() as db:
        row = await db.get(Strategy, env["bob_strategy"])
        row.rule = {"field": "__import__", "operator": "GT", "value": 1}
        await db.commit()

    r = await env["client"].get("/api/strategies", headers=_h(env["tokens"]["bob"]))
    payload = r.json()[0]
    assert payload["valid"] is False
    assert payload["rule"] == {}
    assert "no longer be read" in payload["description"][0]


@pytest.mark.asyncio
async def test_an_unreadable_strategy_cannot_be_enabled(env):
    async with env["Session"]() as db:
        row = await db.get(Strategy, env["bob_strategy"])
        row.rule = {"field": "NONSENSE", "operator": "GT", "value": 1}
        row.enabled = False
        await db.commit()

    r = await env["client"].post(
        f"/api/strategies/{env['bob_strategy']}/enabled?enabled=true",
        headers=_h(env["tokens"]["bob"]))
    assert r.status_code == 400
    async with env["Session"]() as db:
        assert (await db.get(Strategy, env["bob_strategy"])).enabled is False


@pytest.mark.asyncio
async def test_the_vocabulary_endpoint_offers_only_what_the_parser_accepts(env):
    """The builder must not be able to offer a field the backend rejects."""
    from app.services import strategy as rules

    r = await env["client"].get("/api/strategies/vocabulary",
                                headers=_h(env["tokens"]["alice"]))
    payload = r.json()
    assert {f["field"] for f in payload["fields"]} == {f.value for f in rules.Field}
    assert set(payload["operators"]) == {o.value for o in rules.Operator}
    assert set(payload["action_modes"]) == {m.value for m in rules.ActionMode}
    assert "REAL_AUTO" not in payload["action_modes"]


@pytest.mark.asyncio
async def test_strategy_count_is_capped_per_customer(env):
    from app.routers.strategies import MAX_PER_USER

    async with env["Session"]() as db:
        result = await db.execute(select(User).where(User.email == "alice@example.com"))
        alice = result.scalar_one()
        for i in range(MAX_PER_USER):
            db.add(Strategy(user_id=alice.id, name=f"s{i}", symbol="XAUUSD",
                            timeframe="M15", direction="BUY",
                            action_mode=StrategyActionMode.ALERT_ONLY, rule=RULE))
        await db.commit()

    r = await env["client"].post(
        "/api/strategies", headers=_h(env["tokens"]["alice"]), json=_body())
    assert r.status_code == 400
    assert str(MAX_PER_USER) in r.json()["detail"]
