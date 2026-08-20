"""Component health aggregation (section 81)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.health import (
    Component,
    ComponentHealth,
    ComponentStatus,
    SystemHealth,
    bridge_health,
    market_data_health,
    simple,
)

NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)


def test_unknown_is_not_up():
    """"Not checked" must never be reported as healthy."""
    assert simple(Component.AI_WORKERS, None, now=NOW).status is ComponentStatus.UNKNOWN


def test_market_data_grades_by_age():
    assert market_data_health(NOW - timedelta(seconds=5), now=NOW).status is (
        ComponentStatus.UP
    )
    assert market_data_health(NOW - timedelta(minutes=2), now=NOW).status is (
        ComponentStatus.DEGRADED
    )
    assert market_data_health(NOW - timedelta(hours=1), now=NOW).status is (
        ComponentStatus.DOWN
    )


def test_market_data_with_no_tick_is_unknown_not_down():
    assert market_data_health(None, now=NOW).status is ComponentStatus.UNKNOWN


def test_future_tick_is_unknown():
    h = market_data_health(NOW + timedelta(minutes=5), now=NOW)
    assert h.status is ComponentStatus.UNKNOWN
    assert "clock" in h.detail.lower()


def test_bridge_auth_failure_says_so_without_naming_the_secret():
    h = bridge_health(connected=True, authenticated=False, now=NOW)
    assert h.status is ComponentStatus.DOWN
    assert "authentication" in h.detail.lower()
    assert "token" not in h.detail.lower()


def test_overall_is_the_worst_component():
    system = SystemHealth(
        (
            ComponentHealth(Component.BACKEND, ComponentStatus.UP),
            ComponentHealth(Component.DATABASE, ComponentStatus.UP),
            ComponentHealth(Component.MT5_BRIDGE, ComponentStatus.DOWN),
        )
    )
    assert system.overall is ComponentStatus.DOWN
    assert len(system.faults) == 1


def test_not_configured_does_not_make_the_platform_look_broken():
    system = SystemHealth(
        (
            ComponentHealth(Component.BACKEND, ComponentStatus.UP),
            ComponentHealth(Component.PAYMENT_SERVICE, ComponentStatus.NOT_CONFIGURED),
        )
    )
    assert system.overall is ComponentStatus.UP
    assert system.faults == ()


def test_unknown_outranks_degraded():
    """Not knowing is worse than knowing it is imperfect."""
    system = SystemHealth(
        (
            ComponentHealth(Component.MARKET_DATA, ComponentStatus.DEGRADED),
            ComponentHealth(Component.AI_WORKERS, ComponentStatus.UNKNOWN),
        )
    )
    assert system.overall is ComponentStatus.UNKNOWN


def test_empty_system_is_unknown_not_up():
    assert SystemHealth(()).overall is ComponentStatus.UNKNOWN
