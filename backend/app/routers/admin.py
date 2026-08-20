"""ADMIN-only control centre (section 81).

Every route here depends on require_admin, which 404s a non-admin so that
probing tells a customer nothing.

A NOTE ON THE WIDER GAP, because it matters more than this router:
the existing trading and risk routes authorise on *authentication* alone.
The ADMIN/CUSTOMER distinction is currently enforced in the frontend only,
so a CUSTOMER's token can still reach /api/trading/* and /api/risk/*
directly. That is a behaviour change to make deliberately rather than as a
side effect of adding this router, so it is reported, not silently applied.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import require_admin
from ..models import (
    AuditLog,
    Incident,
    IncidentStatus,
    Notification,
    NotificationSeverity,
    RiskSettings,
    Subscription,
    SubscriptionStatus,
    User,
    UserRole,
)
from ..services import health as health_svc
from ..services import recovery as recovery_svc
from ..services import safe_mode as safe_mode_svc
from ..services.mt5_client import mt5

router = APIRouter(prefix="/api/admin", tags=["admin"])


class RecoveryActionIn(BaseModel):
    """An admin asking for one allow-listed operation.

    `operation` is validated against the Operation enum, so an unknown name
    or a shell string is a 400 before anything is dispatched. There is
    deliberately no field here that could carry a command.
    """

    operation: str


class RecoveryActionOut(BaseModel):
    operation: str
    ok: bool
    detail: str
    state: str


class SubscriptionIn(BaseModel):
    status: SubscriptionStatus
    plan: str | None = None
    #: Days from now the paid period ends. None leaves it open-ended.
    days: int | None = None


class SubscriptionOut(BaseModel):
    user_id: int
    status: str
    plan: str | None
    current_period_end: datetime | None


class EmergencyStopAllResult(BaseModel):
    stopped_accounts: int
    positions_closed: int
    detail: str


@router.get("/control-centre")
async def control_centre(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One read for the whole operator view. Never raises on a dead probe."""
    now = datetime.now(timezone.utc)

    bridge_connected = False
    bridge_authenticated = True
    last_tick_at: datetime | None = None
    try:
        bridge_connected = await mt5.connected()
    except Exception as exc:  # noqa: BLE001 - a probe must not 500 the page
        # 401/403 from the bridge means the token is wrong, not that it is
        # down; section 83 wants that surfaced as a credential problem.
        if "401" in str(exc) or "403" in str(exc):
            bridge_authenticated = False

    if bridge_connected:
        try:
            tick = await mt5.tick()
            raw = tick.get("time") if isinstance(tick, dict) else None
            if raw:
                last_tick_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001 - freshness simply stays unknown
            last_tick_at = None

    components = (
        health_svc.simple(health_svc.Component.BACKEND, True, up_detail="Serving.",
                          now=now),
        health_svc.simple(health_svc.Component.DATABASE, await _db_ok(db),
                          up_detail="Reachable.", down_detail="Query failed.", now=now),
        health_svc.bridge_health(
            connected=bridge_connected, authenticated=bridge_authenticated, now=now
        ),
        health_svc.simple(health_svc.Component.MT5, bridge_connected or None,
                          up_detail="Terminal reachable via bridge.", now=now),
        health_svc.market_data_health(last_tick_at, now=now),
        # Not yet wired; reported honestly rather than assumed healthy.
        health_svc.simple(health_svc.Component.AI_WORKERS, None, now=now),
        health_svc.ComponentHealth(
            health_svc.Component.PAYMENT_SERVICE,
            health_svc.ComponentStatus.NOT_CONFIGURED,
            "No payment provider connected.",
            now,
        ),
        health_svc.ComponentHealth(
            health_svc.Component.NOTIFICATION_SERVICE,
            health_svc.ComponentStatus.NOT_CONFIGURED,
            "No notification channel connected.",
            now,
        ),
    )
    system = health_svc.SystemHealth(components)

    safe = safe_mode_svc.evaluate(
        bridge_connected=bridge_connected,
        bridge_authenticated=bridge_authenticated,
        last_tick_at=last_tick_at,
        now=now,
        database_healthy=bool(await _db_ok(db)),
    )

    total_users = await db.scalar(select(func.count()).select_from(User)) or 0
    admins = (
        await db.scalar(
            select(func.count()).select_from(User).where(User.role == UserRole.ADMIN)
        )
        or 0
    )
    active = (
        await db.scalar(
            select(func.count()).select_from(User).where(User.is_active.is_(True))
        )
        or 0
    )
    bots_running = (
        await db.scalar(
            select(func.count())
            .select_from(RiskSettings)
            .where(RiskSettings.bot_enabled.is_(True))
        )
        or 0
    )
    stopped = (
        await db.scalar(
            select(func.count())
            .select_from(RiskSettings)
            .where(RiskSettings.emergency_stop.is_(True))
        )
        or 0
    )

    return {
        "generated_at": now.isoformat(),
        "system_health": system.as_dict(),
        "safe_mode": safe.as_dict(),
        "customers": {
            "total": total_users,
            "admins": admins,
            "customers": total_users - admins,
            "active": active,
        },
        "trading": {
            "bots_enabled": bots_running,
            "accounts_emergency_stopped": stopped,
            "real_trading_allowed_by_server": _real_allowed(),
        },
        # Present so the panel has a stable shape before the systems exist.
        "incidents": {"open": 0, "recovered": 0, "failed_recoveries": 0},
        "support": {"needs_admin": 0, "open": 0},
    }


