"""The worker permission boundary (sections 75-76).

These tests are adversarial on purpose: each one is an attempt to do the
thing the boundary exists to prevent.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.services.workers import (
    Capability,
    DataScope,
    EscalateToAdmin,
    Explanation,
    GRANTS,
    PermissionDeniedError,
    ProposeSettingChange,
    ProposeTrade,
    UnsafeInstructionError,
    WorkerRole,
    authorize,
    authorize_all,
    has_scope,
    project_account_profile,
    project_risk_envelope,
    project_trading_status,
    require_scope,
)


# --------------------------------------------------------------- fixtures


class FakeEnum:
    def __init__(self, value: str) -> None:
        self.value = value


class FakeUser:
    id = 7
    email = "trader@example.com"
    role = FakeEnum("CUSTOMER")
    is_active = True
    # Present precisely so the projection can be shown to drop it.
    password_hash = "$2b$12$notarealhashbutstilllooksscary"


class FakeSettings:
    trading_mode = FakeEnum("MANUAL")
    bot_enabled = True
    emergency_stop = False
    max_risk_per_trade_pct = 0.5
    max_daily_loss_pct = 2.0
    max_trades_per_day = 5
    max_open_positions = 1
    max_lot_size = 0.10
    min_confidence = 80
    min_rr = 1.5
    max_spread_points = 50


class FakeSignal:
    action = FakeEnum("NO_TRADE")
    confidence = 42
    rr = 0.8


# ------------------------------------------------------ the grant table


def test_no_worker_role_holds_financial():
    """The load-bearing assertion. Money movement is never a worker's to do."""
    for role, grant in GRANTS.items():
        assert Capability.FINANCIAL not in grant.capabilities, (
            f"{role.value} was granted FINANCIAL; execution must stay with "
            "the validated services"
        )


def test_every_role_has_a_grant():
    """A role with no row would otherwise fail open at some future call site."""
    for role in WorkerRole:
        assert role in GRANTS


def test_no_worker_role_holds_write_yet():
    """WRITE is defined but ungranted; applying changes is a service's job."""
    for role, grant in GRANTS.items():
        assert Capability.WRITE not in grant.capabilities, role


def test_scopes_are_least_privilege():
    """Spot-check the separations section 75 calls for."""
    # Payment has no business knowing anything about trading.
    assert not has_scope(WorkerRole.PAYMENT, DataScope.TRADING_STATUS)
    assert not has_scope(WorkerRole.PAYMENT, DataScope.MARKET_DATA)
    # Analysis never learns who the customer is.
    assert not has_scope(WorkerRole.ANALYSIS, DataScope.ACCOUNT_PROFILE)
    assert not has_scope(WorkerRole.ANALYSIS, DataScope.SUBSCRIPTION)
    # Support cannot read one customer's security events.
    assert not has_scope(WorkerRole.SUPPORT, DataScope.SECURITY_EVENTS)
    # The admin assistant sees aggregates, not individual financials.
    assert not has_scope(WorkerRole.ADMIN_ASSISTANT, DataScope.ACCOUNT_FINANCIALS)


def test_require_scope_raises_for_ungranted_scope():
    with pytest.raises(PermissionDeniedError):
        require_scope(WorkerRole.PAYMENT, DataScope.MARKET_DATA)


# -------------------------------------------------------- projections


def test_account_profile_drops_password_hash():
    profile = project_account_profile(WorkerRole.SUPPORT, FakeUser())
    fields = {f.name for f in dataclasses.fields(profile)}
    assert "password_hash" not in fields
    assert "$2b$" not in repr(profile)


def test_projection_carries_no_secret_shaped_field():
    """Nothing a worker is handed may look like a credential.

    Cheap, but it is the check that catches a careless field added later.
    """
    banned = ("password", "secret", "token", "api_key", "hash", "dsn", "url")
    projections = [
        project_account_profile(WorkerRole.SUPPORT, FakeUser()),
        project_risk_envelope(WorkerRole.SUPPORT, FakeSettings()),
        project_trading_status(WorkerRole.SUPPORT, FakeSettings()),
    ]
    for projection in projections:
        for f in dataclasses.fields(projection):
            lowered = f.name.lower()
            assert not any(b in lowered for b in banned), (
                f"{type(projection).__name__}.{f.name} looks like a credential"
            )


