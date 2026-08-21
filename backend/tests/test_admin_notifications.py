"""Notification centre and incident filtering (sections 4, 5, 10)."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base, get_db
from app.main import app
from app.models import (
    Incident,
    IncidentStatus,
    Notification,
    NotificationSeverity,
    RiskSettings,
    User,
    UserRole,
)
from app.security import create_access_token


@pytest_asyncio.fixture
async def env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        customer = User(email="c@example.com", password_hash="x",
                        role=UserRole.CUSTOMER, is_active=True)
        admin = User(email="a@example.com", password_hash="x",
                     role=UserRole.ADMIN, is_active=True)
        db.add_all([customer, admin])
        await db.commit()
        for u in (customer, admin):
            await db.refresh(u)
            db.add(RiskSettings(user_id=u.id))
        inc = Incident(service="BRIDGE", category="UNREACHABLE",
                       status=IncidentStatus.NEEDS_ADMIN,
                       actions=[{"operation": "RESTART_BRIDGE", "ok": False,
                                 "detail": "unreachable"}],
                       final_state="NEEDS_ADMIN", attempt_number=3)
        db.add(inc)
        await db.commit()
        await db.refresh(inc)
        db.add_all([
            Notification(severity=NotificationSeverity.CRITICAL,
                         event="auth_failure",
                         message="Bridge authentication failed.",
                         incident_id=inc.id),
            Notification(severity=NotificationSeverity.INFO,
                         event="bridge_restarted",
                         message="MT5 bridge restarted successfully."),
            Notification(severity=NotificationSeverity.WARNING,
                         event="market_data_stale",
                         message="Market data became stale. AI Auto paused."),
        ])
        await db.commit()
        tokens = {"customer": create_access_token(str(customer.id)),
                  "admin": create_access_token(str(admin.id))}

    async def override_db():
        async with Session() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        yield {"client": client, "tokens": tokens, "incident_id": inc.id,
               "Session": Session, "customer_id": customer.id}
    app.dependency_overrides.clear()
    await engine.dispose()


def _h(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.mark.asyncio
async def test_customer_cannot_read_notifications(env):
    for path in ("/api/admin/notifications", "/api/admin/incidents"):
        r = await env["client"].get(path, headers=_h(env["tokens"]["customer"]))
        assert r.status_code == 404, path


@pytest.mark.asyncio
async def test_customer_cannot_mark_notifications_read(env):
    r = await env["client"].post("/api/admin/notifications/read-all",
                                 headers=_h(env["tokens"]["customer"]))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_sees_notifications_with_unread_count(env):
    r = await env["client"].get("/api/admin/notifications",
                                headers=_h(env["tokens"]["admin"]))
    assert r.status_code == 200
    body = r.json()
    assert body["unread"] == 3
    assert len(body["notifications"]) == 3


@pytest.mark.asyncio
async def test_only_in_app_delivery_is_claimed(env):
    """Section 6: never claim an email or push was delivered."""
    r = await env["client"].get("/api/admin/notifications",
                                headers=_h(env["tokens"]["admin"]))
    body = r.json()
    assert body["channels"]["IN_APP"] == "ACTIVE"
    for channel in ("EMAIL", "PUSH", "SMS"):
        assert body["channels"][channel] == "NOT_CONFIGURED"
    for n in body["notifications"]:
        assert n["delivered_channels"] == []


@pytest.mark.asyncio
async def test_severity_filter(env):
    r = await env["client"].get("/api/admin/notifications?severity=CRITICAL",
                                headers=_h(env["tokens"]["admin"]))
    assert [n["severity"] for n in r.json()["notifications"]] == ["CRITICAL"]


@pytest.mark.asyncio
async def test_unknown_severity_is_rejected(env):
    r = await env["client"].get("/api/admin/notifications?severity=BANANA",
                                headers=_h(env["tokens"]["admin"]))
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_marking_one_read_leaves_the_others_unread(env):
    """Read state must be per row, not a global flag."""
    client, admin = env["client"], _h(env["tokens"]["admin"])
    first = (await client.get("/api/admin/notifications",
                              headers=admin)).json()["notifications"][0]
    await client.post(f"/api/admin/notifications/{first['id']}/read", headers=admin)
    body = (await client.get("/api/admin/notifications", headers=admin)).json()
    assert body["unread"] == 2
    read_flags = {n["id"]: n["read"] for n in body["notifications"]}
    assert read_flags[first["id"]] is True
    assert sum(1 for v in read_flags.values() if v) == 1


@pytest.mark.asyncio
async def test_unread_only_filter(env):
    client, admin = env["client"], _h(env["tokens"]["admin"])
    first = (await client.get("/api/admin/notifications",
                              headers=admin)).json()["notifications"][0]
    await client.post(f"/api/admin/notifications/{first['id']}/read", headers=admin)
    body = (await client.get("/api/admin/notifications?unread_only=true",
                             headers=admin)).json()
    assert all(n["read"] is False for n in body["notifications"])


@pytest.mark.asyncio
async def test_mark_all_read_is_idempotent(env):
    client, admin = env["client"], _h(env["tokens"]["admin"])
    first = await client.post("/api/admin/notifications/read-all", headers=admin)
    assert first.json()["marked"] == 3
    second = await client.post("/api/admin/notifications/read-all", headers=admin)
    assert second.json()["marked"] == 0


@pytest.mark.asyncio
async def test_notification_output_contains_no_secrets(env):
    r = await env["client"].get("/api/admin/notifications",
                                headers=_h(env["tokens"]["admin"]))
    blob = r.text.lower()
    for word in ("token", "password", "jwt", "postgresql://", "api_key",
                 "traceback"):
        assert word not in blob


@pytest.mark.asyncio
async def test_incident_filtering(env):
    client, admin = env["client"], _h(env["tokens"]["admin"])
    assert len((await client.get("/api/admin/incidents",
                                 headers=admin)).json()) == 1
    assert len((await client.get("/api/admin/incidents?status_filter=NEEDS_ADMIN",
                                 headers=admin)).json()) == 1
    assert len((await client.get("/api/admin/incidents?status_filter=RECOVERED",
                                 headers=admin)).json()) == 0


@pytest.mark.asyncio
async def test_incident_actions_only_name_allow_listed_operations(env):
    from app.services.recovery import Operation

    r = await env["client"].get("/api/admin/incidents",
                                headers=_h(env["tokens"]["admin"]))
    permitted = {op.value for op in Operation}
    for incident in r.json():
        for action in incident["actions"]:
            assert action["operation"] in permitted


@pytest.mark.asyncio
async def test_incident_output_contains_no_secrets(env):
    r = await env["client"].get("/api/admin/incidents",
                                headers=_h(env["tokens"]["admin"]))
    blob = r.text.lower()
    for word in ("token", "password", "jwt", "postgresql://", "traceback"):
        assert word not in blob


# ------------------------------------------------- customer-facing status


@pytest.mark.asyncio
async def test_customer_status_is_coarse_and_leaks_no_infrastructure(env):
    """Section 7: no Docker, container, port or host detail for customers."""
    r = await env["client"].get("/api/support/platform-status",
                                headers=_h(env["tokens"]["customer"]))
    assert r.status_code == 200
    blob = r.text.lower()
    for word in ("docker", "container", "port", "8100", "localhost", "127.0.0.1",
                 "token", "bridge", "postgres"):
        assert word not in blob, f"customer status leaked {word!r}"


@pytest.mark.asyncio
async def test_customer_status_explains_a_pause_in_plain_language(env):
    r = await env["client"].get("/api/support/platform-status",
                                headers=_h(env["tokens"]["customer"]))
    body = r.json()
    assert body["automated_trading"] in ("PAUSED", "ACTIVE")
    if body["automated_trading"] == "PAUSED":
        assert body["reasons"]
        assert body["banner"] == "AUTOMATED TRADING TEMPORARILY PAUSED"


# ------------------------------------------- control-centre summaries


@pytest.mark.asyncio
async def test_support_counts_are_real_not_placeholders(env):
    """These were hard-coded zeros before; they now count actual rows."""
    from app.models import (
        SupportTicket,
        TicketCategory,
        TicketPriority,
        TicketStatus,
    )

    client, admin = env["client"], _h(env["tokens"]["admin"])
    async with env["Session"]() as db:
        db.add_all([
            SupportTicket(user_id=env["customer_id"], category=TicketCategory.TRADING,
                          subject="a", description="a", ai_summary="",
                          safe_diagnostics={}, priority=TicketPriority.CRITICAL,
                          status=TicketStatus.NEEDS_ADMIN),
            SupportTicket(user_id=env["customer_id"], category=TicketCategory.BROKER,
                          subject="b", description="b", ai_summary="",
                          safe_diagnostics={}, priority=TicketPriority.NORMAL,
                          status=TicketStatus.OPEN),
            SupportTicket(user_id=env["customer_id"], category=TicketCategory.AI,
                          subject="c", description="c", ai_summary="",
                          safe_diagnostics={}, priority=TicketPriority.NORMAL,
                          status=TicketStatus.RESOLVED),
        ])
        await db.commit()

    body = (await client.get("/api/admin/control-centre", headers=admin)).json()
    assert body["support"]["needs_admin"] == 1
    assert body["support"]["open"] == 1
    assert body["support"]["resolved"] == 1
    assert body["support"]["urgent"] == 1


@pytest.mark.asyncio
async def test_incident_counts_are_real(env):
    body = (
        await env["client"].get("/api/admin/control-centre",
                                headers=_h(env["tokens"]["admin"]))
    ).json()
    assert body["incidents"]["needs_admin"] == 1
    assert body["incidents"]["recovered"] == 0


@pytest.mark.asyncio
async def test_bot_summary_pairs_each_gate_with_its_minimum(env):
    """Section 3: a waiting bot must read as waiting, not broken."""
    from app.models import Signal, SignalAction

    from sqlalchemy import select

    from app.models import RiskSettings

    client, admin = env["client"], _h(env["tokens"]["admin"])
    async with env["Session"]() as db:
        db.add(Signal(user_id=env["customer_id"], symbol="XAUUSD", action=SignalAction.NO_TRADE,
                      confidence=42, risk_reward=0.8, reason="structure unclear",
                      risk_approved=False, risk_reasons=["confidence below minimum"]))
        # Set explicitly, so this proves the panel reads the OWNER'S number
        # rather than happening to match whatever the model default is on
        # the day.
        owner = (await db.execute(select(RiskSettings).where(
            RiskSettings.user_id == env["customer_id"]))).scalar_one()
        owner.min_confidence = 66
        await db.commit()

    body = (await client.get("/api/admin/control-centre", headers=admin)).json()
    sig = body["bot"]["signal"]
    assert sig["action"] == "NO_TRADE"
    assert sig["confidence"] == 42
    assert sig["rr"] == 0.8
    # The minimums come from the signal owner's own risk settings.
    assert sig["required_confidence"] == 66
    assert sig["required_rr"] == 1.5
    assert sig["risk_reasons"] == ["confidence below minimum"]


@pytest.mark.asyncio
async def test_bot_summary_with_no_signal_reports_none(env):
    body = (
        await env["client"].get("/api/admin/control-centre",
                                headers=_h(env["tokens"]["admin"]))
    ).json()
    assert body["bot"]["signal"] is None
    assert body["bot"]["last_execution_error"] is None


@pytest.mark.asyncio
async def test_per_service_last_incident_is_reported(env):
    body = (
        await env["client"].get("/api/admin/control-centre",
                                headers=_h(env["tokens"]["admin"]))
    ).json()
    bridge = body["recovery"]["BRIDGE"]
    assert bridge["last_incident"] is not None
    assert bridge["last_incident"]["status"] == "NEEDS_ADMIN"
    assert body["recovery"]["FRONTEND"]["last_incident"] is None


@pytest.mark.asyncio
async def test_control_centre_exposes_no_secrets(env):
    r = await env["client"].get("/api/admin/control-centre",
                                headers=_h(env["tokens"]["admin"]))
    blob = r.text.lower()
    for word in ("token", "password", "jwt", "postgresql://", "api_key",
                 "traceback", "127.0.0.1"):
        assert word not in blob, f"control centre leaked {word!r}"


@pytest.mark.asyncio
async def test_customer_cannot_read_the_control_centre(env):
    r = await env["client"].get("/api/admin/control-centre",
                                headers=_h(env["tokens"]["customer"]))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_there_is_no_customer_route_to_any_notification(env):
    """Section 14: a customer must not reach a notification by any route.

    Checked by enumerating the app rather than by guessing paths, so a route
    added later without the gate fails this.
    """
    from app.deps import require_admin
    from app.main import app

    for route in app.routes:
        path = getattr(route, "path", "")
        if "notification" not in path:
            continue
        deps = set()
        dependant = getattr(route, "dependant", None)
        if dependant:
            stack = list(dependant.dependencies)
            while stack:
                d = stack.pop()
                deps.add(d.call)
                stack.extend(d.dependencies)
        assert require_admin in deps, f"{path} is not admin-gated"


@pytest.mark.asyncio
async def test_support_escalation_notifies_the_owner(env):
    """Section 7's SUPPORT notification, and it must not quote the customer."""
    from sqlalchemy import select

    client = env["client"]
    await client.post(
        "/api/support/ask",
        headers=_h(env["tokens"]["customer"]),
        json={"question": "unanswerable zzzq my secret passphrase is hunter2"},
    )
    async with env["Session"]() as db:
        rows = (await db.execute(select(Notification))).scalars().all()
    support_notes = [n for n in rows if n.event == "support_needs_admin"]
    assert support_notes, "escalation did not reach the notification centre"
    assert support_notes[0].severity is NotificationSeverity.HIGH
    # The customer's words are untrusted text; they belong in the ticket.
    assert "hunter2" not in support_notes[0].message
