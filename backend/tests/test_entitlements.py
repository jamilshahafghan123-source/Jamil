"""Entitlement rules (sections 2, 3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import SubscriptionStatus, UserRole
from app.services.entitlements import (
    AccessLevel,
    has_demo_access,
    has_platform_access,
    level_for,
    subscription_grants_access,
)

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
FUTURE = NOW + timedelta(days=10)
PAST = NOW - timedelta(days=1)


@pytest.mark.parametrize(
    "status,expected",
    [
        (SubscriptionStatus.ACTIVE, True),
        (SubscriptionStatus.TRIAL, True),
        (SubscriptionStatus.PAST_DUE, False),
        (SubscriptionStatus.CANCELED, False),
        (SubscriptionStatus.EXPIRED, False),
        (SubscriptionStatus.NONE, False),
        (None, False),
    ],
)
def test_status_decides_entitlement(status, expected):
    assert subscription_grants_access(status, FUTURE, now=NOW) is expected


def test_active_past_its_period_does_not_grant_access():
    """The date outranks the label: a missed webhook must fail closed."""
    assert subscription_grants_access(SubscriptionStatus.ACTIVE, PAST, now=NOW) is False


def test_open_ended_period_grants_access():
    assert subscription_grants_access(SubscriptionStatus.ACTIVE, None, now=NOW) is True


def test_naive_timestamp_is_treated_as_utc():
    naive = FUTURE.replace(tzinfo=None)
    assert subscription_grants_access(SubscriptionStatus.ACTIVE, naive, now=NOW) is True


def test_admin_needs_no_subscription():
    assert (
        has_platform_access(
            role=UserRole.ADMIN, is_active=True, status=None,
            current_period_end=None, now=NOW,
        )
        is True
    )


def test_inactive_admin_is_still_refused():
    """Deactivating an account must mean something even for an owner."""
    assert (
        has_platform_access(
            role=UserRole.ADMIN, is_active=False, status=None,
            current_period_end=None, now=NOW,
        )
        is False
    )


def test_customer_without_a_subscription_row_is_refused():
    """Accounts predating the table have no entitlement, not a free pass."""
    assert (
        has_platform_access(
            role=UserRole.CUSTOMER, is_active=True, status=None,
            current_period_end=None, now=NOW,
        )
        is False
    )


def test_demo_currently_follows_platform_access():
    """Today's product gates all customer dashboard access; preserved."""
    assert (
        has_demo_access(
            role=UserRole.CUSTOMER, is_active=True, status=SubscriptionStatus.NONE,
            current_period_end=None, now=NOW,
        )
        is False
    )


def test_demo_can_be_opened_without_touching_routes():
    """The future free-demo switch works, and only affects demo."""
    kwargs = dict(
        role=UserRole.CUSTOMER, is_active=True, status=SubscriptionStatus.NONE,
        current_period_end=None, now=NOW,
    )
    assert has_demo_access(**kwargs, demo_open_to_all=True) is True
    assert has_platform_access(**kwargs) is False


def test_level_for_reports_the_ladder():
    assert (
        level_for(role=UserRole.ADMIN, is_active=True, status=None,
                  current_period_end=None, now=NOW)
        is AccessLevel.ADMIN
    )
    assert (
        level_for(role=UserRole.CUSTOMER, is_active=True,
                  status=SubscriptionStatus.ACTIVE, current_period_end=FUTURE,
                  now=NOW)
        is AccessLevel.PLATFORM
    )
    assert (
        level_for(role=UserRole.CUSTOMER, is_active=True,
                  status=SubscriptionStatus.NONE, current_period_end=None, now=NOW)
        is AccessLevel.AUTHENTICATED
    )
    assert (
        level_for(role=UserRole.CUSTOMER, is_active=False,
                  status=SubscriptionStatus.ACTIVE, current_period_end=FUTURE,
                  now=NOW)
        is AccessLevel.PUBLIC
    )
