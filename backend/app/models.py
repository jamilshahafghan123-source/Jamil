"""Database models.

Design note: `AuditLog` and `OrderLog` are append-only. Every trading
decision writes an audit row *before* anything is sent to the broker, and
every order request writes an order row with both the request and the
broker's response. That pair is the forensic record.
"""

from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TradingMode(str, enum.Enum):
    MANUAL = "MANUAL"  # AI produces signals; a human places the trade.
    DEMO = "DEMO"  # AI auto-executes, demo account only.
    REAL = "REAL"  # AI auto-executes on a live account. Gated hard.


class SignalAction(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"
    NO_TRADE = "NO_TRADE"


class OrderStatus(str, enum.Enum):
    REQUESTED = "REQUESTED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    settings: Mapped[RiskSettings | None] = relationship(
        back_populates="user", uselist=False
    )


class RiskSettings(Base):
    """Per-user risk envelope. The risk engine reads only from here."""

    __tablename__ = "risk_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)

    # Mode & kill switch
    trading_mode: Mapped[TradingMode] = mapped_column(
        Enum(TradingMode), default=TradingMode.MANUAL
    )
    bot_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    emergency_stop: Mapped[bool] = mapped_column(Boolean, default=False)

    # Risk envelope
    max_risk_per_trade_pct: Mapped[float] = mapped_column(Float, default=0.5)
    max_daily_loss_pct: Mapped[float] = mapped_column(Float, default=2.0)
    max_trades_per_day: Mapped[int] = mapped_column(Integer, default=5)
    max_open_positions: Mapped[int] = mapped_column(Integer, default=1)
    max_lot_size: Mapped[float] = mapped_column(Float, default=0.10)

    # Signal quality / execution filters
    min_confidence: Mapped[int] = mapped_column(Integer, default=70)
    min_rr: Mapped[float] = mapped_column(Float, default=1.5)
    max_spread_points: Mapped[int] = mapped_column(Integer, default=50)

    # Set when the daily loss limit trips; cleared at the next UTC day roll.
    halted_until_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="settings")


class Signal(Base):
    """An AI analysis result. Producing one never moves money."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    symbol: Mapped[str] = mapped_column(String(24))
    action: Mapped[SignalAction] = mapped_column(Enum(SignalAction))
    entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_reward: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(Text, default="")

    # Deterministic market snapshot the AI was given, plus its full response.
    market_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)

    # Filled in once the risk engine has ruled on it.
    risk_approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    risk_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    executed: Mapped[bool] = mapped_column(Boolean, default=False)


class OrderLog(Base):
    """Every order request and its broker response. Append-only."""

    __tablename__ = "order_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    signal_id: Mapped[int | None] = mapped_column(
        ForeignKey("signals.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    mode: Mapped[TradingMode] = mapped_column(Enum(TradingMode))
    symbol: Mapped[str] = mapped_column(String(24))
    action: Mapped[SignalAction] = mapped_column(Enum(SignalAction))
    volume: Mapped[float] = mapped_column(Float)
    entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus))
    broker_ticket: Mapped[int | None] = mapped_column(Integer, nullable=True)
    broker_retcode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    broker_comment: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    response_payload: Mapped[dict] = mapped_column(JSON, default=dict)


class AuditLog(Base):
    """Append-only trail of every decision point in the pipeline."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    event: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class DailyStat(Base):
    """Per-user, per-UTC-day counters the risk engine enforces against."""

    __tablename__ = "daily_stats"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_daily_user_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    trades_opened: Mapped[int] = mapped_column(Integer, default=0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    start_balance: Mapped[float] = mapped_column(Float, default=0.0)
