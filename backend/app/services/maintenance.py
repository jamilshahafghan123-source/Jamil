"""Maintenance mode (section 5).

Entered around operations that make the platform's state briefly untrue —
a database restore above all. While it is on, nothing new is opened, but
nothing existing is torn down.

WHAT IT BLOCKS, AND WHAT IT DELIBERATELY DOES NOT
-------------------------------------------------
Blocked: new automated trades, and new *opening* broker execution. Those
are the actions that commit fresh risk against state we cannot vouch for.

Allowed: closing a position. A maintenance window must never trap someone
in a trade — the whole point is that we are unsure, and forcing a customer
to hold through that uncertainty is worse than letting them out. Closing
reduces exposure; it is the one financial action that is safer to permit
than to block.

Also allowed: login, health, admin diagnostics, and support. A customer
whose bot has stopped is exactly who needs to see why.

Nothing here closes a position by itself. Entering maintenance is not a
trading decision and must never become one.

State is process-level and explicit. It does not time out: a window ends
because somebody ended it, not because a clock ran down while a restore
was still in flight.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class MaintenanceState:
    active: bool
    reason: str = ""
    since: datetime | None = None
    #: Free text for operators. Redacted by the caller before display.
    detail: str = ""

    @property
    def blocks_automated_trading(self) -> bool:
        return self.active

    @property
    def blocks_new_broker_execution(self) -> bool:
        return self.active

    @property
    def blocks_closing_a_position(self) -> bool:
        """Never. See the module docstring."""
        return False

    @property
    def blocks_account_viewing(self) -> bool:
        return False

    @property
    def blocks_support(self) -> bool:
        return False

    def as_dict(self) -> dict:
        return {
            "active": self.active,
            "reason": self.reason,
            "since": self.since.isoformat() if self.since else None,
            "detail": self.detail,
        }


_state = MaintenanceState(active=False)

#: Shown to customers. Plain, and never names a service or a file.
CUSTOMER_MESSAGE = (
    "The platform is briefly in maintenance. Automated trading is paused and "
    "new orders are not being accepted. Existing positions are unaffected and "
    "can still be closed."
)


def current() -> MaintenanceState:
    return _state


def enter(reason: str, *, detail: str = "", now: datetime | None = None) -> MaintenanceState:
    global _state
    _state = MaintenanceState(
        active=True,
        reason=reason,
        since=now or datetime.now(timezone.utc),
        detail=detail,
    )
    return _state


def exit_(*, detail: str = "") -> MaintenanceState:
    global _state
    _state = MaintenanceState(active=False, detail=detail)
    return _state


def reset() -> None:
    """Test helper. Never called by application code."""
    global _state
    _state = MaintenanceState(active=False)
