"""Pydantic request/response models. All input is validated here."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .models import OrderStatus, SignalAction, TradingMode

# --------------------------------------------------------------------- auth


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    role: str
    is_active: bool
    #: Whether this account may use paid platform features. The frontend
    #: routes on it; the backend still enforces it independently on every
    #: gated route, so this is a UX hint and never the boundary.
    platform_access: bool = False
    #: Demo features specifically. Equal to platform_access today; a
    #: separate field so opening a free demo is a backend change alone.
    demo_access: bool = False


# ------------------------------------------------------------------ account


class AccountInfo(BaseModel):
    login: int
    server: str
    currency: str
    balance: float
    equity: float
    margin: float
    free_margin: float
    margin_level: float | None = None
    leverage: int
    # "demo" | "contest" | "real" — reported by the broker, not by us.
    trade_mode: str
    company: str = ""


class Tick(BaseModel):
    symbol: str
    bid: float
    ask: float
    spread_points: float
    time: datetime


class Position(BaseModel):
    ticket: int
    symbol: str
    type: Literal["BUY", "SELL"]
    volume: float
    price_open: float
    sl: float
    tp: float
    price_current: float
    profit: float
    swap: float = 0.0
    time: datetime
    comment: str = ""


class Deal(BaseModel):
    ticket: int
    order: int
    position_id: int
    entry: int
    symbol: str
    type: str
    volume: float
    price: float
    profit: float
    commission: float = 0.0
    swap: float = 0.0
    time: datetime
    comment: str = ""


# -------------------------------------------------------------------- risk


class RiskSettingsIn(BaseModel):
    """Every bound is clamped here as well as in the risk engine."""

    max_risk_per_trade_pct: float = Field(ge=0.01, le=5.0)
    max_daily_loss_pct: float = Field(ge=0.1, le=20.0)
    max_trades_per_day: int = Field(ge=1, le=50)
    max_open_positions: int = Field(ge=1, le=10)
    max_lot_size: float = Field(ge=0.01, le=10.0)
    min_confidence: int = Field(ge=0, le=100)
    min_rr: float = Field(ge=0.1, le=10.0)
    max_spread_points: int = Field(ge=1, le=1000)


class RiskSettingsOut(RiskSettingsIn):
    model_config = ConfigDict(from_attributes=True)
    trading_mode: TradingMode
    bot_enabled: bool
    bot_paused: bool = False
    emergency_stop: bool
    halted_until_date: str | None = None


class ModeChangeRequest(BaseModel):
    mode: TradingMode
    # Required verbatim when switching to REAL. See routers/risk.py.
    confirmation: str | None = None


class BotToggleRequest(BaseModel):
    enabled: bool


class BotPauseRequest(BaseModel):
    paused: bool


# ------------------------------------------------------------- ai analysis


class LevelZone(BaseModel):
    low: float
    high: float
    label: str = ""


class TimeframeView(BaseModel):
    timeframe: str
    trend: Literal["UP", "DOWN", "RANGE"]
    structure: str = ""
    support: list[float] = []
    resistance: list[float] = []
    breakout: str = "NONE"
    pullback: str = "NONE"
    liquidity: list[LevelZone] = []
    notes: str = ""


class AnalysisOut(BaseModel):
    symbol: str
    generated_at: datetime
    bias: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    summary: str
    timeframes: list[TimeframeView]
    entry_zones: list[LevelZone] = []
    warnings: list[str] = []


class SignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    symbol: str
    action: SignalAction
    entry: float | None
    stop_loss: float | None
    take_profit: float | None
    risk_reward: float | None
    confidence: int
    reason: str
    risk_approved: bool | None
    risk_reasons: list | None
    executed: bool


# ------------------------------------------------------------------ orders


class ManualOrderRequest(BaseModel):
    """A human accepting a signal. Still goes through the risk engine."""

    signal_id: int
    # Optional override; if omitted the engine sizes the position itself.
    volume: float | None = Field(default=None, ge=0.01, le=10.0)


class ClosePositionRequest(BaseModel):
    ticket: int


class OrderLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    mode: TradingMode
    symbol: str
    action: SignalAction
    volume: float
    entry: float | None
    stop_loss: float | None
    take_profit: float | None
    status: OrderStatus
    broker_ticket: int | None
    broker_retcode: int | None
    broker_comment: str | None


# --------------------------------------------------------------- dashboard


class BotStatus(BaseModel):
    bot_enabled: bool
    emergency_stop: bool
    trading_mode: TradingMode
    real_trading_allowed_by_server: bool
    bridge_connected: bool
    halted_today: bool
    trades_today: int
    pnl_today: float
    last_signal_at: datetime | None = None


class DashboardSnapshot(BaseModel):
    account: AccountInfo | None
    tick: Tick | None
    positions: list[Position]
    status: BotStatus