@router.get("/recovery")
async def recovery_status(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Recovery panel: agent reachability, per-service state, history."""
    incidents = (
        (
            await db.execute(
                select(Incident).order_by(Incident.id.desc()).limit(20)
            )
        )
        .scalars()
        .all()
    )
    notes = (
        (
            await db.execute(
                select(Notification).order_by(Notification.id.desc()).limit(20)
            )
        )
        .scalars()
        .all()
    )
    return {
        "agent": {
            "configured": recovery_svc.agent.configured,
            # Never the URL or the token, only whether one is set.
            "status": "CONFIGURED" if recovery_svc.agent.configured else "OFFLINE",
        },
        "services": {
            s.value: {
                "state": recovery_svc.planner.state_of(s).value,
                "attempts_in_window": len(
                    recovery_svc.planner.record_for(s).recent(
                        datetime.now(timezone.utc)
                    )
                ),
                "has_automatic_repair": (
                    recovery_svc.POLICIES[s].repair is not None
                ),
                "policy": recovery_svc.POLICIES[s].description,
            }
            for s in recovery_svc.Service
        },
        "permitted_operations": [op.value for op in recovery_svc.Operation],
        "incidents": [
            {
                "id": i.id,
                "service": i.service,
                "category": i.category,
                "status": i.status.value,
                "detected_at": i.detected_at.isoformat() if i.detected_at else None,
                "recovered_at": (
                    i.recovered_at.isoformat() if i.recovered_at else None
                ),
                "attempt_number": i.attempt_number,
                "actions": i.actions or [],
                "final_state": i.final_state,
                "detail": i.detail,
            }
            for i in incidents
        ],
        "notifications": [
            {
                "id": n.id,
                "severity": n.severity.value,
                "event": n.event,
                "message": n.message,
                "created_at": n.created_at.isoformat() if n.created_at else None,
                "read_at": n.read_at.isoformat() if n.read_at else None,
                "delivered_channels": n.delivered_channels or [],
            }
            for n in notes
        ],
    }


@router.post("/recovery/run", response_model=RecoveryActionOut)
async def run_recovery_operation(
    body: RecoveryActionIn,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RecoveryActionOut:
    """Run one allow-listed operation, on an administrator's explicit request.

    This is the manual "CHECK NOW / RESTART BRIDGE" path. It is not a command
    box: the body names an operation from a closed enum and carries nothing
    else, so there is no string here that reaches a shell.
    """
    try:
        operation = recovery_svc.parse(body.operation)
    except recovery_svc.UnknownOperationError:
        # The rejected value is not echoed back.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Unknown recovery operation"
        ) from None

    result = await recovery_svc.agent.run(operation)

    incident = None
    if recovery_svc.is_mutating(operation):
        incident = Incident(
            service="MANUAL",
            category="ADMIN_REQUESTED",
            status=(
                IncidentStatus.RECOVERED if result.ok else IncidentStatus.FAILED
            ),
            original_state="",
            final_state="OK" if result.ok else "FAILED",
            attempt_number=1,
            actions=[result.as_dict()],
            detail=f"Requested by administrator {admin.email}.",
            recovered_at=datetime.now(timezone.utc) if result.ok else None,
        )
        db.add(incident)
        db.add(
            AuditLog(
                user_id=admin.id,
                event="admin_recovery_operation",
                detail={"operation": operation.value, "ok": result.ok},
            )
        )

    if result.auth_failure:
        db.add(
            Notification(
                severity=NotificationSeverity.CRITICAL,
                event="auth_failure",
                message=(
                    "The Windows recovery agent rejected the configured "
                    "credentials. Verification is required; no secret has "
                    "been changed."
                ),
            )
        )

    await db.commit()

    state = "NEEDS_ADMIN" if result.auth_failure else ("OK" if result.ok else "FAILED")
    return RecoveryActionOut(
        operation=operation.value, ok=result.ok, detail=result.detail, state=state
    )


@router.get("/notifications")
async def list_notifications(
    severity: str | None = None,
    unread_only: bool = False,
    limit: int = 100,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Owner notification centre.

    `delivered_channels` is returned as stored, which is empty for every row
    today: only IN_APP is real, and nothing here claims an email or push was
    sent when no provider is configured.
    """
    stmt = select(Notification).order_by(Notification.id.desc())
    if severity:
        try:
            stmt = stmt.where(Notification.severity == NotificationSeverity(severity))
        except ValueError:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Unknown severity"
            ) from None
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = (await db.execute(stmt.limit(min(limit, 200)))).scalars().all()

    unread = (
        await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.read_at.is_(None))
        )
        or 0
    )
    return {
        "unread": unread,
        "channels": {
            # The delivery abstraction. Only IN_APP is real; the rest are
            # declared so a future deliverer has a contract, and are
            # reported as unconfigured rather than silently pretended.
            "IN_APP": "ACTIVE",
            "EMAIL": "NOT_CONFIGURED",
            "PUSH": "NOT_CONFIGURED",
            "SMS": "NOT_CONFIGURED",
        },
        "notifications": [
            {
                "id": n.id,
                "severity": n.severity.value,
                "event": n.event,
                "message": n.message,
                "created_at": n.created_at.isoformat() if n.created_at else None,
                "read": n.read_at is not None,
                "incident_id": n.incident_id,
                "delivered_channels": n.delivered_channels or [],
            }
            for n in rows
        ],
    }


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.get(Notification, notification_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if row.read_at is None:
        row.read_at = datetime.now(timezone.utc)
        await db.commit()
    return {"id": row.id, "read": True}


@router.post("/notifications/read-all")
async def mark_all_notifications_read(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = (
        (
            await db.execute(
                select(Notification).where(Notification.read_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(timezone.utc)
    for row in rows:
        row.read_at = now
    await db.commit()
    return {"marked": len(rows)}


@router.get("/incidents")
async def list_incidents(
    status_filter: str | None = None,
    limit: int = 100,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    stmt = select(Incident).order_by(Incident.id.desc())
    if status_filter and status_filter != "ALL":
        try:
            stmt = stmt.where(Incident.status == IncidentStatus(status_filter))
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown status") from None
    rows = (await db.execute(stmt.limit(min(limit, 200)))).scalars().all()
    return [
        {
            "id": i.id,
            "service": i.service,
            "category": i.category,
            "status": i.status.value,
            "detected_at": i.detected_at.isoformat() if i.detected_at else None,
            "recovered_at": i.recovered_at.isoformat() if i.recovered_at else None,
            "attempt_number": i.attempt_number,
            "actions": i.actions or [],
            "final_state": i.final_state,
            "detail": i.detail,
        }
        for i in rows
    ]


@router.post("/emergency-stop-all", response_model=EmergencyStopAllResult)
async def emergency_stop_all(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> EmergencyStopAllResult:
    """Halt all automated trading, platform-wide.

    Section 81 is explicit that this must NOT delete existing positions, and
    it does not: it sets each account's emergency stop, which the risk engine
    and bot loop both refuse to trade through, and closes nothing. Open
    positions stay open and manageable. That is the difference between this
    and the per-user /api/risk/emergency-stop, which does close positions at
    its owner's request.
    """
    rows = (await db.execute(select(RiskSettings))).scalars().all()
    changed = 0
    for row in rows:
        if not row.emergency_stop:
            row.emergency_stop = True
            changed += 1
        row.bot_enabled = False

    db.add(
        AuditLog(
            user_id=admin.id,
            event="admin_emergency_stop_all",
            detail={
                "accounts_affected": len(rows),
                "accounts_newly_stopped": changed,
                "positions_closed": 0,
                "actor_email": admin.email,
            },
        )
    )
    await db.commit()

    return EmergencyStopAllResult(
        stopped_accounts=len(rows),
        positions_closed=0,
        detail=(
            "Automated trading halted on every account. Open positions were "
            "left untouched and can still be managed manually."
        ),
    )


@router.put("/subscriptions/{user_id}", response_model=SubscriptionOut)
async def set_subscription(
    user_id: int,
    body: SubscriptionIn,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionOut:
    """Set an account's entitlement by hand.

    No payment provider exists yet, so without this there is no way to grant
    access short of editing the database. It is an operator tool, not a
    billing system: it records no amount, takes no payment details, and when
    a provider is added that provider becomes the authority and this becomes
    a break-glass override.
    """
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    row = (
        await db.execute(select(Subscription).where(Subscription.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        row = Subscription(user_id=user_id)
        db.add(row)

    row.status = body.status
    row.plan = body.plan
    row.current_period_end = (
        datetime.now(timezone.utc) + timedelta(days=body.days) if body.days else None
    )

    db.add(
        AuditLog(
            user_id=admin.id,
            event="admin_subscription_set",
            detail={
                "target_user_id": user_id,
                "status": body.status.value,
                "plan": body.plan,
                "days": body.days,
            },
        )
    )
    await db.commit()
    await db.refresh(row)
    return SubscriptionOut(
        user_id=row.user_id,
        status=row.status.value,
        plan=row.plan,
        current_period_end=row.current_period_end,
    )


async def _db_ok(db: AsyncSession) -> bool | None:
    try:
        await db.execute(select(1))
        return True
    except Exception:  # noqa: BLE001 - reported as DOWN, not raised
        return False


def _real_allowed() -> bool:
    from ..config import get_settings

    return bool(get_settings().ALLOW_REAL_TRADING)
