"""Component health for the admin control centre.

Section 81's SYSTEM HEALTH panel, and the input safe mode evaluates from.

Health is reported per component with an explicit UNKNOWN state, kept
separate from DOWN on purpose: "we did not check" and "we checked and it
is broken" lead to different decisions, and collapsing them is how a
monitoring system starts lying. Safe mode treats UNKNOWN on a critical
component as untrustworthy, which is the fail-closed reading.

Nothing here performs I/O. Callers do the probing and hand in readings, so
this module stays cheap, deterministic and testable — a health aggregator
that opens sockets cannot be tested against the failures that matter.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


class ComponentStatus(str, enum.Enum):
    UP = "UP"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"
    #: Not checked, or the check itself failed to produce an answer.
    UNKNOWN = "UNKNOWN"
    #: Deliberately switched off, or not configured in this deployment.
    NOT_CONFIGURED = "NOT_CONFIGURED"


#: Worst-first, for aggregating. NOT_CONFIGURED is not a fault: a payment
#: service nobody has connected yet must not make the platform look broken.
_SEVERITY: dict[ComponentStatus, int] = {
    ComponentStatus.DOWN: 4,
    ComponentStatus.UNKNOWN: 3,
    ComponentStatus.DEGRADED: 2,
    ComponentStatus.UP: 1,
    ComponentStatus.NOT_CONFIGURED: 0,
}


class Component(str, enum.Enum):
    """The components section 81 asks the control centre to show."""

    BACKEND = "backend"
    DATABASE = "database"
    MT5 = "mt5"
    MT5_BRIDGE = "mt5_bridge"
    MARKET_DATA = "market_data"
    AI_WORKERS = "ai_workers"
    PAYMENT_SERVICE = "payment_service"
    NOTIFICATION_SERVICE = "notification_service"


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    component: Component
    status: ComponentStatus
    #: Operator-facing. Never a raw exception or anything carrying a secret.
    detail: str = ""
    checked_at: datetime | None = None

    def as_dict(self) -> dict:
        return {
            "component": self.component.value,
            "status": self.status.value,
            "detail": self.detail,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
        }


@dataclass(frozen=True, slots=True)
class SystemHealth:
    components: tuple[ComponentHealth, ...]

    @property
    def overall(self) -> ComponentStatus:
        """Worst component wins. An average would hide the one that matters."""
        if not self.components:
            return ComponentStatus.UNKNOWN
        return max(
            (c.status for c in self.components),
            key=lambda s: _SEVERITY[s],
        )

    @property
    def faults(self) -> tuple[ComponentHealth, ...]:
        return tuple(
            c
            for c in self.components
            if c.status in (ComponentStatus.DOWN, ComponentStatus.UNKNOWN,
                            ComponentStatus.DEGRADED)
        )

    def get(self, component: Component) -> ComponentHealth | None:
        for c in self.components:
            if c.component is component:
                return c
        return None

    def as_dict(self) -> dict:
        return {
            "overall": self.overall.value,
            "components": [c.as_dict() for c in self.components],
            "fault_count": len(self.faults),
        }


def market_data_health(
    last_tick_at: datetime | None,
    *,
    now: datetime | None = None,
    stale_after: timedelta = timedelta(seconds=90),
    down_after: timedelta = timedelta(minutes=10),
) -> ComponentHealth:
    """Freshness, graded. Section 81's "market-data freshness"."""
    now = now or datetime.now(timezone.utc)
    if last_tick_at is None:
        return ComponentHealth(
            Component.MARKET_DATA,
            ComponentStatus.UNKNOWN,
            "No tick has been received yet.",
            now,
        )
    seen = last_tick_at if last_tick_at.tzinfo else last_tick_at.replace(
        tzinfo=timezone.utc
    )
    age = now - seen
    if age < timedelta(0):
        return ComponentHealth(
            Component.MARKET_DATA,
            ComponentStatus.UNKNOWN,
            "Last tick is timestamped in the future; clocks disagree.",
            now,
        )
    if age >= down_after:
        return ComponentHealth(
            Component.MARKET_DATA,
            ComponentStatus.DOWN,
            f"No tick for {int(age.total_seconds())}s.",
            now,
        )
    if age >= stale_after:
        return ComponentHealth(
            Component.MARKET_DATA,
            ComponentStatus.DEGRADED,
            f"Last tick {int(age.total_seconds())}s ago.",
            now,
        )
    return ComponentHealth(
        Component.MARKET_DATA,
        ComponentStatus.UP,
        f"Last tick {int(age.total_seconds())}s ago.",
        now,
    )


def bridge_health(
    *,
    connected: bool,
    authenticated: bool = True,
    now: datetime | None = None,
) -> ComponentHealth:
    """Auth failure is reported distinctly from an outage.

    Section 83: a token mismatch must stop retries and ask a human, not be
    treated as a connectivity blip to be retried around.
    """
    now = now or datetime.now(timezone.utc)
    if not authenticated:
        return ComponentHealth(
            Component.MT5_BRIDGE,
            ComponentStatus.DOWN,
            "Bridge authentication failed. Credential verification required.",
            now,
        )
    if not connected:
        return ComponentHealth(
            Component.MT5_BRIDGE, ComponentStatus.DOWN, "Bridge unreachable.", now
        )
    return ComponentHealth(Component.MT5_BRIDGE, ComponentStatus.UP, "Reachable.", now)


def simple(
    component: Component,
    ok: bool | None,
    *,
    up_detail: str = "",
    down_detail: str = "",
    now: datetime | None = None,
) -> ComponentHealth:
    """None means not checked — which is UNKNOWN, never UP."""
    now = now or datetime.now(timezone.utc)
    if ok is None:
        return ComponentHealth(component, ComponentStatus.UNKNOWN, "Not checked.", now)
    return ComponentHealth(
        component,
        ComponentStatus.UP if ok else ComponentStatus.DOWN,
        up_detail if ok else down_detail,
        now,
    )
