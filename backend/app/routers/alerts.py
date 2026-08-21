"""Customer alerts (section 62).

In-app delivery only. There is no channel parameter to set and no
provider to configure, because none is connected — see services.alerts.

Ownership is enforced in the query, and a foreign alert returns the same
404 as a missing one.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import current_user, rate_limit, require_platform_access
from ..models import Alert, AlertKind, User
from ..services import alerts as engine

router = APIRouter(
    prefix="/api/alerts",
    tags=["alerts"],
    dependencies=[Depends(rate_limit), Depends(require_platform_access)],
)

MAX_PER_USER = 60


class AlertIn(BaseModel):
    kind: str
    symbol: str = Field(min_length=1, max_length=24)
    threshold: float | None = None
    session: str | None = Field(default=None, max_length=16)
    note: str = Field(default="", max_length=200)
    repeatable: bool = False
    enabled: bool = True


def _out(row: Alert) -> dict:
    return {
        "id": row.id,
        "kind": row.kind.value,
        "label": engine.KIND_LABEL.get(row.kind, row.kind.value),
        "symbol": row.symbol,
        "threshold": row.threshold,
        "session": row.session,
        "note": row.note,
        "enabled": row.enabled,
        "repeatable": row.repeatable,
        "triggered_at": row.triggered_at.isoformat() if row.triggered_at else None,
        "trigger_count": row.trigger_count,
        "last_message": row.last_message,
        "acknowledged": row.acknowledged,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/kinds")
async def alert_kinds(_user: User = Depends(current_user)) -> dict:
    """What can be watched, and what each kind needs to be complete."""
    return {
        "kinds": [
            {
                "kind": kind.value,
                "label": engine.KIND_LABEL.get(kind, kind.value),
                "needs_threshold": kind in engine.NEEDS_THRESHOLD,
                "needs_session": kind in engine.NEEDS_SESSION,
            }
            for kind in AlertKind
        ],
        "delivery": "IN_APP",
        "delivery_note": (
            "Alerts appear inside J Gold AI. Email, SMS and push are not "
            "connected, so they are not offered — an alert you believed "
            "would reach your phone and did not would be worse than none."
        ),
    }


@router.get("")
async def list_alerts(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = (
        await db.execute(
            select(Alert)
            .where(Alert.user_id == user.id)
            .order_by(Alert.created_at.desc())
        )
    ).scalars().all()
    rows = list(rows)
    return {
        "alerts": [_out(r) for r in rows],
        "unacknowledged": sum(1 for r in rows if not r.acknowledged),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_alert(
    body: AlertIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        kind = AlertKind(body.kind.upper())
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Unknown alert type {body.kind!r}."
        ) from None

    # An alert missing what it needs could never fire; refusing it beats
    # storing something that silently never works.
    if kind in engine.NEEDS_THRESHOLD and body.threshold is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{engine.KIND_LABEL[kind]} needs a level.",
        )
    if kind in engine.NEEDS_SESSION and not body.session:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{engine.KIND_LABEL[kind]} needs a session.",
        )

    existing = (
        await db.execute(select(Alert.id).where(Alert.user_id == user.id))
    ).scalars().all()
    if len(existing) >= MAX_PER_USER:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"You already have {MAX_PER_USER} alerts. Delete one first.",
        )

    row = Alert(
        user_id=user.id, kind=kind, symbol=body.symbol.upper(),
        threshold=body.threshold,
        session=body.session.upper() if body.session else None,
        note=body.note, repeatable=body.repeatable, enabled=body.enabled,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.post("/{alert_id}/enabled")
async def set_enabled(
    alert_id: int,
    enabled: bool,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (
        await db.execute(
            select(Alert).where(Alert.id == alert_id, Alert.user_id == user.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    row.enabled = enabled
    # Re-enabling a fired one-shot alert arms it again, which is what a
    # customer means when they switch it back on.
    if enabled and not row.repeatable:
        row.trigger_count = 0
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.post("/{alert_id}/acknowledge")
async def acknowledge(
    alert_id: int,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (
        await db.execute(
            select(Alert).where(Alert.id == alert_id, Alert.user_id == user.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    row.acknowledged = True
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.delete("/{alert_id}")
async def delete_alert(
    alert_id: int,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        delete(Alert).where(Alert.id == alert_id, Alert.user_id == user.id)
    )
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    return {"deleted": alert_id}


async def fire(db: AsyncSession, row: Alert, message: str) -> None:
    """Mark an alert as fired. The only place that writes trigger state."""
    row.triggered_at = datetime.now(timezone.utc)
    row.trigger_count += 1
    row.last_message = message
    row.acknowledged = False
    await db.commit()
