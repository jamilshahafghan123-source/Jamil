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


class ExecutionVenue(str, enum.Enum):
    """Where an approved automated signal is sent.

    Two venues, and they never share an adapter. MT5_BRIDGE is the existing
    broker path; JGOLD_DEMO is the internal simulator that reaches no broker
    at all. Defaulting to MT5_BRIDGE keeps every existing account behaving
    exactly as it did before this column existed.
    """

    MT5_BRIDGE = "MT5_BRIDGE"
    JGOLD_DEMO = "JGOLD_DEMO"


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    CUSTOMER = "CUSTOMER"


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
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole), default=UserRole.CUSTOMER
    )
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

    #: Which execution adapter AI Auto uses. Defaults to the broker bridge,
    #: so existing accounts are unaffected by this column appearing.
    execution_venue: Mapped[ExecutionVenue] = mapped_column(
        Enum(ExecutionVenue), default=ExecutionVenue.MT5_BRIDGE
    )

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


class TicketCategory(str, enum.Enum):
    LOGIN = "LOGIN"
    ACCOUNT = "ACCOUNT"
    SUBSCRIPTION = "SUBSCRIPTION"
    PAYMENT = "PAYMENT"
    BROKER = "BROKER"
    DEPOSIT_WITHDRAW = "DEPOSIT_WITHDRAW"
    TRADING = "TRADING"
    DEMO = "DEMO"
    CHART = "CHART"
    AI = "AI"
    TECHNICAL = "TECHNICAL"
    SECURITY = "SECURITY"
    OTHER = "OTHER"


class TicketStatus(str, enum.Enum):
    OPEN = "OPEN"
    AI_HANDLING = "AI_HANDLING"
    NEEDS_ADMIN = "NEEDS_ADMIN"
    RESOLVED = "RESOLVED"


class TicketPriority(str, enum.Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SupportTicket(Base):
    """A support case. Owned by exactly one customer.

    `safe_diagnostics` is a JSON snapshot of the state the support worker
    could see when the ticket was raised — bot enabled, confidence against
    its minimum, broker reachability. It is written from the permission
    boundary's projections, which are built by allowlist, so a credential
    cannot reach this column even if one is added to a model later.
    """

    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    category: Mapped[TicketCategory] = mapped_column(
        Enum(TicketCategory), default=TicketCategory.OTHER, index=True
    )
    subject: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    ai_summary: Mapped[str] = mapped_column(Text, default="")
    safe_diagnostics: Mapped[dict] = mapped_column(JSON, default=dict)
    priority: Mapped[TicketPriority] = mapped_column(
        Enum(TicketPriority), default=TicketPriority.NORMAL, index=True
    )
    status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus), default=TicketStatus.OPEN, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    messages: Mapped[list[SupportMessage]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="SupportMessage.id"
    )


class SupportAuthor(str, enum.Enum):
    CUSTOMER = "CUSTOMER"
    SUPPORT_AI = "SUPPORT_AI"
    ADMIN = "ADMIN"


class SupportMessage(Base):
    """One turn of a support conversation.

    Customer text is stored verbatim as *data*. Nothing downstream parses it
    for instructions — see app/services/support/worker.py.
    """

    __tablename__ = "support_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("support_tickets.id"), index=True, nullable=False
    )
    author: Mapped[SupportAuthor] = mapped_column(Enum(SupportAuthor))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    ticket: Mapped[SupportTicket] = relationship(back_populates="messages")


class SubscriptionStatus(str, enum.Enum):
    """Entitlement states. No payment provider is connected yet, so every
    account starts at NONE and only an operator can move it."""

    NONE = "NONE"
    TRIAL = "TRIAL"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"


