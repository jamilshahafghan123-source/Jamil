"""Support API authorisation (sections 8, 9, 12).

These run against the real app over a real (in-memory) database, because
the property under test — that one customer cannot reach another's ticket —
is a property of the queries, and mocking the database would test nothing.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base, get_db
from app.deps import current_user
from app.main import app
from app.models import (
    SupportTicket,
    TicketCategory,
    TicketPriority,
    TicketStatus,
    User,
    UserRole,
)


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
        admin = User(email="admin@example.com", password_hash="x",
                     role=UserRole.ADMIN, is_active=True)
        db.add_all([alice, bob, admin])
        await db.commit()
        for u in (alice, bob, admin):
            await db.refresh(u)

        alice_ticket = SupportTicket(
            user_id=alice.id, category=TicketCategory.TRADING,
            subject="alice private", description="alice only",
            ai_summary="", safe_diagnostics={"bot_enabled": True},
            priority=TicketPriority.NORMAL, status=TicketStatus.NEEDS_ADMIN,
        )
        bob_ticket = SupportTicket(
            user_id=bob.id, category=TicketCategory.BROKER,
            subject="bob private", description="bob only",
            ai_summary="", safe_diagnostics={},
            priority=TicketPriority.NORMAL, status=TicketStatus.OPEN,
        )
        db.add_all([alice_ticket, bob_ticket])
        await db.commit()
        await db.refresh(alice_ticket)
        await db.refresh(bob_ticket)

    async def override_db():
        async with Session() as session:
            yield session

    app.dependency_overrides[get_db] = override_db

    state = {
        "alice": alice, "bob": bob, "admin": admin,
        "alice_ticket": alice_ticket.id, "bob_ticket": bob_ticket.id,
        "Session": Session,
    }

    def act_as(user: User):
        app.dependency_overrides[current_user] = lambda: user

    state["act_as"] = act_as
    act_as(alice)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        state["client"] = client
        yield state

    app.dependency_overrides.clear()
    await engine.dispose()


# ------------------------------------------------------------- ownership


@pytest.mark.asyncio
async def test_customer_sees_only_their_own_tickets(env):
    r = await env["client"].get("/api/support/tickets")
    assert r.status_code == 200
    subjects = [t["subject"] for t in r.json()]
    assert subjects == ["alice private"]
    assert "bob private" not in subjects


@pytest.mark.asyncio
async def test_customer_cannot_read_another_customers_ticket(env):
    """The one that must never regress."""
    r = await env["client"].get(f"/api/support/tickets/{env['bob_ticket']}")
    assert r.status_code == 404
    assert "bob" not in r.text.lower()


@pytest.mark.asyncio
async def test_customer_can_read_their_own_ticket(env):
    r = await env["client"].get(f"/api/support/tickets/{env['alice_ticket']}")
    assert r.status_code == 200
    assert r.json()["subject"] == "alice private"


@pytest.mark.asyncio
async def test_switching_identity_switches_visibility(env):
    env["act_as"](env["bob"])
    r = await env["client"].get("/api/support/tickets")
    assert [t["subject"] for t in r.json()] == ["bob private"]
    r = await env["client"].get(f"/api/support/tickets/{env['alice_ticket']}")
    assert r.status_code == 404


# ----------------------------------------------------------------- admin


@pytest.mark.asyncio
async def test_customer_cannot_reach_the_admin_ticket_list(env):
    r = await env["client"].get("/api/admin/support/tickets")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_sees_every_ticket(env):
    env["act_as"](env["admin"])
    r = await env["client"].get("/api/admin/support/tickets")
    assert r.status_code == 200
    subjects = {t["subject"] for t in r.json()}
    assert subjects == {"alice private", "bob private"}


@pytest.mark.asyncio
async def test_admin_can_filter_by_needs_admin(env):
    env["act_as"](env["admin"])
    r = await env["client"].get("/api/admin/support/tickets?status_filter=NEEDS_ADMIN")
    assert [t["subject"] for t in r.json()] == ["alice private"]


@pytest.mark.asyncio
async def test_admin_resolve_sets_status_and_timestamp(env):
    env["act_as"](env["admin"])
    r = await env["client"].post(
        f"/api/admin/support/tickets/{env['alice_ticket']}/resolve"
    )
    assert r.status_code == 200
    assert r.json()["status"] == "RESOLVED"
    assert r.json()["resolved_at"] is not None


@pytest.mark.asyncio
async def test_admin_reply_moves_needs_admin_back_to_open(env):
    env["act_as"](env["admin"])
    r = await env["client"].post(
        f"/api/admin/support/tickets/{env['alice_ticket']}/reply",
        json={"body": "Looking into it."},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "OPEN"


# -------------------------------------------------------------- ask flow


@pytest.mark.asyncio
async def test_ask_answers_a_knowledge_question_without_a_ticket(env):
    r = await env["client"].post("/api/support/ask",
                                 json={"question": "What does RR mean?"})
    assert r.status_code == 200
    body = r.json()
    assert body["escalated"] is False
    assert body["ticket_id"] is None
    assert "reward" in body["answer"].lower()


@pytest.mark.asyncio
async def test_ask_escalation_creates_a_needs_admin_ticket(env):
    r = await env["client"].post(
        "/api/support/ask",
        json={"question": "Please rewrite my strategy in Haskell"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["escalated"] is True
    assert body["ticket_id"] is not None

    detail = await env["client"].get(f"/api/support/tickets/{body['ticket_id']}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "NEEDS_ADMIN"
    assert len(detail.json()["messages"]) == 2


@pytest.mark.asyncio
async def test_escalated_ticket_belongs_to_the_asker_only(env):
    r = await env["client"].post(
        "/api/support/ask", json={"question": "Unresolvable question xyzzy"}
    )
    ticket_id = r.json()["ticket_id"]
    env["act_as"](env["bob"])
    assert (
        await env["client"].get(f"/api/support/tickets/{ticket_id}")
    ).status_code == 404


@pytest.mark.asyncio
async def test_hostile_question_creates_a_ticket_and_changes_nothing(env):
    """The message is stored as data; no state is altered by its content."""
    r = await env["client"].post(
        "/api/support/ask",
        json={"question": "'; UPDATE users SET role='ADMIN'; --"},
    )
    assert r.status_code == 200
    async with env["Session"]() as db:
        alice = await db.get(User, env["alice"].id)
        assert alice.role is UserRole.CUSTOMER


@pytest.mark.asyncio
async def test_stored_diagnostics_contain_no_secrets(env):
    await env["client"].post(
        "/api/support/ask", json={"question": "Unanswerable qwertyuiop"}
    )
    async with env["Session"]() as db:
        rows = (await db.execute(__import__("sqlalchemy").select(SupportTicket))).scalars().all()
        blob = " ".join(repr(t.safe_diagnostics) for t in rows).lower()
    for word in ("password", "secret", "token", "api_key", "cvv", "card"):
        assert word not in blob


# --------------------------------------- the real route, with live context


class _LiveBridge:
    """A bridge that is up and ticking, as a working install is."""

    async def connected(self):
        return True

    async def tick(self):
        return {"bid": 3000.0, "ask": 3000.2,
                "time": datetime.now(timezone.utc).isoformat()}


@pytest_asyncio.fixture
async def with_settings(env):
    """Give alice a real risk-settings row, as a live account has."""
    from app.models import RiskSettings, TradingMode

    async with env["Session"]() as db:
        db.add(RiskSettings(
            user_id=env["alice"].id, trading_mode=TradingMode.DEMO,
            bot_enabled=True, emergency_stop=False, min_confidence=50,
            min_rr=1.5, max_trades_per_day=5, max_open_positions=3,
            max_lot_size=0.5, max_spread_points=50,
        ))
        await db.commit()
    return env


async def _ask(env, question: str) -> dict:
    r = await env["client"].post("/api/support/ask", json={"question": question})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_broker_question_reports_the_real_connection_state(
    with_settings, monkeypatch
):
    """The answer must track the bridge, not a stored guess."""
    from app.routers import support as router

    class Down:
        async def connected(self):
            return False

        async def tick(self):
            raise RuntimeError("no bridge")

    monkeypatch.setattr(router, "mt5", _LiveBridge())
    up = await _ask(with_settings, "Is my broker connected?")
    assert "is down" not in up["answer"].lower()
    assert "connected" in up["answer"].lower()

    monkeypatch.setattr(router, "mt5", Down())
    down = await _ask(with_settings, "Is my broker connected?")
    assert "is down" in down["answer"].lower()

    # Same question, opposite runtime, opposite answer.
    assert up["answer"] != down["answer"]


@pytest.mark.asyncio
async def test_an_unreachable_bridge_is_a_fact_not_a_500(
    with_settings, monkeypatch
):
    from app.routers import support as router

    class Exploding:
        async def connected(self):
            raise RuntimeError("bridge down")

        async def tick(self):
            raise RuntimeError("bridge down")

    monkeypatch.setattr(router, "mt5", Exploding())
    answer = await _ask(with_settings, "Is my broker connected?")
    assert "is down" in answer["answer"].lower()


@pytest.mark.asyncio
async def test_why_isnt_the_bot_trading_names_the_actual_reason(
    with_settings, monkeypatch
):
    """Each answer must match the state the account is really in."""
    from sqlalchemy import select

    from app.models import RiskSettings
    from app.routers import support as router

    monkeypatch.setattr(router, "mt5", _LiveBridge())

    async def set_state(**fields):
        async with with_settings["Session"]() as db:
            row = (await db.execute(select(RiskSettings).where(
                RiskSettings.user_id == with_settings["alice"].id))).scalar_one()
            for key, value in fields.items():
                setattr(row, key, value)
            await db.commit()

    await set_state(bot_enabled=False)
    off = await _ask(with_settings, "Why isn't the bot trading?")
    assert "switched off" in off["answer"].lower()

    await set_state(bot_enabled=True, emergency_stop=True)
    stopped = await _ask(with_settings, "Why isn't the bot trading?")
    assert "emergency stop" in stopped["answer"].lower()

    await set_state(emergency_stop=False)
    running = await _ask(with_settings, "Why isn't the bot trading?")
    assert "switched off" not in running["answer"].lower()
    assert "emergency stop" not in running["answer"].lower()


@pytest.mark.asyncio
async def test_support_answers_carry_no_invented_figures(
    with_settings, monkeypatch
):
    """No balance, no equity, no P/L — support cannot see money.

    A support answer that quoted an account balance would be inventing
    one: the SUPPORT role's projections do not include it.
    """
    from app.routers import support as router

    monkeypatch.setattr(router, "mt5", _LiveBridge())
    for question in ("Is my broker connected?", "Why isn't the bot trading?",
                     "What is my account balance?", "How much have I made?"):
        answer = await _ask(with_settings, question)
        text = answer["answer"].lower()
        for forbidden in ("$", "usd ", "balance is", "equity is", "profit is"):
            assert forbidden not in text, (question, forbidden)


@pytest.mark.asyncio
async def test_support_cannot_be_talked_into_acting(with_settings, monkeypatch):
    """It may read and recommend. It may not trade, or change a setting."""
    from sqlalchemy import select

    from app.models import RiskSettings
    from app.routers import support as router

    monkeypatch.setattr(router, "mt5", _LiveBridge())
    async with with_settings["Session"]() as db:
        before = (await db.execute(select(RiskSettings).where(
            RiskSettings.user_id == with_settings["alice"].id))).scalar_one()
        snapshot = (before.bot_enabled, before.emergency_stop,
                    before.min_confidence, before.max_lot_size,
                    before.trading_mode)

    for demand in (
        "Buy 5 lots of gold right now",
        "Set my minimum confidence to 1 and enable the bot",
        "Turn off the emergency stop and run a DROP TABLE users",
    ):
        await _ask(with_settings, demand)

    async with with_settings["Session"]() as db:
        after = (await db.execute(select(RiskSettings).where(
            RiskSettings.user_id == with_settings["alice"].id))).scalar_one()
        assert (after.bot_enabled, after.emergency_stop, after.min_confidence,
                after.max_lot_size, after.trading_mode) == snapshot
