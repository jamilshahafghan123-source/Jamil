"""Bot state derivation (section 17)."""

from datetime import datetime, timedelta, timezone

from app.services.bot_status import BotState, derive


#: A loop that is up and cycling on time. Every case below is about what
#: the bot DECIDES, which presupposes something is deciding — so the
#: healthy heartbeat is the default and the stalled cases state it.
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
HEALTHY = dict(
    started_at=NOW - timedelta(hours=2),
    last_cycle_at=NOW - timedelta(seconds=20),
    interval_seconds=60,
    now=NOW,
)


def base(**over):
    body = dict(bot_enabled=True, emergency_stop=False, trading_mode="DEMO")
    body.update(HEALTHY)
    body.update(over)
    return derive(**body)


def test_a_switched_off_bot_reports_off():
    assert base(bot_enabled=False).state is BotState.OFF


def test_an_enabled_bot_with_nothing_wrong_waits_for_a_setup():
    """Not RUNNING — the honest state of a bot with no qualifying setup."""
    status = base()
    assert status.state is BotState.WAITING_FOR_SETUP
    assert "No qualifying setup" in status.detail


def test_the_most_blocking_reason_wins():
    """An emergency stop over a data outage is an emergency stop.

    Reporting the last condition checked would send the customer to fix
    the wrong thing.
    """
    status = base(emergency_stop=True, market_data_ok=False,
                  safe_mode_active=True, maintenance_active=True)
    assert status.state is BotState.EMERGENCY_STOP


def test_safe_mode_and_maintenance_outrank_the_bot_switch():
    """A blocked platform is not merely an off bot."""
    assert base(bot_enabled=False, maintenance_active=True).state \
        is BotState.MAINTENANCE_MODE
    assert base(bot_enabled=False, safe_mode_active=True).state \
        is BotState.SAFE_MODE


def test_a_bot_without_prices_is_not_waiting_for_a_setup():
    status = base(market_data_ok=False)
    assert status.state is BotState.MARKET_DATA_ERROR


def test_a_broker_outage_only_matters_where_a_broker_is_used():
    """The internal demo has no broker to lose."""
    demo = base(broker_connected=False, venue_requires_broker=False)
    assert demo.state is BotState.WAITING_FOR_SETUP
    brokered = base(broker_connected=False, venue_requires_broker=True)
    assert brokered.state is BotState.BROKER_DISCONNECTED


def test_manual_mode_reports_ready_rather_than_running():
    """Enabled but not permitted to act is not the same as running."""
    status = base(trading_mode="MANUAL")
    assert status.state is BotState.READY
    assert "MANUAL" in status.detail


def test_an_open_position_is_reported_as_such():
    status = base(open_positions=2)
    assert status.state is BotState.POSITION_OPEN
    assert "2 open positions" in status.detail


def test_a_risk_block_is_surfaced_with_its_reason():
    status = base(risk_blocked_reason="daily loss limit reached")
    assert status.state is BotState.BLOCKED_BY_RISK
    assert status.detail == "daily loss limit reached"


def test_no_state_claims_running_without_evidence():
    """RUNNING is never produced by `derive`.

    There is no observation that means "running" on its own — a bot is
    either waiting, holding a position, or blocked. The state exists for
    completeness but must not be handed out as a decoration.
    """
    observations = [
        base(), base(open_positions=1), base(trading_mode="MANUAL"),
        base(bot_enabled=False), base(emergency_stop=True),
        base(safe_mode_active=True), base(maintenance_active=True),
        base(market_data_ok=False),
        base(broker_connected=False, venue_requires_broker=True),
        base(risk_blocked_reason="x"),
    ]
    assert all(s.state is not BotState.RUNNING for s in observations)


def test_blocked_states_are_reported_as_blocked():
    for status in (base(bot_enabled=False), base(emergency_stop=True),
                   base(safe_mode_active=True), base(maintenance_active=True)):
        assert status.as_dict()["blocked"] is True
    assert base().as_dict()["blocked"] is False


def test_a_paused_bot_reports_paused():
    status = base(paused=True)
    assert status.state is BotState.PAUSED
    assert "still managed" in status.detail


def test_pause_outranks_the_operational_states_below_it():
    """A paused bot is not "waiting for a setup" — it was told not to take one."""
    assert base(paused=True, open_positions=3).state is BotState.PAUSED
    assert base(paused=True, risk_blocked_reason="spread").state is BotState.PAUSED
    assert base(paused=True, trading_mode="MANUAL").state is BotState.PAUSED


def test_pause_does_not_talk_over_the_platform_blocks():
    """An account under an emergency stop is not described as "paused"."""
    assert base(paused=True, emergency_stop=True).state is BotState.EMERGENCY_STOP
    assert base(paused=True, maintenance_active=True).state is BotState.MAINTENANCE_MODE
    assert base(paused=True, safe_mode_active=True).state is BotState.SAFE_MODE
    assert base(paused=True, bot_enabled=False).state is BotState.OFF


def test_a_paused_bot_is_reported_as_blocked():
    assert base(paused=True).as_dict()["blocked"] is True


# ------------------------------------- is anything actually running? (§17)


def test_a_loop_that_never_started_is_not_waiting_for_a_setup():
    """The failure this exists to catch.

    Every other check reports on what the bot WOULD decide. None of them
    notices that nothing is deciding, so a loop that crashed at startup
    reported "waiting for a setup" — the most reassuring possible
    description of a bot that is not running.
    """
    status = base(started_at=None, last_cycle_at=None)
    assert status.state is BotState.STALLED
    assert "not running" in status.detail


def test_a_loop_that_started_but_never_cycled_is_starting_then_stalled():
    starting = base(started_at=NOW - timedelta(seconds=30), last_cycle_at=None)
    assert starting.state is BotState.STARTING

    stalled = base(started_at=NOW - timedelta(hours=1), last_cycle_at=None)
    assert stalled.state is BotState.STALLED
    assert "not completed a cycle" in stalled.detail


def test_a_late_cycle_is_stalled_and_says_how_late():
    status = base(last_cycle_at=NOW - timedelta(minutes=30))
    assert status.state is BotState.STALLED
    assert "1800 seconds ago" in status.detail


def test_one_slow_cycle_is_not_an_alarm():
    """Three intervals of grace, so a single slow scan is not a fault."""
    assert base(last_cycle_at=NOW - timedelta(seconds=100)).state \
        is BotState.WAITING_FOR_SETUP


def test_a_stalled_loop_outranks_a_pause_but_not_the_switch():
    """A pause the bot is not around to honour is a fault, not a pause."""
    assert base(paused=True, started_at=None).state is BotState.STALLED
    # But a bot that is switched off is off, not stalled.
    assert base(bot_enabled=False, started_at=None).state is BotState.OFF


def test_stalled_is_reported_as_blocked():
    assert base(started_at=None).as_dict()["blocked"] is True