class Subscription(Base):
    """A customer's entitlement to paid platform features.

    Deliberately minimal: status, which plan it refers to, and when the
    paid period ends. There is no provider id, no amount and no payment
    method here, because no payment provider exists yet and modelling one
    speculatively would invite code that pretends to know things it does
    not. When a provider is added, it becomes the authority and this row
    becomes a cache of what it reports.

    ADMIN accounts never need a row: administrators bypass entitlement.
    """

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, index=True, nullable=False
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus), default=SubscriptionStatus.NONE, index=True
    )
    #: "weekly" | "monthly" | "yearly", or NULL when there is no plan.
    plan: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: End of the paid period. NULL means open-ended (e.g. a granted trial
    #: with no expiry). A past value revokes access even while the status
    #: still reads ACTIVE — see services/entitlements.py.
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class IncidentStatus(str, enum.Enum):
    OPEN = "OPEN"
    RECOVERING = "RECOVERING"
    RECOVERED = "RECOVERED"
    NEEDS_ADMIN = "NEEDS_ADMIN"
    FAILED = "FAILED"


class Incident(Base):
    """One detected service failure and what was done about it.

    `actions` is the ordered list of allow-listed operation names that were
    attempted, with their results. Because operations are enum constants,
    this column can only ever contain names from that enum — there is no
    shape in which a command string could be recorded here.
    """

    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    service: Mapped[str] = mapped_column(String(32), index=True)
    category: Mapped[str] = mapped_column(String(32))
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus), default=IncidentStatus.OPEN, index=True
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    recovered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    original_state: Mapped[str] = mapped_column(String(32), default="")
    final_state: Mapped[str] = mapped_column(String(32), default="")
    attempt_number: Mapped[int] = mapped_column(Integer, default=0)
    #: [{"operation": "RESTART_BRIDGE", "ok": true, "detail": "..."}]
    actions: Mapped[list] = mapped_column(JSON, default=list)
    admin_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    detail: Mapped[str] = mapped_column(Text, default="")


