"""Tests for the risk engine and position sizing.

These cover the paths where a bug costs real money: sizing arithmetic, the
daily-loss halt, mode gating, and the live-account guard.

Run:  python -m pytest tests/ -q
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.models import DailyStat, RiskSettings, TradingMode
from app.services import risk_engine

# XAUUSD on a typical broker: 100oz contract, $0.01 tick size, $1 tick value.
SYMBOL_INFO = {
    "point": 0.01,
    "trade_contract_size": 100.0,
    "trade_tick_size": 0.01,
    "trade_tick_value": 1.0,
    "volume_min": 0.01,
    "volume_max": 100.0,
    "volume_step": 0.01,
    "trade_stops_level": 0,
}

DEMO_ACCOUNT = {
    "balance": 10_000.0,
    "equity": 10_000.0,
    "currency": "USD",
    "trade_mode": "demo",
}

TICK = {"bid": 2500.00, "ask": 2500.30, "spread_points": 30.0}


def make_settings(**over) -> RiskSettings:
    s = RiskSettings(
        user_id=1,
        trading_mode=TradingMode.DEMO,
        bot_enabled=True,
        emergency_stop=False,
        max_risk_per_trade_pct=1.0,
        max_daily_loss_pct=2.0,
        max_trades_per_day=5,
        max_open_positions=1,
        max_lot_size=1.0,
        min_confidence=70,
        min_rr=1.5,
        max_spread_points=50,
        halted_until_date=None,
    )
    for k, v in over.items():
        setattr(s, k, v)
    return s


def make_stats(**over) -> DailyStat:
    s = DailyStat(
        user_id=1,
        day=datetime.now(timezone.utc).date(),
        trades_opened=0,
        realized_pnl=0.0,
        start_balance=10_000.0,
    )
    for k, v in over.items():
        setattr(s, k, v)
    return s


def evaluate(**over):
    kwargs = dict(
        action="BUY",
        entry=2500.00,
        stop_loss=2490.00,  # $10 stop
        take_profit=2520.00,  # $20 target -> RR 2.0
        confidence=80,
        settings_row=make_settings(),
        account=DEMO_ACCOUNT,
        symbol_info=SYMBOL_INFO,
        tick=TICK,
        open_positions=[],
        stats=make_stats(),
        server_allows_real=False,
    )
    kwargs.update(over)
    return risk_engine.evaluate(**kwargs)


# ------------------------------------------------------------- sizing


def test_position_size_matches_risk_percent():
    """1% of $10,000 = $100 risk. $10 stop at $1/tick, 0.01 tick = $1000/lot."""
    vol, risk_amount = risk_engine.position_size(
        balance=10_000.0,
        risk_pct=1.0,
        sl_distance=10.0,
        symbol_info=SYMBOL_INFO,
        max_lot=10.0,
    )
    assert risk_amount == 100.0
    # loss_per_lot = (10 / 0.01) * 1.0 = 1000  ->  100/1000 = 0.10 lots
    assert vol == pytest.approx(0.10)


def test_position_size_rounds_down_never_up():
    """Rounding up would silently exceed the user's risk limit."""
    vol, _ = risk_engine.position_size(
        balance=10_000.0,
        risk_pct=0.77,  # $77 -> 0.077 lots, must floor to 0.07
        sl_distance=10.0,
        symbol_info=SYMBOL_INFO,
        max_lot=10.0,
    )
    assert vol == pytest.approx(0.07)


def test_position_size_respects_max_lot_cap():
    vol, _ = risk_engine.position_size(
        balance=1_000_000.0,
        risk_pct=5.0,
        sl_distance=10.0,
        symbol_info=SYMBOL_INFO,
        max_lot=0.5,
    )
    assert vol == 0.5


def test_position_size_returns_zero_below_broker_minimum():
    """Never round up to volume_min — that would exceed the risk limit."""
    vol, _ = risk_engine.position_size(
        balance=100.0,  # 1% = $1 risk
        risk_pct=1.0,
        sl_distance=10.0,  # needs 0.001 lots, below the 0.01 minimum
        symbol_info=SYMBOL_INFO,
        max_lot=10.0,
    )
    assert vol == 0.0


# ------------------------------------------------------------- gating


def test_approves_a_clean_signal():
    d = evaluate()
    assert d.approved
    assert d.volume == pytest.approx(0.10)
    assert d.computed_rr == 2.0


def test_emergency_stop_blocks_everything():
    d = evaluate(settings_row=make_settings(emergency_stop=True))
    assert not d.approved
    assert "EMERGENCY STOP" in d.reasons[0]


def test_no_trade_action_is_not_executable():
    d = evaluate(action="NO_TRADE")
    assert not d.approved


def test_low_confidence_blocked():
    d = evaluate(confidence=50)
    assert not d.approved
    assert "confidence" in d.reasons[-1]


def test_wide_spread_blocked():
    d = evaluate(tick={**TICK, "spread_points": 200.0})
    assert not d.approved
    assert "spread" in d.reasons[-1]


