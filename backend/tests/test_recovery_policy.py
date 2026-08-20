"""Recovery operations, policy and state machine (sections 2, 4, 6, 13).

No test here can reach a real machine: the planner executes nothing, and
the agent is never configured in the suite, so every call short-circuits to
"unavailable" before any socket is opened. See test_agent_is_inert_in_tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.recovery import (
    MUTATING,
    POLICIES,
    READ_ONLY,
    FailureCategory,
    Operation,
    RecoveryPlanner,
    Service,
    ServiceState,
    UnknownOperationError,
    is_mutating,
    parse,
)
from app.services.recovery.policy import ATTEMPT_WINDOW, MAX_ATTEMPTS

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)


# ------------------------------------------------------- the allow-list


@pytest.mark.parametrize(
    "payload",
    [
        "powershell Stop-Process -Name terminal64",
        "docker restart backend; rm -rf /",
        "RESTART_BRIDGE; whoami",
        "restart_bridge",           # wrong case is not a near-miss, it is unknown
        "run_command",
        "",
        "../../etc/passwd",
        "CHECK_MT5 && echo hi",
    ],
)
def test_arbitrary_command_strings_are_rejected(payload):
    with pytest.raises(UnknownOperationError):
        parse(payload)


@pytest.mark.parametrize("payload", [None, 42, {"operation": "RESTART_BRIDGE"},
                                     ["RESTART_BRIDGE"], object()])
def test_non_string_payloads_are_rejected(payload):
    with pytest.raises(UnknownOperationError):
        parse(payload)


def test_every_valid_operation_round_trips():
    for op in Operation:
        assert parse(op.value) is op
        assert parse(op) is op


def test_read_only_and_mutating_partition_the_set():
    assert READ_ONLY | MUTATING == set(Operation)
    assert not (READ_ONLY & MUTATING)


def test_restarts_are_classified_as_mutating():
    for op in (Operation.RESTART_BRIDGE, Operation.RESTART_BACKEND,
               Operation.RESTART_FRONTEND, Operation.RESTART_DATABASE,
               Operation.START_MT5):
        assert is_mutating(op)


def test_checks_are_not_mutating():
    for op in (Operation.CHECK_MT5, Operation.CHECK_DOCKER,
               Operation.VERIFY_HEALTH):
        assert not is_mutating(op)


def test_no_operation_carries_a_free_text_field():
    """The enum has no payload, so there is nowhere to hide a command."""
    for op in Operation:
        assert isinstance(op.value, str)
        assert op.value == op.name


# --------------------------------------------------------- auth failure


def test_auth_failure_escalates_without_attempting_anything():
    """Section 4: never guess, rewrite or copy a secret."""
    planner = RecoveryPlanner()
    d = planner.plan(Service.BRIDGE, FailureCategory.AUTH_FAILURE, now=NOW)
    assert d.state is ServiceState.NEEDS_ADMIN
    assert d.operations == ()
    assert d.notify_severity == "CRITICAL"
    assert planner.record_for(Service.BRIDGE).attempts == []


def test_auth_failure_reason_promises_no_secret_change():
    planner = RecoveryPlanner()
    d = planner.plan(Service.BRIDGE, FailureCategory.AUTH_FAILURE, now=NOW)
    assert "no automatic retry" in d.reason.lower()
    for leak in ("token", "password", "secret value", ".env"):
        assert leak not in d.reason.lower().replace("secret change", "")


def test_repeated_auth_failure_never_starts_retrying():
    planner = RecoveryPlanner()
    for i in range(5):
        d = planner.plan(Service.BRIDGE, FailureCategory.AUTH_FAILURE,
                         now=NOW + timedelta(minutes=i))
        assert d.operations == ()
        assert d.state is ServiceState.NEEDS_ADMIN


# ------------------------------------------------------- retry / cooldown


def test_first_failure_plans_diagnose_repair_verify_in_order():
    planner = RecoveryPlanner()
    d = planner.plan(Service.BRIDGE, FailureCategory.UNREACHABLE, now=NOW)
    assert d.state is ServiceState.RECOVERING
    assert d.operations[0] is Operation.CHECK_BRIDGE
    assert Operation.RESTART_BRIDGE in d.operations
    # Verification comes after the repair, never before.
    assert d.operations.index(Operation.RESTART_BRIDGE) < d.operations.index(
        Operation.VERIFY_HEALTH
    )


def test_cooldown_blocks_an_immediate_second_attempt():
    planner = RecoveryPlanner()
    planner.plan(Service.BRIDGE, FailureCategory.UNREACHABLE, now=NOW)
    d = planner.plan(Service.BRIDGE, FailureCategory.UNREACHABLE,
                     now=NOW + timedelta(seconds=5))
    assert d.state is ServiceState.MONITORING
    assert d.operations == ()
    assert "cooldown" in d.reason.lower()


def test_backoff_grows_between_attempts():
    """30s, then 60s: the second wait is longer than the first."""
    planner = RecoveryPlanner()
    planner.plan(Service.BRIDGE, FailureCategory.UNREACHABLE, now=NOW)
    t1 = NOW + timedelta(seconds=31)
    assert planner.plan(Service.BRIDGE, FailureCategory.UNREACHABLE,
                        now=t1).state is ServiceState.RECOVERING
    # 31s after the second attempt is still inside the 60s window.
    t2 = t1 + timedelta(seconds=31)
    assert planner.plan(Service.BRIDGE, FailureCategory.UNREACHABLE,
                        now=t2).state is ServiceState.MONITORING


def test_attempt_cap_escalates_to_needs_admin():
    """The loop guard. A broken service is not restarted forever."""
    planner = RecoveryPlanner()
    t = NOW
    for _ in range(MAX_ATTEMPTS):
        d = planner.plan(Service.BRIDGE, FailureCategory.UNREACHABLE, now=t)
        assert d.state is ServiceState.RECOVERING
        t += timedelta(minutes=3)
    d = planner.plan(Service.BRIDGE, FailureCategory.UNREACHABLE, now=t)
    assert d.state is ServiceState.NEEDS_ADMIN
    assert d.operations == ()
    assert d.notify_severity == "HIGH"


def test_needs_admin_does_not_time_itself_out():
    """Only a human clears it; no amount of waiting resumes restarting."""
    planner = RecoveryPlanner()
    t = NOW
    for _ in range(MAX_ATTEMPTS):
        planner.plan(Service.BRIDGE, FailureCategory.UNREACHABLE, now=t)
        t += timedelta(minutes=3)
    planner.plan(Service.BRIDGE, FailureCategory.UNREACHABLE, now=t)
    far_future = t + ATTEMPT_WINDOW * 10
    d = planner.plan(Service.BRIDGE, FailureCategory.UNREACHABLE, now=far_future)
    assert d.state is ServiceState.NEEDS_ADMIN
    assert d.operations == ()


def test_admin_clear_resumes_recovery():
    planner = RecoveryPlanner()
    t = NOW
    for _ in range(MAX_ATTEMPTS + 1):
        planner.plan(Service.BRIDGE, FailureCategory.UNREACHABLE, now=t)
        t += timedelta(minutes=3)
    assert planner.state_of(Service.BRIDGE) is ServiceState.NEEDS_ADMIN
    planner.clear(Service.BRIDGE)
    d = planner.plan(Service.BRIDGE, FailureCategory.UNREACHABLE, now=t)
    assert d.state is ServiceState.RECOVERING


def test_attempts_outside_the_window_do_not_count():
    planner = RecoveryPlanner()
    t = NOW
    for _ in range(MAX_ATTEMPTS):
        planner.plan(Service.BRIDGE, FailureCategory.UNREACHABLE, now=t)
        t += timedelta(minutes=3)
    later = t + ATTEMPT_WINDOW + timedelta(minutes=1)
    assert planner.plan(Service.BRIDGE, FailureCategory.UNREACHABLE,
                        now=later).state is ServiceState.RECOVERING


# ------------------------------------------------------------ outcomes


def test_a_restart_is_not_a_success_until_verification_passes():
    planner = RecoveryPlanner()
    planner.plan(Service.BRIDGE, FailureCategory.UNREACHABLE, now=NOW)
    assert planner.settle(Service.BRIDGE, verified_healthy=False, now=NOW) is (
        ServiceState.DEGRADED
    )
    assert planner.settle(Service.BRIDGE, verified_healthy=True, now=NOW) is (
        ServiceState.HEALTHY
    )


def test_success_clears_the_attempt_history():
    planner = RecoveryPlanner()
    planner.plan(Service.BRIDGE, FailureCategory.UNREACHABLE, now=NOW)
    planner.settle(Service.BRIDGE, verified_healthy=True, now=NOW)
    assert planner.record_for(Service.BRIDGE).attempts == []


# ---------------------------------------------- services without a repair


def test_docker_engine_is_never_repaired_automatically():
    """Section 4: detect and escalate, do not attempt unsafe repair."""
    assert POLICIES[Service.DOCKER].repair is None
    planner = RecoveryPlanner()
    d = planner.plan(Service.DOCKER, FailureCategory.ENGINE_STOPPED, now=NOW)
    assert d.state is ServiceState.NEEDS_ADMIN
    assert all(op in READ_ONLY for op in d.operations)


def test_stale_market_data_is_diagnosed_not_restarted():
    """Restarting things to fix a data gap risks breaking a healthy system."""
    assert POLICIES[Service.MARKET_DATA].repair is None
    planner = RecoveryPlanner()
    d = planner.plan(Service.MARKET_DATA, FailureCategory.STALE_DATA, now=NOW)
    assert all(op in READ_ONLY for op in d.operations)


def test_backend_policy_checks_docker_before_restarting():
    ops = POLICIES[Service.BACKEND]
    assert ops.diagnose[0] is Operation.CHECK_DOCKER
    assert ops.repair is Operation.RESTART_BACKEND


def test_no_policy_closes_positions_or_touches_trading():
    """Recovery must never become a trading incident (section 5)."""
    for policy in POLICIES.values():
        every = (*policy.diagnose, *(([policy.repair]) if policy.repair else ()),
                 *policy.verify)
        for op in every:
            assert op in set(Operation)
            assert "CLOSE" not in op.value
            assert "TRADE" not in op.value
            assert "ORDER" not in op.value
