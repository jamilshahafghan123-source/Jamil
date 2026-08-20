"""SAFE MODE (section 84): fail closed, but never lock customers out."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.safe_mode import (
    SAFE_MODE_BANNER,
    SafeModeReason,
    evaluate,
)

NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)
FRESH = NOW - timedelta(seconds=5)


def healthy(**overrides):
    kwargs = dict(bridge_connected=True, last_tick_at=FRESH, now=NOW)
    kwargs.update(overrides)
    return evaluate(**kwargs)


def test_healthy_system_is_not_in_safe_mode():
    state = healthy()
    assert state.active is False
    assert state.reasons == ()
    assert state.blocks_automated_trading is False


def test_stale_market_data_trips_safe_mode():
    state = healthy(last_tick_at=NOW - timedelta(minutes=5))
    assert state.active is True
    assert SafeModeReason.STALE_MARKET_DATA in state.reasons


def test_missing_prices_trips_safe_mode():
    state = healthy(last_tick_at=None)
    assert SafeModeReason.MISSING_PRICES in state.reasons


def test_tick_from_the_future_is_treated_as_untrustworthy():
    """A clock skew must not read as the freshest possible data."""
    state = healthy(last_tick_at=NOW + timedelta(minutes=5))
    assert SafeModeReason.STALE_MARKET_DATA in state.reasons


def test_disconnected_bridge_trips_safe_mode():
    state = healthy(bridge_connected=False)
    assert SafeModeReason.BROKER_UNAVAILABLE in state.reasons


def test_auth_failure_is_distinct_from_an_outage():
    """Section 83: a bad token is a credential problem, not a blip."""
    state = healthy(bridge_connected=False, bridge_authenticated=False)
    assert SafeModeReason.BRIDGE_AUTH_FAILURE in state.reasons
    assert SafeModeReason.BROKER_UNAVAILABLE not in state.reasons


@pytest.mark.parametrize(
    "override,expected",
    [
        ({"risk_engine_available": False}, SafeModeReason.RISK_ENGINE_UNAVAILABLE),
        ({"database_healthy": False}, SafeModeReason.DATABASE_DEGRADED),
        (
            {"instrument_metadata_available": False},
            SafeModeReason.INSTRUMENT_METADATA_UNAVAILABLE,
        ),
        ({"candles_consistent": False}, SafeModeReason.INCONSISTENT_CANDLES),
        ({"recent_execution_failures": 3}, SafeModeReason.EXECUTION_FAILURE),
    ],
)
def test_each_trigger_trips_safe_mode(override, expected):
    assert expected in healthy(**override).reasons


def test_execution_failures_below_threshold_do_not_trip():
    assert healthy(recent_execution_failures=2).active is False


def test_multiple_faults_are_all_reported():
    state = healthy(bridge_connected=False, last_tick_at=None, database_healthy=False)
    assert len(state.reasons) == 3


def test_safe_mode_never_blocks_account_viewing():
    """Section 84: login, history and support stay available."""
    state = healthy(bridge_connected=False, last_tick_at=None)
    assert state.active is True
    assert state.blocks_account_viewing is False


def test_customer_message_is_plain_and_present_for_every_reason():
    """Every trigger must have safe wording — no raw exceptions leaked."""
    for reason in SafeModeReason:
        state = _state_forcing(reason)
        assert state.customer_messages, reason
        joined = " ".join(state.customer_messages).lower()
        for leak in ("traceback", "exception", "token", "secret", "password"):
            assert leak not in joined, f"{reason} message leaks {leak!r}"


def test_banner_matches_the_specified_wording():
    assert healthy(last_tick_at=None).banner == SAFE_MODE_BANNER
    assert SAFE_MODE_BANNER == "AUTOMATED TRADING TEMPORARILY PAUSED"


def _state_forcing(reason: SafeModeReason):
    mapping = {
        SafeModeReason.STALE_MARKET_DATA: {"last_tick_at": NOW - timedelta(hours=1)},
        SafeModeReason.MISSING_PRICES: {"last_tick_at": None},
        SafeModeReason.INCONSISTENT_CANDLES: {"candles_consistent": False},
        SafeModeReason.RISK_ENGINE_UNAVAILABLE: {"risk_engine_available": False},
        SafeModeReason.BROKER_UNAVAILABLE: {"bridge_connected": False},
        SafeModeReason.BRIDGE_AUTH_FAILURE: {"bridge_authenticated": False},
        SafeModeReason.EXECUTION_FAILURE: {"recent_execution_failures": 5},
        SafeModeReason.DATABASE_DEGRADED: {"database_healthy": False},
        SafeModeReason.INSTRUMENT_METADATA_UNAVAILABLE: {
            "instrument_metadata_available": False
        },
    }
    return healthy(**mapping[reason])
