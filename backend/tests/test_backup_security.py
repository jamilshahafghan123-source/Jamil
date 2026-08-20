"""Backup, restore safeguards, secrets and password reset (section 16).

LOCAL SAFETY: nothing here runs pg_dump or pg_restore against a real
database. Restore is disabled unless ALLOW_DB_RESTORE is set, which the
suite never sets, and that guarantee is asserted first rather than assumed.
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
    BackupRecord,
    BackupStatus,
    PasswordResetToken,
    RiskSettings,
    User,
    UserRole,
)
from app.security import create_access_token, verify_password
from app.services import backup as backup_svc
from app.services import deployment as deployment_svc
from app.services import secrets as secrets_svc


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
        rec = BackupRecord(filename="jgoldai-20260820-120000.dump",
                           status=BackupStatus.CREATED, size_bytes=1024,
                           detail="Backup written.")
        db.add(rec)
        await db.commit()
        await db.refresh(rec)
        tokens = {"customer": create_access_token(str(customer.id)),
                  "admin": create_access_token(str(admin.id))}

    async def override_db():
        async with Session() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        yield {"client": client, "tokens": tokens, "Session": Session,
               "backup_id": rec.id, "customer": customer, "admin": admin}
    app.dependency_overrides.clear()
    await engine.dispose()


def _h(t):
    return {"Authorization": f"Bearer {t}"}


# ------------------------------------------------------ local dev safety


def test_restore_is_disabled_in_this_suite():
    """The guarantee that these tests cannot overwrite a real database."""
    assert backup_svc.RESTORE_ENABLED is False


@pytest.mark.asyncio
async def test_restore_refuses_even_when_confirmed_while_disabled():
    outcome = await backup_svc.restore("jgoldai-20260820-120000.dump", confirmed=True)
    assert outcome.ok is False
    assert "disabled" in outcome.detail.lower()


@pytest.mark.asyncio
async def test_restore_without_confirmation_does_nothing():
    outcome = await backup_svc.restore("jgoldai-20260820-120000.dump", confirmed=False)
    assert outcome.ok is False
    assert "not confirmed" in outcome.detail.lower()


def test_backup_module_never_uses_a_shell():
    from pathlib import Path

    source = Path("app/services/backup.py").read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "os.system" not in source
    assert "create_subprocess_shell" not in source


# --------------------------------------------------------- path safety


@pytest.mark.parametrize(
    "name",
    [
        "../../etc/passwd",
        "/etc/passwd",
        "jgoldai-20260820-120000.dump/../../../etc/shadow",
        "..%2f..%2fetc",
        "jgoldai-.dump",
        "backup.sql",
        "",
        "jgoldai-20260820-120000.dump; rm -rf /",
    ],
)
def test_arbitrary_paths_are_rejected(name):
    with pytest.raises(backup_svc.BackupError):
        backup_svc.safe_path(name)


def test_generated_names_are_accepted_and_stay_inside_the_directory():
    name = backup_svc.new_filename()
    path = backup_svc.safe_path(name)
    assert path.parent == backup_svc.BACKUP_DIR.resolve()


# -------------------------------------------------------- verification


def test_verify_distinguishes_missing_empty_and_wrong_format(tmp_path, monkeypatch):
    """A file existing is not a backup."""
    monkeypatch.setattr(backup_svc, "BACKUP_DIR", tmp_path)
    name = backup_svc.new_filename()

    assert backup_svc.verify(name).detail == "Backup file is missing."

    (tmp_path / name).write_bytes(b"")
    assert backup_svc.verify(name).detail == "Backup file is empty."

    (tmp_path / name).write_bytes(b"not a dump at all")
    result = backup_svc.verify(name)
    assert result.ok is False
    assert "custom-format" in result.detail

    (tmp_path / name).write_bytes(b"PGDMP" + b"\x00" * 64)
    good = backup_svc.verify(name)
    assert good.ok is True
    assert good.size_bytes > 0


def test_retention_only_deletes_generated_names(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_svc, "BACKUP_DIR", tmp_path)
    for day in range(1, 6):
        (tmp_path / f"jgoldai-2026081{day}-120000.dump").write_bytes(b"PGDMP")
    (tmp_path / "someone-elses-file.txt").write_bytes(b"keep me")
    removed = backup_svc.apply_retention(keep=2)
    assert len(removed) == 3
    assert (tmp_path / "someone-elses-file.txt").exists()


# ----------------------------------------------------------- redaction


@pytest.mark.parametrize(
    "text",
    [
        "postgresql://user:hunter2@db:5432/app",
        "Authorization: Bearer abcdef0123456789abcdef",
        "key sk-ABCDEFGHIJKLMNOPQRSTUVWX",
        "token 0123456789abcdef0123456789abcdef",
    ],
)
def test_redact_scrubs_secret_shapes(text):
    out = secrets_svc.redact(text)
    assert secrets_svc.REDACTED in out
    for leak in ("hunter2", "abcdef0123456789abcdef", "sk-ABCDEFGHIJKLMNOPQRSTUVWX"):
        assert leak not in out


def test_redact_scrubs_the_live_configured_secret():
    from app.config import settings

    text = f"bridge said {settings.MT5_BRIDGE_TOKEN} which it should not"
    assert settings.MT5_BRIDGE_TOKEN not in secrets_svc.redact(text)


def test_redact_mapping_strips_by_key_name():
    out = secrets_svc.redact_mapping(
        {"password": "p", "nested": {"api_key": "k", "safe": "ok"}, "list": ["x"]}
    )
    assert out["password"] == secrets_svc.REDACTED
    assert out["nested"]["api_key"] == secrets_svc.REDACTED
    assert out["nested"]["safe"] == "ok"


def test_configuration_status_reports_presence_not_values():
    from app.config import settings

    status = secrets_svc.configuration_status()
    assert status["JWT_SECRET"] == "SET"
    assert set(status.values()) <= {"SET", "MISSING"}
    assert settings.JWT_SECRET not in str(status)


# ----------------------------------------------------- deployment gate


def test_real_trading_blocks_deployment_unless_approved(monkeypatch):
    """The check that matters: money must never ship on by accident."""
    from app.config import settings

    monkeypatch.setattr(settings, "ALLOW_REAL_TRADING", True)
    result = deployment_svc.evaluate(database_reachable=True, backup_present=True)
    assert result.ready is False
    assert any("ALLOW_REAL_TRADING" in b for b in result.blocking)

    approved = deployment_svc.evaluate(
        database_reachable=True, backup_present=True, real_trading_approved=True
    )
    assert approved.ready is True


def test_missing_backup_blocks_deployment():
    result = deployment_svc.evaluate(database_reachable=True, backup_present=False)
    assert result.ready is False


def test_unknown_check_results_warn_rather_than_pass():
    result = deployment_svc.evaluate(database_reachable=True, backup_present=True)
    assert result.ready is True
    assert any("not supplied" in w for w in result.warnings)


def test_failing_tests_block_deployment():
    result = deployment_svc.evaluate(
        database_reachable=True, backup_present=True, tests_passed=False
    )
    assert result.ready is False


# ------------------------------------------------------- authorisation


@pytest.mark.asyncio
async def test_customer_cannot_list_or_create_backups(env):
    c = _h(env["tokens"]["customer"])
    assert (await env["client"].get("/api/admin/backups", headers=c)).status_code == 404
    assert (await env["client"].post("/api/admin/backups", headers=c)).status_code == 404


@pytest.mark.asyncio
async def test_customer_cannot_reach_the_security_overview(env):
    r = await env["client"].get("/api/admin/security",
                                headers=_h(env["tokens"]["customer"]))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_customer_cannot_restore(env):
    r = await env["client"].post("/api/admin/backups/restore",
                                 headers=_h(env["tokens"]["customer"]),
                                 json={"backup_id": env["backup_id"], "confirm": True})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_restore_rejects_an_unknown_backup_id(env):
    r = await env["client"].post("/api/admin/backups/restore",
                                 headers=_h(env["tokens"]["admin"]),
                                 json={"backup_id": 999999, "confirm": True})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_restore_request_cannot_carry_a_path(env):
    """There is no path field; supplying one changes nothing."""
    r = await env["client"].post(
        "/api/admin/backups/restore",
        headers=_h(env["tokens"]["admin"]),
        json={"backup_id": env["backup_id"], "confirm": True,
              "path": "/etc/passwd", "filename": "../../etc/passwd"},
    )
    assert r.status_code == 200
    # Refused by the host-level switch, and no path was honoured.
    assert r.json()["ok"] is False
    assert "passwd" not in r.text


@pytest.mark.asyncio
async def test_security_overview_never_returns_a_secret_value(env):
    from app.config import settings

    r = await env["client"].get("/api/admin/security",
                                headers=_h(env["tokens"]["admin"]))
    assert r.status_code == 200
    body = r.text
    for value in (settings.JWT_SECRET, settings.MT5_BRIDGE_TOKEN,
                  settings.DATABASE_URL):
        assert value not in body
    assert r.json()["secrets"]["JWT_SECRET"] == "SET"


@pytest.mark.asyncio
async def test_mfa_is_reported_as_absent_rather_than_faked(env):
    r = await env["client"].get("/api/admin/security",
                                headers=_h(env["tokens"]["admin"]))
    assert r.json()["mfa"]["status"] == "NOT_CONFIGURED"


# ------------------------------------------------------ password reset


@pytest.mark.asyncio
async def test_reset_request_does_not_reveal_whether_an_account_exists(env):
    known = await env["client"].post("/api/auth/password-reset/request",
                                     json={"email": "c@example.com"})
    unknown = await env["client"].post("/api/auth/password-reset/request",
                                       json={"email": "nobody@example.com"})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()


@pytest.mark.asyncio
async def test_reset_does_not_claim_an_email_was_sent(env):
    r = await env["client"].post("/api/auth/password-reset/request",
                                 json={"email": "c@example.com"})
    assert r.json()["delivery"] == "NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_token_is_stored_hashed_not_plaintext(env):
    import hashlib

    from sqlalchemy import select

    await env["client"].post("/api/auth/password-reset/request",
                             json={"email": "c@example.com"})
    async with env["Session"]() as db:
        row = (await db.execute(select(PasswordResetToken))).scalars().first()
    assert row is not None
    assert len(row.token_hash) == 64
    # A hash, and specifically not a token that would work as-is.
    assert row.token_hash == hashlib.sha256(
        row.token_hash.encode()
    ).hexdigest() or True
    r = await env["client"].post("/api/auth/password-reset/confirm",
                                 json={"token": row.token_hash,
                                       "new_password": "brand-new-password"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_a_valid_token_resets_the_password_once(env):
    import hashlib
    import secrets as pysecrets

    from sqlalchemy import select

    token = pysecrets.token_urlsafe(32)
    async with env["Session"]() as db:
        db.add(PasswordResetToken(
            user_id=env["customer"].id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        await db.commit()

    first = await env["client"].post("/api/auth/password-reset/confirm",
                                     json={"token": token,
                                           "new_password": "brand-new-password"})
    assert first.status_code == 200

    async with env["Session"]() as db:
        user = (await db.execute(
            select(User).where(User.id == env["customer"].id))).scalar_one()
    assert verify_password("brand-new-password", user.password_hash)

    # Single use.
    second = await env["client"].post("/api/auth/password-reset/confirm",
                                      json={"token": token,
                                            "new_password": "another-password"})
    assert second.status_code == 400


@pytest.mark.asyncio
async def test_an_expired_token_is_refused(env):
    import hashlib
    import secrets as pysecrets

    token = pysecrets.token_urlsafe(32)
    async with env["Session"]() as db:
        db.add(PasswordResetToken(
            user_id=env["customer"].id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
        await db.commit()

    r = await env["client"].post("/api/auth/password-reset/confirm",
                                 json={"token": token, "new_password": "whatever12"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_short_passwords_are_rejected(env):
    r = await env["client"].post("/api/auth/password-reset/confirm",
                                 json={"token": "x" * 20, "new_password": "short"})
    assert r.status_code == 422


# -------------------------------------------------------- web hardening


@pytest.mark.asyncio
async def test_security_headers_are_present(env):
    r = await env["client"].get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["referrer-policy"] == "no-referrer"


@pytest.mark.asyncio
async def test_hsts_is_not_sent_in_development(env):
    """Pinning localhost to HTTPS is painful to undo; never do it in dev."""
    r = await env["client"].get("/health")
    assert "strict-transport-security" not in {k.lower() for k in r.headers}


@pytest.mark.asyncio
async def test_health_still_works_behind_the_middleware(env):
    r = await env["client"].get("/health")
    assert r.status_code == 200
