"""Request/response models for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Timeframe = Literal[
    "M1", "M2", "M3", "M4", "M5", "M6", "M10", "M12", "M15", "M20", "M30",
    "H1", "H2", "H3", "H4", "H6", "H8", "H12",
    "D1", "W1", "MN1",
]
Side = Literal["buy", "sell"]
OrderKind = Literal["market", "limit", "stop", "stop_limit"]
TimeInForce = Literal["gtc", "day", "specified", "specified_day"]
Filling = Literal["fok", "ioc", "return"]


class Passthrough(BaseModel):
    """Base for payloads mirroring MT5 structures, which differ between brokers/builds."""

    model_config = ConfigDict(extra="allow")


# --- health -------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    version: str


class ReadinessResponse(BaseModel):
    connected: bool
    login: int | None = None
    trade_mode: str | None = None
    is_demo: bool = False
    live_trading_allowed: bool = False
    detail: str | None = None


# --- market data --------------------------------------------------------------


class Candle(BaseModel):
    time: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: int
    spread: int
    real_volume: int


class CandlesResponse(BaseModel):
    symbol: str
    timeframe: Timeframe
    count: int
    candles: list[Candle]


class SymbolSummary(BaseModel):
    name: str
    description: str = ""
    path: str = ""
    digits: int
    point: float
    spread: int = 0
    trade_mode: int = 0
    volume_min: float = 0.0
    volume_max: float = 0.0
    volume_step: float = 0.0
    visible: bool = False


class TickResponse(Passthrough):
    symbol: str
    bid: float
    ask: float
    last: float | None = None


class AccountResponse(Passthrough):
    login: int
    balance: float
    equity: float
    margin_free: float
    currency: str
    leverage: int
    trade_mode_name: str | None = None
    is_demo: bool = False


# --- trading ------------------------------------------------------------------


class OrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(..., examples=["EURUSD"])
    side: Side
    volume: float = Field(..., gt=0, description="Lots. Snapped to the symbol's volume step.")
    type: OrderKind = "market"

    price: float | None = Field(
        default=None, gt=0, description="Required for pending orders; ignored for market orders."
    )
    stop_limit_price: float | None = Field(
        default=None, gt=0, description="Limit price triggered by a stop_limit order."
    )
    sl: float | None = Field(default=None, ge=0, description="Stop loss price. 0 clears it.")
    tp: float | None = Field(default=None, ge=0, description="Take profit price. 0 clears it.")

    deviation: int | None = Field(default=None, ge=0, description="Max slippage in points.")
    magic: int | None = Field(default=None, ge=0)
    comment: str | None = Field(default=None, max_length=24)
    type_time: TimeInForce = "gtc"
    expiration: datetime | None = None
    filling: Filling | None = Field(
        default=None, description="Defaults to the symbol's supported mode (FOK, else IOC)."
    )
    dry_run: bool = Field(
        default=False, description="Validate via order_check without sending the order."
    )

    @model_validator(mode="after")
    def _check_shape(self) -> "OrderRequest":
        if self.type == "market":
            if self.price is not None:
                raise ValueError("'price' is not accepted for market orders.")
        elif self.price is None:
            raise ValueError(f"'price' is required for {self.type} orders.")

        if self.type == "stop_limit" and self.stop_limit_price is None:
            raise ValueError("'stop_limit_price' is required for stop_limit orders.")
        if self.type != "stop_limit" and self.stop_limit_price is not None:
            raise ValueError("'stop_limit_price' is only valid for stop_limit orders.")

        if self.type_time in ("specified", "specified_day") and self.expiration is None:
            raise ValueError("'expiration' is required when type_time is 'specified'.")
        if self.type == "market" and self.type_time != "gtc":
            raise ValueError("'type_time' only applies to pending orders.")
        return self


class ClosePositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    volume: float | None = Field(
        default=None, gt=0, description="Partial close volume. Defaults to the whole position."
    )
    deviation: int | None = Field(default=None, ge=0)
    comment: str | None = Field(default=None, max_length=24)


class ModifyPositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sl: float | None = Field(default=None, ge=0, description="New stop loss. 0 removes it.")
    tp: float | None = Field(default=None, ge=0, description="New take profit. 0 removes it.")


class TradeResult(Passthrough):
    retcode: int
    retcode_description: str
    success: bool
    order: int | None = None
    deal: int | None = None
    volume: float | None = None
    price: float | None = None
    comment: str | None = None
    dry_run: bool = False
    sent_request: dict[str, Any] | None = None
    risk: dict[str, Any] | None = None


class Position(Passthrough):
    ticket: int
    symbol: str
    side: str
    volume: float
    price_open: float
    sl: float = 0.0
    tp: float = 0.0
    price_current: float = 0.0
    profit: float = 0.0
    time: datetime | None = None


class PendingOrder(Passthrough):
    ticket: int
    symbol: str
    volume_current: float | None = None
    price_open: float | None = None
    type: int | None = None
    time_setup: datetime | None = None


class Deal(Passthrough):
    ticket: int
    symbol: str = ""
    volume: float = 0.0
    price: float = 0.0
    profit: float = 0.0
    time: datetime | None = None
