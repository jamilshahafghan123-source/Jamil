"""AI worker permission boundary.

Sections 75-76 of the platform brief: least-privilege data access, and a
hard separation between READ / RECOMMEND / WRITE / FINANCIAL.

Import from here rather than from the submodules, so the boundary has one
public surface:

    from app.services.workers import WorkerRole, authorize, project_trading_status

No AI worker lives in this package yet. This is the floor they will stand
on — built first so that adding one cannot quietly widen what it can reach.
"""

from .capabilities import (
    Capability,
    DataScope,
    Grant,
    GRANTS,
    PermissionDeniedError,
    WorkerRole,
    grant_for,
    has_capability,
    has_scope,
    require_capability,
    require_scope,
)
from .context import (
    AccountProfile,
    BrokerConnectivity,
    RiskEnvelope,
    TradingStatus,
    project_account_profile,
    project_broker_connectivity,
    project_risk_envelope,
    project_trading_status,
)
from .guard import UnsafeInstructionError, authorize, authorize_all
from .intents import (
    EscalateToAdmin,
    Explanation,
    Intent,
    ProposeSettingChange,
    ProposeTrade,
)

__all__ = [
    "AccountProfile",
    "BrokerConnectivity",
    "Capability",
    "DataScope",
    "EscalateToAdmin",
    "Explanation",
    "GRANTS",
    "Grant",
    "Intent",
    "PermissionDeniedError",
    "ProposeSettingChange",
    "ProposeTrade",
    "RiskEnvelope",
    "TradingStatus",
    "UnsafeInstructionError",
    "WorkerRole",
    "authorize",
    "authorize_all",
    "grant_for",
    "has_capability",
    "has_scope",
    "project_account_profile",
    "project_broker_connectivity",
    "project_risk_envelope",
    "project_trading_status",
    "require_capability",
    "require_scope",
]
