"""Owner notification events (section 8).

An event layer, not a delivery mechanism. Rows are written here and the
admin control centre reads them; nothing pretends to have emailed or pushed
anything. `delivered_channels` stays empty until something real delivers,
so the record never overstates what happened.

Adding email or push later means writing a deliverer that consumes these
rows and appends to that list — no change to any caller.

Section 8 also says not to spam the owner with successful health checks, so
`should_notify` filters routine noise: a recovery that worked first time is
INFO and worth one line, a health check that passed is not an event at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...models import NotificationSeverity


@dataclass(frozen=True, slots=True)
class NotificationEvent:
    severity: NotificationSeverity
    event: str
    message: str
    incident_id: int | None = None


def bridge_restarted(incident_id: int | None = None) -> NotificationEvent:
    return NotificationEvent(
        NotificationSeverity.INFO, "bridge_restarted",
        "MT5 bridge restarted successfully.", incident_id,
    )


def market_data_stale(incident_id: int | None = None) -> NotificationEvent:
    return NotificationEvent(
        NotificationSeverity.WARNING, "market_data_stale",
        "Market data became stale. Automated trading is paused.", incident_id,
    )


def recovery_failed(service: str, attempts: int,
                    incident_id: int | None = None) -> NotificationEvent:
    return NotificationEvent(
        NotificationSeverity.HIGH, "recovery_failed",
        f"{service} recovery failed after {attempts} attempts.", incident_id,
    )


def auth_failure(what: str, incident_id: int | None = None) -> NotificationEvent:
    return NotificationEvent(
        NotificationSeverity.CRITICAL, "auth_failure",
        (f"{what} authentication failed. Automated trading remains paused and "
         "credential verification is required."),
        incident_id,
    )


def service_recovered(service: str,
                      incident_id: int | None = None) -> NotificationEvent:
    return NotificationEvent(
        NotificationSeverity.INFO, "service_recovered",
        f"{service} recovered and passed its health check.", incident_id,
    )


def needs_admin(service: str, reason: str,
                incident_id: int | None = None) -> NotificationEvent:
    return NotificationEvent(
        NotificationSeverity.HIGH, "needs_admin",
        f"{service} needs attention: {reason}", incident_id,
    )


#: Events routine enough to suppress when nothing actually changed.
_ROUTINE = frozenset({"health_check_passed"})


def should_notify(event: NotificationEvent, *, state_changed: bool = True) -> bool:
    """Section 8: no spam for normal successful health checks."""
    if event.event in _ROUTINE:
        return False
    if event.severity is NotificationSeverity.INFO and not state_changed:
        return False
    return True
