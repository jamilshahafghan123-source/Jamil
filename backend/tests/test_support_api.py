"""Support API authorisation (sections 8, 9, 12).

These run against the real app over a real (in-memory) database, because
the property under test — that one customer cannot reach another's ticket —
is a property of the queries, and mocking the database would test nothing.
"""

from __future__ import annotations

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