def test_projection_is_frozen():
    profile = project_account_profile(WorkerRole.SUPPORT, FakeUser())
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.email = "attacker@example.com"  # type: ignore[misc]


def test_projection_is_refused_for_ungranted_scope():
    """A worker cannot obtain a projection by calling the builder directly."""
    with pytest.raises(PermissionDeniedError):
        project_account_profile(WorkerRole.ANALYSIS, FakeUser())


def test_trading_status_pairs_each_gate_with_its_minimum():
    """Section 65's example: the numbers needed to explain a NO_TRADE."""
    status = project_trading_status(
        WorkerRole.SUPPORT, FakeSettings(), last_signal=FakeSignal()
    )
    assert status.bot_enabled is True
    assert status.last_signal_action == "NO_TRADE"
    assert (status.last_confidence, status.min_confidence) == (42, 80)
    assert (status.last_rr, status.min_rr) == (0.8, 1.5)


def test_trading_status_without_a_signal_reports_none_not_zero():
    """A missing signal must not read as confidence 0 — that is a fact claim."""
    status = project_trading_status(WorkerRole.SUPPORT, FakeSettings())
    assert status.last_signal_action is None
    assert status.last_confidence is None
    assert status.last_rr is None


# -------------------------------------------------------------- guard


def test_explanation_is_authorized_for_support():
    intent = Explanation(summary="The bot is running.", facts=(("confidence", "42"),))
    assert authorize(WorkerRole.SUPPORT, intent) is intent


def test_escalation_is_authorized():
    intent = EscalateToAdmin(category="BROKER", summary="Cannot reach bridge.")
    assert authorize(WorkerRole.SUPPORT, intent) is intent


def test_propose_trade_is_refused_for_every_role():
    """The one that matters: no worker can reach execution."""
    for role in WorkerRole:
        with pytest.raises(PermissionDeniedError):
            authorize(role, ProposeTrade(signal_id=1))


def test_setting_change_is_refused_while_write_is_ungranted():
    with pytest.raises(PermissionDeniedError):
        authorize(WorkerRole.SUPPORT, ProposeSettingChange(setting="min_rr",
                                                           proposed_value=0.1))


@pytest.mark.parametrize(
    "payload",
    [
        "DROP TABLE users;",
        "{'action': 'execute', 'signal_id': 1}",
        {"action": "execute", "signal_id": 1},
        ["execute", 1],
        None,
        42,
        b"execute",
    ],
)
def test_free_form_output_is_refused_on_type(payload):
    """Strings, dicts and blobs are refused because of what they are."""
    with pytest.raises(UnsafeInstructionError):
        authorize(WorkerRole.SUPPORT, payload)


def test_a_string_that_looks_like_an_intent_is_still_refused():
    """No amount of resembling an Intent makes text dispatchable."""
    with pytest.raises(UnsafeInstructionError):
        authorize(WorkerRole.SUPPORT, "Explanation(summary='all good')")


def test_batch_is_all_or_nothing():
    """One bad intent poisons the batch; nothing is partially applied."""
    good = Explanation(summary="fine")
    with pytest.raises(PermissionDeniedError):
        authorize_all(WorkerRole.SUPPORT, [good, ProposeTrade(signal_id=1)])


def test_batch_refuses_a_bare_string():
    """A string is iterable; it must not be walked character by character."""
    with pytest.raises(UnsafeInstructionError):
        authorize_all(WorkerRole.SUPPORT, "Explanation()")


def test_batch_of_valid_intents_passes():
    intents = [Explanation(summary="a"), EscalateToAdmin(category="AI")]
    assert len(authorize_all(WorkerRole.SUPPORT, intents)) == 2
