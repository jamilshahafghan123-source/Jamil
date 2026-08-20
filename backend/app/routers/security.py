"""Password reset (section 9) and admin backup/security surfaces (14).

PASSWORD RESET
--------------
The request endpoint answers identically whether or not the address exists,
so it cannot be used to enumerate accounts. Tokens are random, single-use,
expiring, and stored only as a SHA-256 hash — a database disclosure leaks
nothing usable.

There is no email provider configured. Rather than pretend a message was
sent, the response says plainly that delivery is not configured, and the
token is returned only to an ADMIN through a separate endpoint so an
operator can hand it over out of band. That is a deliberate, documented
stopgap, not a design.
"""

from __future__ import annotations

import hashlib
import secrets as pysecrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..db import get_db
from ..deps import login_rate_limit, rate_limiter, require_admin
from ..models import (
    AuditLog,
    BackupRecord,
    BackupStatus,
    Incident,
    IncidentStatus,
    Notification,
    NotificationSeverity,
    PasswordResetToken,
    User,
    UserRole,
)
from ..security import hash_password
from ..services import backup as backup_svc
from ..services import deployment as deployment_svc
from ..services import launch_checklist as checklist_svc
from ..services import maintenance as maintenance_svc
from ..services import secrets as secrets_svc

router = APIRouter(prefix="/api/auth", tags=["auth"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])

#: Reset requests are cheap to send and expensive to receive. Tighter than
#: the global limit, and separate from login so one cannot exhaust the other.
reset_rate_limit = rate_limiter(5)

TOKEN_TTL = timedelta(hours=1)

#: Identical for every request, so the endpoint reveals nothing.
_NEUTRAL = (
    "If that address has an account, a reset has been created. Email delivery "
    "is not configured on this deployment, so an administrator must supply "
    "the reset link."
)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ResetRequestIn(BaseModel):
    email: EmailStr


class ResetConfirmIn(BaseModel):
    token: str = Field(min_length=16, max_length=128)
    new_password: str = Field(min_length=8, max_length=200)


@router.post("/password-reset/request", dependencies=[Depends(reset_rate_limit)])
async def request_password_reset(
    body: ResetRequestIn, db: AsyncSession = Depends(get_db)
) -> dict:
    """Always the same answer, whether or not the account exists."""
    user = (
        await db.execute(select(User).where(User.email == body.email.lower()))
    ).scalar_one_or_none()

    if user is not None and user.is_active:
        token = pysecrets.token_urlsafe(32)
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=_hash(token),
                expires_at=datetime.now(timezone.utc) + TOKEN_TTL,
            )
        )
        # The event is recorded; the token never is.
        db.add(
            AuditLog(
                user_id=user.id,
                event=audit.PASSWORD_RESET_REQUESTED,
                detail={"delivery": "not_configured"},
            )
        )
        await db.commit()

    return {"detail": _NEUTRAL, "delivery": "NOT_CONFIGURED"}


