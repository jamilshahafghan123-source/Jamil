"""Bot state derivation (section 17)."""

from app.services.bot_status import BotState, derive


def base(**over):
    body = dict(bot_enabled=True, emergency_stop=False, trading_mode="DEMO")
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
