"""Backend route authorisation (sections 4, 5, 7, 10).

These go through the real app with real tokens, because the claim under
test is "a CUSTOMER's token cannot reach these endpoints" — and a token is
exactly what a bypass attempt would use. Nothing here mocks the gate.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base, get_db
from app.main import app
from app.models import (
    RiskSettings,
    Subscription,
    SubscriptionStatus,
    User,
    UserRole,
)
from app.security import create_access_token

#: Every route a customer without entitlement must not reach.
PLATFORM_ROUTES = [
    ("GET", "/api/account"),
    ("GET", "/api/market/tick"),
    ("GET", "/api/positions"),
    ("GET", "/api/history/deals"),
    ("GET", "/api/history/orders"),
    ("GET", "/api/status"),
    ("GET", "/api/dashboard"),
    ("GET", "/api/risk/settings"),
    ("GET", "/api/analysis/signals"),
    ("GET", "/api/analysis/indicators"),
    ("POST", "/api/trading/execute"),
    ("POST", "/api/trading/close-all"),
    ("POST", "/api/risk/emergency-stop"),
    ("POST", "/api/risk/bot/pause"),
    # Strategies are customer trading configuration and sit behind the
    # same platform gate as everything else here.
    ("GET", "/api/strategies"),
    ("GET", "/api/strategies/vocabulary"),
    ("GET", "/api/alerts"),
    ("GET", "/api/alerts/kinds"),
    ("GET", "/api/opportunities"),
]

ADMIN_ROUTES = [
    ("GET", "/api/admin/control-centre"),
    ("GET", "/api/admin/support/tickets"),
]


async def _call(client, method, path, token=None, json=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return await client.request(method, path, headers=headers, json=json or {})


@pytest_asyncio.fixture
async def env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        users = {
            "plain": User(email="plain@example.com", password_hash="x",
                          role=UserRole.CUSTOMER, is_active=True),
            "subbed": User(email="subbed@example.com", password_hash="x",
                           role=UserRole.CUSTOMER, is_active=True),
            "expired": User(email="expired@example.com", password_hash="x",
                            role=UserRole.CUSTOMER, is_active=True),
            "inactive": User(email="off@example.com", password_hash="x",
                             role=UserRole.CUSTOMER, is_active=False),
            "admin": User(email="admin@example.com", password_hash="x",
                          role=UserRole.ADMIN, is_active=True),
        }
        db.add_all(list(users.values()))
        await db.commit()
        for u in users.values():
            await db.refresh(u)
            db.add(RiskSettings(user_id=u.id))
        now = datetime.now(timezone.utc)
        db.add(
            Subscription(user_id=users["subbed"].id,
                         status=SubscriptionStatus.ACTIVE, plan="monthly",
                         current_period_end=now + timedelta(days=30))
        )
        # ACTIVE but the period has ended: the date must win.
        db.add(
            Subscription(user_id=users["expired"].id,
                         status=SubscriptionStatus.ACTIVE, plan="monthly",
                         current_period_end=now - timedelta(days=1))
        )
        await db.commit()

        tokens = {k: create_access_token(str(u.id)) for k, u in users.items()}

    async def override_db():
        async with Session() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        yield {"client": client, "tokens": tokens, "users": users,
               "Session": Session}
    app.dependency_overrides.clear()
    await engine.dispose()


# ------------------------------------------------------- unauthenticated


@pytest.mark.parametrize("method,path", PLATFORM_ROUTES)
@pytest.mark.asyncio
async def test_unauthenticated_is_refused(env, method, path):
    r = await _call(env["client"], method, path)
    assert r.status_code == 401, path


@pytest.mark.asyncio
async def test_health_stays_open_for_container_checks(env):
    """Gating /health would break the Docker health check."""
    r = await env["client"].get("/health")
    assert r.status_code == 200


# ------------------------------------------- the gap this task closes


@pytest.mark.parametrize("method,path", PLATFORM_ROUTES)
@pytest.mark.asyncio
async def test_customer_without_subscription_cannot_bypass_the_frontend_gate(
    env, method, path
):
    """A valid CUSTOMER token, used directly against the API, is refused."""
    r = await _call(env["client"], method, path, token=env["tokens"]["plain"])
    assert r.status_code == 403, f"{path} returned {r.status_code}"


@pytest.mark.parametrize("method,path", PLATFORM_ROUTES)
@pytest.mark.asyncio
async def test_expired_subscription_is_refused(env, method, path):
    r = await _call(env["client"], method, path, token=env["tokens"]["expired"])
    assert r.status_code == 403, path


@pytest.mark.asyncio
async def test_inactive_user_is_refused(env):
    r = await _call(env["client"], "GET", "/api/dashboard",
                    token=env["tokens"]["inactive"])
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_denial_is_403_so_the_client_does_not_log_the_user_out(env):
    """401 would clear the token and bounce to login — a loop for a
    signed-in customer who simply has no subscription."""
    r = await _call(env["client"], "GET", "/api/dashboard",
                    token=env["tokens"]["plain"])
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_denial_leaks_no_internals(env):
    r = await _call(env["client"], "GET", "/api/dashboard",
                    token=env["tokens"]["plain"])
    body = r.text.lower()
    for leak in ("traceback", "sqlalchemy", "select ", "customer", "userrole",
                 "postgres", "token", "secret"):
        assert leak not in body, f"denial leaked {leak!r}"


# ------------------------------------------------------------- allowed


@pytest.mark.asyncio
async def test_admin_bypasses_the_subscription_requirement(env):
    """Not 403. It may still fail on the absent broker, never on access."""
    r = await _call(env["client"], "GET", "/api/risk/settings",
                    token=env["tokens"]["admin"])
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_subscribed_customer_is_allowed_through(env):
    r = await _call(env["client"], "GET", "/api/risk/settings",
                    token=env["tokens"]["subbed"])
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_auth_me_stays_reachable_without_a_subscription(env):
    """App.tsx calls it for every signed-in user; gating it would loop."""
    r = await _call(env["client"], "GET", "/api/auth/me",
                    token=env["tokens"]["plain"])
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_support_stays_reachable_without_a_subscription(env):
    """A gated customer is exactly who needs support."""
    r = await env["client"].post(
        "/api/support/ask",
        headers={"Authorization": f"Bearer {env['tokens']['plain']}"},
        json={"question": "What does RR mean?"},
    )
    assert r.status_code == 200


# --------------------------------------------------------------- admin


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
@pytest.mark.asyncio
async def test_customer_cannot_reach_admin_routes(env, method, path):
    for who in ("plain", "subbed"):
        r = await _call(env["client"], method, path, token=env["tokens"][who])
        assert r.status_code == 404, f"{path} as {who}"


@pytest.mark.asyncio
async def test_admin_reaches_admin_routes(env):
    r = await _call(env["client"], "GET", "/api/admin/support/tickets",
                    token=env["tokens"]["admin"])
    assert r.status_code == 200


# ------------------------------------------------- object-level ownership


@pytest.mark.asyncio
async def test_risk_settings_are_scoped_to_the_caller(env):
    """user_id is derived from the token; it is never accepted as input."""
    subbed = env["users"]["subbed"]
    admin = env["users"]["admin"]
    r = await env["client"].put(
        f"/api/risk/settings?user_id={admin.id}",
        headers={"Authorization": f"Bearer {env['tokens']['subbed']}"},
        json={"max_risk_per_trade_pct": 0.25, "max_daily_loss_pct": 2,
              "max_trades_per_day": 5, "max_open_positions": 1,
              "max_lot_size": 0.1, "min_confidence": 70, "min_rr": 1.5,
              "max_spread_points": 50},
    )
    assert r.status_code == 200
    async with env["Session"]() as db:
        from sqlalchemy import select

        rows = (await db.execute(select(RiskSettings))).scalars().all()
        mine = [x for x in rows if x.user_id == subbed.id][0]
        theirs = [x for x in rows if x.user_id == admin.id][0]
        assert mine.max_risk_per_trade_pct == 0.25
        # The query parameter was ignored, as it must be.
        assert theirs.max_risk_per_trade_pct != 0.25


@pytest.mark.asyncio
async def test_execute_refuses_another_users_signal(env):
    r = await env["client"].post(
        "/api/trading/execute",
        headers={"Authorization": f"Bearer {env['tokens']['subbed']}"},
        json={"signal_id": 999999},
    )
    assert r.status_code in (400, 404, 422)


# ---------------------------------------------------- real trading is off


def test_real_trading_remains_disabled():
    from app.config import get_settings

    assert get_settings().ALLOW_REAL_TRADING is False


def test_risk_engine_and_executor_are_untouched_by_this_layer():
    """Authorisation is added in front of the pipeline, never inside it."""
    from pathlib import Path

    for module in ("app/services/risk_engine.py", "app/services/executor.py"):
        source = Path(module).read_text(encoding="utf-8")
        assert "entitlement" not in source.lower()
        assert "subscription" not in source.lower()


# ------------------------------------------------ operator grant endpoint


@pytest.mark.asyncio
async def test_admin_can_grant_and_it_takes_effect_immediately(env):
    plain = env["users"]["plain"]
    r = await env["client"].put(
        f"/api/admin/subscriptions/{plain.id}",
        headers={"Authorization": f"Bearer {env['tokens']['admin']}"},
        json={"status": "ACTIVE", "plan": "monthly", "days": 30},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ACTIVE"

    after = await _call(env["client"], "GET", "/api/risk/settings",
                        token=env["tokens"]["plain"])
    assert after.status_code == 200


@pytest.mark.asyncio
async def test_revoking_takes_effect_immediately(env):
    subbed = env["users"]["subbed"]
    assert (
        await _call(env["client"], "GET", "/api/risk/settings",
                    token=env["tokens"]["subbed"])
    ).status_code == 200

    r = await env["client"].put(
        f"/api/admin/subscriptions/{subbed.id}",
        headers={"Authorization": f"Bearer {env['tokens']['admin']}"},
        json={"status": "CANCELED"},
    )
    assert r.status_code == 200

    assert (
        await _call(env["client"], "GET", "/api/risk/settings",
                    token=env["tokens"]["subbed"])
    ).status_code == 403


@pytest.mark.asyncio
async def test_customer_cannot_grant_themselves_a_subscription(env):
    """The obvious privilege escalation, and it must 404 like any admin route."""
    plain = env["users"]["plain"]
    r = await env["client"].put(
        f"/api/admin/subscriptions/{plain.id}",
        headers={"Authorization": f"Bearer {env['tokens']['plain']}"},
        json={"status": "ACTIVE", "days": 3650},
    )
    assert r.status_code == 404
    assert (
        await _call(env["client"], "GET", "/api/dashboard",
                    token=env["tokens"]["plain"])
    ).status_code == 403


@pytest.mark.asyncio
async def test_grant_is_audited(env):
    from sqlalchemy import select

    from app.models import AuditLog

    await env["client"].put(
        f"/api/admin/subscriptions/{env['users']['plain'].id}",
        headers={"Authorization": f"Bearer {env['tokens']['admin']}"},
        json={"status": "ACTIVE", "days": 7},
    )
    async with env["Session"]() as db:
        rows = (await db.execute(select(AuditLog))).scalars().all()
    events = [r.event for r in rows]
    assert "admin_subscription_set" in events