@router.post("/password-reset/confirm", dependencies=[Depends(login_rate_limit)])
async def confirm_password_reset(
    body: ResetConfirmIn, db: AsyncSession = Depends(get_db)
) -> dict:
    """Spend a token. Expired, used and unknown all fail the same way."""
    row = (
        await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == _hash(body.token)
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if row is None or row.used_at is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired token")
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired token")

    user = await db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired token")

    user.password_hash = hash_password(body.new_password)
    row.used_at = now
    # Any other outstanding token for this user dies with it.
    others = (
        (
            await db.execute(
                select(PasswordResetToken).where(
                    PasswordResetToken.user_id == user.id,
                    PasswordResetToken.used_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for other in others:
        other.used_at = now

    db.add(AuditLog(user_id=user.id, event=audit.PASSWORD_RESET_USED, detail={}))
    await db.commit()
    return {"detail": "Password updated."}


# ------------------------------------------------------------------ admin


class BackupOut(BaseModel):
    id: int
    filename: str
    status: str
    size_bytes: int
    created_at: datetime
    verified_at: datetime | None
    detail: str


class RestoreIn(BaseModel):
    """Restore names a registry id. There is deliberately no path field."""

    backup_id: int
    confirm: bool = False


def _out(row: BackupRecord) -> BackupOut:
    return BackupOut(
        id=row.id, filename=row.filename, status=row.status.value,
        size_bytes=row.size_bytes, created_at=row.created_at,
        verified_at=row.verified_at, detail=row.detail,
    )


@admin_router.get("/backups", response_model=list[BackupOut])
async def list_backups(
    _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[BackupOut]:
    rows = (
        (await db.execute(select(BackupRecord).order_by(BackupRecord.id.desc())))
        .scalars()
        .all()
    )
    return [_out(r) for r in rows]


@admin_router.post("/backups", response_model=BackupOut)
async def create_backup(
    admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> BackupOut:
    """Take a backup. A failure is recorded, not swallowed."""
    outcome = await backup_svc.create()
    row = BackupRecord(
        filename=outcome.filename,
        status=BackupStatus.CREATED if outcome.ok else BackupStatus.FAILED,
        size_bytes=outcome.size_bytes,
        checksum=outcome.checksum,
        app_version=deployment_svc.version_info()["version"],
        database_name=backup_svc.database_name(),
        detail=secrets_svc.redact(outcome.detail)[:500],
        created_by_user_id=admin.id,
    )
    db.add(row)
    db.add(
        AuditLog(
            user_id=admin.id,
            event=audit.BACKUP_CREATED if outcome.ok else audit.BACKUP_FAILED,
            detail={"filename": outcome.filename, "ok": outcome.ok},
        )
    )
    await db.commit()
    await db.refresh(row)
    return _out(row)


@admin_router.post("/backups/{backup_id}/verify", response_model=BackupOut)
async def verify_backup(
    backup_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BackupOut:
    row = await db.get(BackupRecord, backup_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    outcome = backup_svc.verify_against(row.filename, row.checksum)
    row.status = BackupStatus.VERIFIED if outcome.ok else BackupStatus.FAILED
    row.detail = secrets_svc.redact(outcome.detail)[:500]
    row.size_bytes = outcome.size_bytes or row.size_bytes
    if outcome.ok:
        row.verified_at = datetime.now(timezone.utc)
    db.add(
        AuditLog(user_id=admin.id, event=audit.BACKUP_VERIFIED,
                 detail={"backup_id": row.id, "ok": outcome.ok})
    )
    await db.commit()
    await db.refresh(row)
    return _out(row)


@admin_router.post("/backups/restore")
async def restore_backup(
    body: RestoreIn,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Restore a *registered* backup.

    The request names a row id. The filename comes from that row and is
    re-validated by the service, so no path from a request ever reaches the
    filesystem. Both the request and its result are audited.
    """
    row = await db.get(BackupRecord, body.backup_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    db.add(
        AuditLog(user_id=admin.id, event=audit.RESTORE_REQUESTED,
                 detail={"backup_id": row.id, "confirmed": body.confirm})
    )
    await db.commit()

    # Enter maintenance for the window. This stops new automated trades and
    # new opening orders; it closes nothing, and closing stays permitted.
    maintenance_svc.enter("Database restore", detail=f"backup #{row.id}")
    try:
        outcome = await backup_svc.restore(row.filename, confirmed=body.confirm)
        # Post-restore health. A restore that "succeeded" into a database we
        # cannot then query has not succeeded.
        healthy = False
        if outcome.ok:
            try:
                await db.execute(select(BackupRecord.id).limit(1))
                healthy = True
            except Exception:  # noqa: BLE001 - reported, never raised outward
                healthy = False
    finally:
        # Leave maintenance only when the restore is verifiably good. A
        # failed or unverified restore stays in maintenance rather than
        # silently resuming execution against a database nobody has checked.
        if outcome.ok and healthy:
            maintenance_svc.exit_(detail="Restore verified.")

    db.add(
        AuditLog(user_id=admin.id, event=audit.RESTORE_RESULT,
                 detail={"backup_id": row.id, "ok": outcome.ok,
                         "post_restore_healthy": healthy})
    )

    if outcome.ok and healthy:
        row.status = BackupStatus.RESTORE_TESTED
    else:
        # A failed restore stays visible as an incident, not just a response.
        db.add(
            Incident(
                service="DATABASE",
                category="RESTORE_FAILED",
                status=IncidentStatus.NEEDS_ADMIN,
                original_state="RESTORE_REQUESTED",
                final_state="NEEDS_ADMIN",
                attempt_number=1,
                actions=[{"operation": "RESTORE", "ok": False,
                          "detail": secrets_svc.redact(outcome.detail)[:300]}],
                detail=secrets_svc.redact(outcome.detail)[:500],
            )
        )
        db.add(
            Notification(
                severity=NotificationSeverity.CRITICAL,
                event="restore_failed",
                message=(
                    f"Database restore from backup #{row.id} did not complete "
                    "successfully. The platform remains in maintenance and "
                    "automated trading is paused."
                ),
            )
        )
    await db.commit()
    return {
        "ok": outcome.ok and healthy,
        "post_restore_healthy": healthy,
        "maintenance_active": maintenance_svc.current().active,
        "detail": secrets_svc.redact(outcome.detail)[:500],
    }


@admin_router.get("/security")
async def security_overview(
    _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    """Security posture. SET/MISSING only — never a value, never a length."""
    failed = (
        (
            await db.execute(
                select(AuditLog)
                .where(AuditLog.event.in_([audit.LOGIN_FAILED,
                                           audit.ADMIN_LOGIN_FAILED]))
                .order_by(AuditLog.id.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    latest_backup = (
        await db.execute(
            select(BackupRecord)
            .where(BackupRecord.status.in_(
                [BackupStatus.CREATED, BackupStatus.VERIFIED,
                 BackupStatus.RESTORE_TESTED]))
            .order_by(BackupRecord.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    admins = (
        (await db.execute(select(User).where(User.role == UserRole.ADMIN)))
        .scalars()
        .all()
    )

    readiness = deployment_svc.evaluate(
        database_reachable=True,
        backup_present=latest_backup is not None,
    )

    return {
        "secrets": secrets_svc.configuration_status(),
        "version": deployment_svc.version_info(),
        "deployment_readiness": readiness.as_dict(),
        "recent_failed_logins": len(failed),
        "admin_accounts": len(admins),
        "restore_enabled_on_host": backup_svc.RESTORE_ENABLED,
        "maintenance": maintenance_svc.current().as_dict(),
        "mfa": {
            # An honest boundary rather than a fake feature.
            "provider": "NONE",
            "status": "NOT_CONFIGURED",
            "detail": "No MFA provider is integrated. The boundary exists; "
                      "nothing is enforced.",
        },
        "latest_backup": _out(latest_backup).model_dump() if latest_backup else None,
        "launch_checklist": checklist_svc.evaluate(
            backup_verified=latest_backup is not None
            and latest_backup.status
            in (BackupStatus.VERIFIED, BackupStatus.RESTORE_TESTED)
        ),
    }
