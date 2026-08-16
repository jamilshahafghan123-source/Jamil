"""Error types shared by the MT5 layer and the HTTP layer."""

from __future__ import annotations

from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


class BridgeError(Exception):
    """Base class for errors that map onto a clean HTTP response."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "bridge_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code,
            content={
                "error": self.error_code,
                "message": self.message,
                # Details carry whatever the raising code had to hand — MT5
                # structures, timestamps, floats — so encode rather than trust
                # it to be JSON-native.
                "details": jsonable_encoder(self.details),
            },
        )


class TerminalUnavailableError(BridgeError):
    """The MetaTrader5 package or the terminal itself cannot be reached."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "terminal_unavailable"


class TerminalCallError(BridgeError):
    """A MetaTrader5 call returned an error (mt5.last_error())."""

    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = "terminal_call_failed"


class SymbolNotFoundError(BridgeError):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "symbol_not_found"


class NotFoundError(BridgeError):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"


class InvalidRequestError(BridgeError):
    # 422, matching FastAPI's own validation errors.
    status_code = 422
    error_code = "invalid_request"


class TradeRejectedError(BridgeError):
    """The terminal accepted the call but the server rejected the trade."""

    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "trade_rejected"


class TradingNotAllowedError(BridgeError):
    """Demo-account guard, volume cap, or terminal AutoTrading is off."""

    status_code = status.HTTP_403_FORBIDDEN
    error_code = "trading_not_allowed"


async def bridge_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, BridgeError)
    return exc.to_response()
