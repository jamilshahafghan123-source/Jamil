"""Who may use what.

The access ladder, lowest to highest:

    PUBLIC              homepage, login, signup — no token
    AUTHENTICATED       account basics, support, the subscription page
    DEMO                demo chart and demo trading
    PLATFORM            paid platform features
    ADMIN               owner surfaces

DEMO sits between AUTHENTICATED and PLATFORM on purpose. The product today
gates all customer dashboard access until a subscription exists, so
`demo_open_to_all` ships False and DEMO currently requires the same
entitlement as PLATFORM. Opening a free demo later is then a one-line
change here rather than an audit of every route.

The decisions are pure functions of state and a clock, with no database and
no request in sight, so the awkward cases — a period that ended a second
ago, a status that says ACTIVE over an expired period — are cheap to test.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from ..models import SubscriptionStatus, UserRole


class AccessLevel(str, enum.Enum):
    PUBLIC = "PUBLIC"
    AUTHENTICATED = "AUTHENTICATED"
    DEMO = "DEMO"
    PLATFORM = "PLATFORM"
    ADMIN = "ADMIN"


#: Flip to True to open demo features to any signed-in customer. Kept here
#: so the product decision lives in one place rather than in route wiring.
DEMO_OPEN_TO_ALL = False

#: Statuses that can grant access at all. PAST_DUE is excluded: an unpaid
#: account keeps its data and its support access, but not paid features.
_ENTITLING = frozenset({SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL})


def subscription_grants_access(
    status: SubscriptionStatus | None,
    current_period_end: datetime | None,
    *,
    now: datetime | None = None,
) -> bool:
    """True only for an entitling status inside its paid period.

    A row still marked ACTIVE whose period ended does NOT grant access. A
    provider webhook can be late or lost, so the date is treated as the
    authority over the label — failing closed on the ambiguity.
    """
    if status is None or status not in _ENTITLING:
        return False
    if current_period_end is None:
        return True
    now = now or datetime.now(timezone.utc)
    end = (
        current_period_end
        if current_period_end.tzinfo
        else current_period_end.replace(tzinfo=timezone.utc)
    )
    return end > now


def has_platform_access(
    *,
    role: UserRole,
    is_active: bool,
    status: SubscriptionStatus | None,
    current_period_end: datetime | None,
    now: datetime | None = None,
) -> bool:
    """The single answer the dependencies ask for.

    A disabled account is refused whatever its role — a deactivated admin
    is deactivated.
    """
    if not is_active:
        return False
    if role is UserRole.ADMIN:
        # Administrators are free and never need an entitlement.
        return True
    return subscription_grants_access(status, current_period_end, now=now)


def has_demo_access(
    *,
    role: UserRole,
    is_active: bool,
    status: SubscriptionStatus | None,
    current_period_end: datetime | None,
    now: datetime | None = None,
    demo_open_to_all: bool = DEMO_OPEN_TO_ALL,
) -> bool:
    """Demo today follows platform access; see the module docstring."""
    if not is_active:
        return False
    if role is UserRole.ADMIN:
        return True
    if demo_open_to_all:
        return True
    return subscription_grants_access(status, current_period_end, now=now)


def level_for(
    *,
    role: UserRole,
    is_active: bool,
    status: SubscriptionStatus | None,
    current_period_end: datetime | None,
    now: datetime | None = None,
) -> AccessLevel:
    """Highest level an account currently reaches. For diagnostics and UI."""
    if not is_active:
        return AccessLevel.PUBLIC
    if role is UserRole.ADMIN:
        return AccessLevel.ADMIN
    if subscription_grants_access(status, current_period_end, now=now):
        return AccessLevel.PLATFORM
    if has_demo_access(
        role=role,
        is_active=is_active,
        status=status,
        current_period_end=current_period_end,
        now=now,
    ):
        return AccessLevel.DEMO
    return AccessLevel.AUTHENTICATED
