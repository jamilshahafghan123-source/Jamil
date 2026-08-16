"""Liveness and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from ..config import Settings, get_settings
from ..dependencies import get_session
from ..errors import BridgeError
from ..mt5.session import MT5Session
from ..schemas import HealthResponse, ReadinessResponse
from ..security import require_api_key

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness probe (no auth)")
async def health() -> HealthResponse:
    from ..main import APP_NAME, APP_VERSION

    return HealthResponse(service=APP_NAME, version=APP_VERSION)


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    dependencies=[Depends(require_api_key)],
    summary="Terminal connectivity probe",
)
async def ready(
    response: Response,
    session: MT5Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ReadinessResponse:
    detail: str | None = None
    try:
        if not await session.ping():
            await session.connect()
    except BridgeError as exc:
        detail = exc.message

    if not session.connected:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        connected=session.connected,
        login=session.account_login,
        trade_mode=session.trade_mode_name,
        is_demo=session.is_demo,
        live_trading_allowed=settings.allow_live_trading,
        detail=detail,
    )
