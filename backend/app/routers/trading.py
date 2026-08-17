"""Trade execution endpoints.

Every route here delegates to `services.executor`, which runs the risk
engine before touching the broker. There is no route that sends an order
directly.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import current_user, get_risk_settings, rate_limit
from ..models import RiskSettings, Signal, SignalAction, User
from ..schemas import ClosePositionRequest, ManualOrderRequest
from ..services import executor

router = APIRouter(
    prefix="/api/trading", tags=["trading"], dependencies=[Depends(rate_limit)]
)


@router.post("/execute")
async def execute_signal(
    body: ManualOrderRequest,
    user: User = Depends(current_user),
    risk: RiskSettings = Depends(get_risk_settings),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Human accepts a signal. Still fully risk-checked and size-capped."""
    sig = await db.get(Signal, body.signal_id)
    if sig is None or sig.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Signal not found")
    if sig.executed:
        raise HTTPException(status.HTTP_409_CONFLICT, "Signal already executed")
    if sig.action == SignalAction.NO_TRADE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Signal is NO_TRADE — nothing to execute"
        )

    result = await executor.execute_signal(
        db,
        user_id=user.id,
        signal=sig,
        settings_row=risk,
        requested_volume=body.volume,
        initiated_by=f"user:{user.email}",
    )
    if not result.executed:
        # 200 with executed=false: a risk block is a normal, expected outcome
        # and the UI needs the reasons, not an exception.
        return result.as_dict()
    return result.as_dict()


@router.post("/close")
async def close_position(
    body: ClosePositionRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Close one position. Reducing exposure is never risk-blocked."""
    return await executor.close_position(
        db, user_id=user.id, ticket=body.ticket, reason=f"user:{user.email}"
    )


@router.post("/close-all")
async def close_all(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    results = await executor.close_all(
        db, user_id=user.id, reason=f"user:{user.email}"
    )
    return {"results": results}