def test_poor_risk_reward_blocked():
    # $10 stop, $5 target -> RR 0.5, below the 1.5 minimum
    d = evaluate(take_profit=2505.00)
    assert not d.approved
    assert "risk/reward" in d.reasons[-1]


def test_max_open_positions_blocked():
    d = evaluate(open_positions=[{"ticket": 1}])
    assert not d.approved
    assert "max open positions" in d.reasons[-1]


def test_max_trades_per_day_blocked():
    d = evaluate(stats=make_stats(trades_opened=5))
    assert not d.approved
    assert "max trades per day" in d.reasons[-1]


def test_daily_loss_limit_blocks():
    # 2% of 10,000 = $200 limit; realized -$250 breaches it.
    d = evaluate(stats=make_stats(realized_pnl=-250.0))
    assert not d.approved
    assert "daily loss limit" in d.reasons[-1]


def test_floating_drawdown_counts_toward_daily_limit():
    """Open losses count too, else the limit is trivially evaded."""
    d = evaluate(
        account={**DEMO_ACCOUNT, "equity": 9_700.0},  # -$300 floating
        stats=make_stats(realized_pnl=0.0),
    )
    assert not d.approved
    assert "daily loss limit" in d.reasons[-1]


def test_halt_flag_blocks():
    d = evaluate(
        settings_row=make_settings(
            halted_until_date=datetime.now(timezone.utc).date()
        )
    )
    assert not d.approved
    assert "halted" in d.reasons[-1]


def test_stale_halt_from_yesterday_does_not_block():
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    d = evaluate(settings_row=make_settings(halted_until_date=yesterday))
    assert d.approved


# ---------------------------------------------------- real-money guards


def test_real_mode_blocked_when_server_disallows():
    d = evaluate(
        settings_row=make_settings(trading_mode=TradingMode.REAL),
        server_allows_real=False,
    )
    assert not d.approved
    assert "ALLOW_REAL_TRADING" in d.reasons[-1]


def test_live_account_refused_in_demo_mode():
    """Defence in depth: the broker says LIVE, our mode says DEMO."""
    d = evaluate(
        account={**DEMO_ACCOUNT, "trade_mode": "real"},
        settings_row=make_settings(trading_mode=TradingMode.DEMO),
    )
    assert not d.approved
    assert "LIVE" in d.reasons[-1]


def test_real_mode_on_live_account_allowed_when_fully_armed():
    d = evaluate(
        account={**DEMO_ACCOUNT, "trade_mode": "real"},
        settings_row=make_settings(trading_mode=TradingMode.REAL),
        server_allows_real=True,
    )
    assert d.approved


# ------------------------------------------------------- order sanity


def test_buy_with_inverted_stops_rejected():
    d = evaluate(action="BUY", stop_loss=2510.00, take_profit=2490.00)
    assert not d.approved
    assert "BUY requires" in d.reasons[-1]


def test_sell_direction_validated():
    d = evaluate(action="SELL", entry=2500.0, stop_loss=2510.0, take_profit=2470.0)
    assert d.approved
    d2 = evaluate(action="SELL", entry=2500.0, stop_loss=2490.0, take_profit=2470.0)
    assert not d2.approved


def test_missing_levels_rejected():
    assert not evaluate(stop_loss=None).approved
    assert not evaluate(take_profit=None).approved


def test_broker_min_stop_distance_enforced():
    d = evaluate(
        stop_loss=2499.90,  # 0.10 away
        take_profit=2500.50,
        symbol_info={**SYMBOL_INFO, "trade_stops_level": 50},  # 50 * 0.01 = 0.50
    )
    assert not d.approved
    assert "broker minimum" in d.reasons[-1]


# ------------------------------------------------- requested volume


def test_requested_volume_cannot_exceed_risk_based_size():
    d = evaluate(requested_volume=0.50)  # risk-based size is 0.10
    assert not d.approved
    assert "exceeds risk-based size" in d.reasons[-1]


def test_requested_volume_below_risk_size_is_honoured():
    d = evaluate(requested_volume=0.05)
    assert d.approved
    assert d.volume == pytest.approx(0.05)


def test_requested_volume_cannot_exceed_hard_lot_cap():
    d = evaluate(
        requested_volume=2.0, settings_row=make_settings(max_lot_size=1.0)
    )
    assert not d.approved
    assert "max lot size" in d.reasons[-1]


# ------------------------------------------------------------- halting


def test_should_halt_for_day():
    s = make_settings(max_daily_loss_pct=2.0)
    stats = make_stats(realized_pnl=-150.0)
    # -150 realized, -60 floating = -210 vs a -200 limit
    assert risk_engine.should_halt_for_day(stats, s, equity=9_940.0, balance=10_000.0)
    assert not risk_engine.should_halt_for_day(
        stats, s, equity=10_000.0, balance=10_000.0
    )
