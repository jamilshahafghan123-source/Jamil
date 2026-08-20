"""Recovery endpoints and local-development safety (sections 10, 13, 14).

LOCAL SAFETY: no test in this file can restart anything on a real machine.
The agent is unconfigured throughout the suite, and `run` returns
"unavailable" before opening a socket — asserted directly below rather than
assumed.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base, get_db
from app.main import app
from app.models import RiskSettings, User, UserRole
from app.security import create_access_token
from app.services.recovery import Operation, agent
from app.services.recovery.agent import WindowsAgent


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
        await db.commit()
        tokens = {"customer": create_access_token(str(customer.id)),
                  "admin": create_access_token(str(admin.id))}

    async def override_db():
        async with Session() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        yield {"client": client, "tokens": tokens, "Session": Session}
    app.dependency_overrides.clear()
    await engine.dispose()


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


# ----------------------------------------------------- local dev safety


@pytest.mark.asyncio
async def test_agent_is_inert_in_tests():
    """The guarantee that this suite cannot touch the developer's machine."""
    assert agent.configured is False
    result = await agent.run(Operation.RESTART_BRIDGE)
    assert result.unavailable is True
    assert result.ok is False


@pytest.mark.asyncio
async def test_unconfigured_agent_reports_unavailable_not_failure():
    """Not configured is not broken: it must not manufacture incidents."""
    for op in Operation:
        result = await WindowsAgent(base_url="", token="").run(op)
        assert result.unavailable is True


def test_no_module_in_the_package_can_run_a_shell():
    """A structural check: nothing here imports a process-spawning API."""
    import pathlib

    banned = ("subprocess", "os.system", "os.popen", "pty.spawn",
              "shutil.which", "eval(", "exec(")
    for path in pathlib.Path("app/services/recovery").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for word in banned:
            assert word not in source, f"{path.name} references {word!r}"


# ------------------------------------------------------- authorisation


@pytest.mark.asyncio
async def test_unauthenticated_cannot_reach_recovery(env):
    for path in ("/api/admin/recovery", "/api/admin/recovery/run"):
        r = await env["client"].get(path)
        assert r.status_code in (401, 405)


@pytest.mark.asyncio
async def test_customer_cannot_read_recovery_status(env):
    r = await env["client"].get("/api/admin/recovery",
                                headers=_hdr(env["tokens"]["customer"]))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_customer_cannot_trigger_a_restart(env):
    r = await env["client"].post("/api/admin/recovery/run",
                                 headers=_hdr(env["tokens"]["customer"]),
                                 json={"operation": "RESTART_BRIDGE"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_can_read_recovery_status(env):
    r = await env["client"].get("/api/admin/recovery",
                                headers=_hdr(env["tokens"]["admin"]))
    assert r.status_code == 200
    body = r.json()
    assert body["agent"]["configured"] is False
    assert set(body["permitted_operations"]) == {op.value for op in Operation}


@pytest.mark.asyncio
async def test_admin_can_request_an_allow_listed_operation(env):
    r = await env["client"].post("/api/admin/recovery/run",
                                 headers=_hdr(env["tokens"]["admin"]),
                                 json={"operation": "CHECK_BRIDGE"})
    assert r.status_code == 200
    # Unconfigured agent, so it reports failure rather than pretending.
    assert r.json()["ok"] is False


@pytest.mark.parametrize(
    "payload",
    [
        "powershell -c Stop-Computer",
        "docker restart backend; rm -rf /",
        "RESTART_BRIDGE && curl evil.example.com",
        "run_command",
        "",
        "restart_bridge",
    ],
)
@pytest.mark.asyncio
async def test_admin_cannot_smuggle_a_command_string(env, payload):
    """Even the owner has no free-form command box."""
    r = await env["client"].post("/api/admin/recovery/run",
                                 headers=_hdr(env["tokens"]["admin"]),
                                 json={"operation": payload})
    assert r.status_code in (400, 422)
    # The empty string is trivially a substring of anything, so the
    # echo check only means something for a non-empty payload.
    if payload:
        assert payload not in r.text


@pytest.mark.asyncio
async def test_rejection_does_not_echo_the_rejected_value(env):
    r = await env["client"].post("/api/admin/recovery/run",
                                 headers=_hdr(env["tokens"]["admin"]),
                                 json={"operation": "canary-9f3a"})
    assert "canary-9f3a" not in r.text


# ------------------------------------------------------- no secrets out


@pytest.mark.asyncio
async def test_recovery_status_exposes_no_secret(env):
    r = await env["client"].get("/api/admin/recovery",
                                headers=_hdr(env["tokens"]["admin"]))
    blob = r.text.lower()
    for word in ("token", "password", "jwt", "secret", "postgresql://",
                 "api_key", "bridge_token"):
        assert word not in blob, f"recovery status leaked {word!r}"


@pytest.mark.asyncio
async def test_agent_url_is_never_returned(env):
    """Only whether an agent is configured, never where it lives."""
    r = await env["client"].get("/api/admin/recovery",
                                headers=_hdr(env["tokens"]["admin"]))
    assert "url" not in r.json()["agent"]


def test_agent_token_is_a_separate_setting_from_the_bridge_token():
    """Section 3: rotating one must not touch the other."""
    from app.config import Settings

    fields = Settings.model_fields
    assert "WINDOWS_AGENT_TOKEN" in fields
    assert "MT5_BRIDGE_TOKEN" in fields
    assert fields["WINDOWS_AGENT_TOKEN"].default is None


# ------------------------------------------------- support AI separation


def test_support_ai_holds_no_recovery_capability():
    """Section 11: support may read and explain, never invoke recovery."""
    from app.services.support import worker
    from app.services.workers import Capability, GRANTS

    caps = GRANTS[worker.ROLE].capabilities
    assert caps == {Capability.READ, Capability.RECOMMEND}


def test_support_package_cannot_reach_the_agent():
    """Structural: the support worker does not import recovery at all."""
    import pathlib

    for path in pathlib.Path("app/services/support").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "recovery" not in source
        assert "RESTART" not in source


# ---------------------------------------------------- unchanged promises


def test_real_trading_remains_disabled():
    from app.config import get_settings

    assert get_settings().ALLOW_REAL_TRADING is False


def test_recovery_never_touches_the_executor_or_risk_engine():
    import pathlib

    for path in pathlib.Path("app/services/recovery").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "executor" not in source
        assert "risk_engine" not in source