class NotificationSeverity(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Notification(Base):
    """An owner-facing event.

    Delivery today is the admin control centre reading this table. Channel
    fields exist so email or push can be added by writing a deliverer that
    consumes these rows — nothing here claims to have sent anything it has
    not, and `delivered_channels` stays empty until something real delivers.
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    severity: Mapped[NotificationSeverity] = mapped_column(
        Enum(NotificationSeverity), default=NotificationSeverity.INFO, index=True
    )
    event: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    incident_id: Mapped[int | None] = mapped_column(
        ForeignKey("incidents.id"), nullable=True, index=True
    )
    #: Channels that actually delivered it. Empty until a deliverer exists.
    delivered_channels: Mapped[list] = mapped_column(JSON, default=list)


class BackupStatus(str, enum.Enum):
    CREATED = "CREATED"
    FAILED = "FAILED"
    VERIFIED = "VERIFIED"
    RESTORE_TESTED = "RESTORE_TESTED"


class BackupRecord(Base):
    """Registry of database backups.

    THE REGISTRY IS THE POINT. Restore accepts a row id from this table and
    nothing else — never a filesystem path from a request, a customer, or a
    model. `filename` is generated server-side from a timestamp and is
    validated against a strict pattern before it is ever used, so a path
    cannot be smuggled in through a name.

    No connection string, password or host is recorded here: the metadata
    describes the artefact, not how to reach the database.
    """

    __tablename__ = "backup_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Basename only. No directory component is ever stored.
    filename: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    status: Mapped[BackupStatus] = mapped_column(
        Enum(BackupStatus), default=BackupStatus.CREATED, index=True
    )
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: SHA-256 of the artefact, so a later verification can prove the file
    #: is the same bytes that were written rather than merely present.
    checksum: Mapped[str] = mapped_column(String(64), default="")
    #: Which build produced it. A restore across versions is a decision, not
    #: an accident, so the version travels with the backup.
    app_version: Mapped[str] = mapped_column(String(64), default="unknown")
    #: Which database it came from. Never a DSN — name only.
    database_name: Mapped[str] = mapped_column(String(64), default="")
    #: Operator-facing. Never a command line, never a credential.
    detail: Mapped[str] = mapped_column(Text, default="")
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )


class PasswordResetToken(Base):
    """A single-use, expiring password reset grant.

    Only the SHA-256 of the token is stored. A database disclosure therefore
    leaks nothing usable: the plaintext exists only in the response to the
    request that created it, and is never logged.
    """

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    #: SHA-256 hex of the token. Never the token itself.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DemoPositionSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class TradeSource(str, enum.Enum):
    MANUAL = "MANUAL"
    AI_ASSIST = "AI_ASSIST"
    AI_AUTO = "AI_AUTO"


class DemoAccount(Base):
    """A J Gold AI internal demo account. Virtual money, never broker funds.

    This is NOT the MT5 demo account. Nothing here is ever sent to a broker,
    and the balance cannot be withdrawn because it does not exist anywhere
    but this row.
    """

    __tablename__ = "demo_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, index=True, nullable=False
    )
    starting_balance: Mapped[float] = mapped_column(Float, default=100000.0)
    balance: Mapped[float] = mapped_column(Float, default=100000.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DemoPosition(Base):
    """An open virtual position."""

    __tablename__ = "demo_positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("demo_accounts.id"), index=True, nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    side: Mapped[DemoPositionSide] = mapped_column(Enum(DemoPositionSide))
    volume: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[TradeSource] = mapped_column(
        Enum(TradeSource), default=TradeSource.MANUAL
    )
    #: Set when the position came from an AI signal, for the history panel.
    signal_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    signal_rr: Mapped[float | None] = mapped_column(Float, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class DemoTrade(Base):
    """A closed virtual trade. Append-only history."""

    __tablename__ = "demo_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("demo_accounts.id"), index=True, nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    side: Mapped[DemoPositionSide] = mapped_column(Enum(DemoPositionSide))
    volume: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float] = mapped_column(Float)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[TradeSource] = mapped_column(
        Enum(TradeSource), default=TradeSource.MANUAL
    )
    #: MANUAL_CLOSE | STOP_LOSS | TAKE_PROFIT | RESET
    close_reason: Mapped[str] = mapped_column(String(32), default="MANUAL_CLOSE")
    signal_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    signal_rr: Mapped[float | None] = mapped_column(Float, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class ChartDrawing(Base):
    """A customer's own chart annotation.

    Scoped to user, symbol and timeframe together: a trend line drawn on
    XAUUSD M15 belongs on XAUUSD M15 and nowhere else, so the scope is part
    of the row rather than something the client filters after loading.

    `payload` holds the shape's geometry as the client understands it —
    price and time coordinates, never pixels, so a drawing survives a
    different screen size. It is opaque to the backend by design: the
    backend's job here is ownership and scoping, not geometry.

    These are the customer's own work and are stored entirely separately
    from AI overlays, which are derived from analysis and never persisted.
    """

    __tablename__ = "chart_drawings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), index=True)
    #: TREND_LINE | HORIZONTAL | VERTICAL | RECTANGLE | ARROW | TEXT |
    #: RULER | LONG_POSITION | SHORT_POSITION
    kind: Mapped[str] = mapped_column(String(24))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class StrategyActionMode(str, enum.Enum):
    """Mirrors services.strategy.ActionMode.

    REAL_AUTO is absent here too: a value the column cannot hold is a
    value no row can carry, whatever a future caller tries to store.
    """

    ALERT_ONLY = "ALERT_ONLY"
    AI_ASSIST = "AI_ASSIST"
    DEMO_AUTO = "DEMO_AUTO"


class Strategy(Base):
    """A customer's saved strategy (section 36).

    `rule` holds the validated condition tree as JSON. It is DATA, not
    code: it is parsed back through services.strategy on every read, so a
    row edited directly in the database still cannot introduce anything
    outside the closed vocabulary.
    """

    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(80))
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    direction: Mapped[str] = mapped_column(String(8))
    action_mode: Mapped[StrategyActionMode] = mapped_column(
        Enum(StrategyActionMode), default=StrategyActionMode.ALERT_ONLY
    )
    rule: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
