"""What each AI worker is allowed to do, and to what.

This module is the enforcement point the rest of the worker architecture
hangs off. The rule it exists to make structural rather than conventional:

    a worker may READ what its role grants and RECOMMEND from it.
    Nothing a worker returns is ever executed as written.

Capability tiers are deliberately ordered but NOT hierarchical — holding
WRITE does not imply FINANCIAL. Each grant is listed explicitly so that
widening a worker's reach is a visible diff on the grant table rather than
an emergent consequence of some inheritance rule.

FINANCIAL is granted to nobody. It exists so that any code path asking for
it fails loudly: money movement belongs to the validated execution services
(risk_engine -> executor), which are not workers and do not go through this
table. A worker that needs a trade placed emits an intent; the execution
service decides.
"""

from __future__ import annotations

import enum
from types import MappingProxyType


class Capability(str, enum.Enum):
    """The four action tiers. See section 76 of the platform brief."""

    #: Read an allowlisted projection of real state. Never raw ORM rows.
    READ = "READ"
    #: Produce advice, explanation or a proposed action for a human/service.
    RECOMMEND = "RECOMMEND"
    #: Change stored application state, via an explicit validated command.
    WRITE = "WRITE"
    #: Move money or place orders. Reserved for validated services.
    FINANCIAL = "FINANCIAL"


class WorkerRole(str, enum.Enum):
    """The departments in section 80. One responsibility each."""

    SUPPORT = "SUPPORT"
    PAYMENT = "PAYMENT"
    BROKER_SUPPORT = "BROKER_SUPPORT"
    ANALYSIS = "ANALYSIS"
    ADMIN_ASSISTANT = "ADMIN_ASSISTANT"
    SECURITY = "SECURITY"
    NOTIFICATION = "NOTIFICATION"


class DataScope(str, enum.Enum):
    """Slices of state a worker may be handed. Least privilege, per role."""

    #: Email, role, active flag, subscription state. No password hash.
    ACCOUNT_PROFILE = "ACCOUNT_PROFILE"
    #: Plan, renewal, provider-reported payment state. Never card data.
    SUBSCRIPTION = "SUBSCRIPTION"
    #: Connection status, account type, currency. Never broker credentials.
    BROKER_CONNECTIVITY = "BROKER_CONNECTIVITY"
    #: Balance, equity, open position count. Read-only.
    ACCOUNT_FINANCIALS = "ACCOUNT_FINANCIALS"
    #: Bot state, last signal, confidence and RR against configured minima.
    TRADING_STATUS = "TRADING_STATUS"
    #: The configured risk envelope. Read-only; changing it is a WRITE.
    RISK_SETTINGS = "RISK_SETTINGS"
    #: Bars, indicators, structure. No account data.
    MARKET_DATA = "MARKET_DATA"
    #: Ticket contents and safe diagnostics.
    SUPPORT_TICKETS = "SUPPORT_TICKETS"
    #: Failed logins, rate-limit events, session anomalies.
    SECURITY_EVENTS = "SECURITY_EVENTS"
    #: Aggregate counts across customers. Never one customer's detail.
    PLATFORM_AGGREGATES = "PLATFORM_AGGREGATES"


class Grant:
    """One row of the permission table: what a role may do, and to what."""

    __slots__ = ("capabilities", "scopes")

    def __init__(
        self,
        capabilities: frozenset[Capability],
        scopes: frozenset[DataScope],
    ) -> None:
        self.capabilities = capabilities
        self.scopes = scopes


def _grant(caps: tuple[Capability, ...], scopes: tuple[DataScope, ...]) -> Grant:
    return Grant(frozenset(caps), frozenset(scopes))


#: The permission table. Read it top to bottom to audit the whole system.
#:
#: Note what is absent as much as what is present: no role holds FINANCIAL,
#: SUPPORT cannot see RISK_SETTINGS as writable, PAYMENT cannot see trading
#: state at all, and ANALYSIS — the only role touching market data — has no
#: access to a customer's identity.
GRANTS: MappingProxyType[WorkerRole, Grant] = MappingProxyType(
    {
        WorkerRole.SUPPORT: _grant(
            (Capability.READ, Capability.RECOMMEND),
            (
                DataScope.ACCOUNT_PROFILE,
                DataScope.SUBSCRIPTION,
                DataScope.BROKER_CONNECTIVITY,
                DataScope.TRADING_STATUS,
                DataScope.RISK_SETTINGS,
                DataScope.SUPPORT_TICKETS,
            ),
        ),
        WorkerRole.PAYMENT: _grant(
            (Capability.READ, Capability.RECOMMEND),
            (DataScope.ACCOUNT_PROFILE, DataScope.SUBSCRIPTION),
        ),
        WorkerRole.BROKER_SUPPORT: _grant(
            (Capability.READ, Capability.RECOMMEND),
            (
                DataScope.ACCOUNT_PROFILE,
                DataScope.BROKER_CONNECTIVITY,
                DataScope.ACCOUNT_FINANCIALS,
            ),
        ),
        WorkerRole.ANALYSIS: _grant(
            (Capability.READ, Capability.RECOMMEND),
            (DataScope.MARKET_DATA, DataScope.TRADING_STATUS, DataScope.RISK_SETTINGS),
        ),
        WorkerRole.ADMIN_ASSISTANT: _grant(
            (Capability.READ, Capability.RECOMMEND),
            (
                DataScope.PLATFORM_AGGREGATES,
                DataScope.SUPPORT_TICKETS,
                DataScope.SECURITY_EVENTS,
                DataScope.TRADING_STATUS,
            ),
        ),
        WorkerRole.SECURITY: _grant(
            (Capability.READ, Capability.RECOMMEND),
            (DataScope.SECURITY_EVENTS, DataScope.ACCOUNT_PROFILE),
        ),
        WorkerRole.NOTIFICATION: _grant(
            (Capability.READ, Capability.RECOMMEND),
            (DataScope.ACCOUNT_PROFILE, DataScope.TRADING_STATUS),
        ),
    }
)


def grant_for(role: WorkerRole) -> Grant:
    """The grant for a role. Unknown roles fail rather than defaulting open."""
    try:
        return GRANTS[role]
    except KeyError:  # pragma: no cover - unreachable while GRANTS is total
        raise PermissionDeniedError(
            f"no grant defined for worker role {role!r}"
        ) from None


class PermissionDeniedError(Exception):
    """A worker asked for a capability, scope or action it does not hold."""


def has_capability(role: WorkerRole, capability: Capability) -> bool:
    return capability in grant_for(role).capabilities


def has_scope(role: WorkerRole, scope: DataScope) -> bool:
    return scope in grant_for(role).scopes


def require_capability(role: WorkerRole, capability: Capability) -> None:
    """Raise unless the role holds the capability. No silent downgrade."""
    if not has_capability(role, capability):
        raise PermissionDeniedError(
            f"worker {role.value} does not hold {capability.value}"
        )


def require_scope(role: WorkerRole, scope: DataScope) -> None:
    """Raise unless the role may see the scope."""
    if not has_scope(role, scope):
        raise PermissionDeniedError(
            f"worker {role.value} may not read {scope.value}"
        )
