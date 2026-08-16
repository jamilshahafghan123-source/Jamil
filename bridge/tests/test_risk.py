"""Risk policy: the limits, and that nothing reaches the terminal once one trips."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.config import Settings
from tests.conftest import AUTH

# XAUUSD in the stub: ask 2401.80, bid 2401.50, tick 0.01 = 1.00 USD per lot,
# so a 10.00 stop distance on 0.10 lots risks 100 USD of a 10,000 balance.
GOLD = "XAUUSD"


@pytest.fixture
def risk_client(client_factory):
    """A client running the shipped policy (RISK_ENABLED defaults to on)."""
    return client_factory(RISK_ENABLED="true")


def order(symbol=GOLD, **overrides):
    payload = {
        "symbol": symbol,
        "side": "buy",
        "volume": 0.10,
        "type": "market",
        "sl": 2397.80,  # 4.00 away -> 40 USD -> 0.40% of balance
        "tp": 2410.00,
    }
    payload.update(overrides)
    return payload


def test_shipped_defaults_match_the_policy():
    fields = Settings.model_fields
    assert fields["risk_enabled"].default is True
    assert fields["risk_per_trade_pct"].default == 0.5
    assert fields["risk_max_daily_loss_pct"].default == 2.0
    assert fields["risk_max_positions"].default == 2
    assert fields["risk_max_lot"].default == 0.10
    assert fields["risk_require_sl"].default is True
    assert fields["risk_require_tp"].default is True
    assert fields["risk_allowed_symbols"].default == "XAUUSD"


def test_compliant_order_passes_and_reports_its_risk(risk_client, mt5):
    response = risk_client.post("/api/v1/orders", json=order(), headers=AUTH)
    assert response.status_code == 201

    assessment = response.json()["risk"]
    assert assessment["risk_money"] == 40.0
    assert assessment["risk_pct"] == 0.4
    assert assessment["risk_budget"] == 50.0
    assert assessment["open_positions"] == 0
    assert len(mt5.state.sent_requests) == 1


def test_symbol_outside_the_allowlist_is_refused(risk_client, mt5):
    response = risk_client.post(
        "/api/v1/orders",
        json=order(symbol="EURUSD", sl=1.08, tp=1.09),
        headers=AUTH,
    )
    assert response.status_code == 403
    body = response.json()
    assert body["error"] == "risk_rejected"
    assert body["details"]["rule"] == "allowed_symbols"
    assert body["details"]["allowed_symbols"] == [GOLD]
    assert mt5.state.sent_requests == []


@pytest.mark.parametrize("missing,rule", [("sl", "require_sl"), ("tp", "require_tp")])
def test_protective_levels_are_mandatory(risk_client, mt5, missing, rule):
    payload = order()
    payload.pop(missing)
    response = risk_client.post("/api/v1/orders", json=payload, headers=AUTH)
    assert response.status_code == 403
    assert response.json()["details"]["rule"] == rule
    assert mt5.state.sent_requests == []


def test_lot_above_the_cap_is_refused(risk_client, mt5):
    response = risk_client.post("/api/v1/orders", json=order(volume=0.25), headers=AUTH)
    assert response.status_code == 403
    details = response.json()["details"]
    assert details["rule"] == "max_lot"
    assert details["max_lot"] == 0.10
    assert mt5.state.sent_requests == []


def test_lot_exactly_at_the_cap_is_allowed(risk_client):
    assert risk_client.post("/api/v1/orders", json=order(volume=0.10), headers=AUTH).status_code == 201


def test_stop_too_wide_breaches_risk_per_trade(risk_client, mt5):
    # 10.00 away on 0.10 lots = 100 USD = 1% of balance, over the 0.5% budget.
    response = risk_client.post("/api/v1/orders", json=order(sl=2391.80), headers=AUTH)
    assert response.status_code == 403
    details = response.json()["details"]
    assert details["rule"] == "risk_per_trade"
    assert details["risk_money"] == 100.0
    assert details["risk_pct"] == 1.0
    assert details["risk_budget"] == 50.0
    # 0.05 lots is the largest size that still fits inside 0.5%.
    assert details["suggested_volume"] == 0.05
    assert mt5.state.sent_requests == []


def test_position_limit_blocks_the_third_order(risk_client, mt5):
    for _ in range(2):
        assert risk_client.post("/api/v1/orders", json=order(), headers=AUTH).status_code == 201
    assert len(mt5.state.positions) == 2

    response = risk_client.post("/api/v1/orders", json=order(), headers=AUTH)
    assert response.status_code == 403
    details = response.json()["details"]
    assert details["rule"] == "max_positions"
    assert details["open_positions"] == 2
    assert len(mt5.state.sent_requests) == 2  # the rejected one never went out


def test_daily_loss_limit_blocks_new_orders(risk_client, mt5):
    _seed_closed_loss(mt5, -250.0)  # -2.44% of the day's opening balance

    response = risk_client.post("/api/v1/orders", json=order(), headers=AUTH)
    assert response.status_code == 403
    details = response.json()["details"]
    assert details["rule"] == "max_daily_loss"
    assert details["max_daily_loss_pct"] == 2.0
    assert mt5.state.sent_requests == []


def test_loss_inside_the_daily_budget_still_trades(risk_client, mt5):
    _seed_closed_loss(mt5, -100.0)  # -1.01%, still inside the 2% budget
    assert risk_client.post("/api/v1/orders", json=order(), headers=AUTH).status_code == 201


def test_floating_loss_counts_towards_the_daily_limit(risk_client, mt5):
    assert risk_client.post("/api/v1/orders", json=order(), headers=AUTH).status_code == 201
    ticket, position = next(iter(mt5.state.positions.items()))
    mt5.state.positions[ticket] = position._replace(profit=-300.0)

    response = risk_client.post("/api/v1/orders", json=order(), headers=AUTH)
    assert response.status_code == 403
    assert response.json()["details"]["rule"] == "max_daily_loss"


def test_balance_operations_do_not_count_as_trading_losses(risk_client, mt5):
    _seed_closed_loss(mt5, -500.0, deal_type=2)  # a withdrawal, not a trade
    assert risk_client.post("/api/v1/orders", json=order(), headers=AUTH).status_code == 201


def test_wide_spread_blocks_a_market_order(risk_client, mt5):
    bid, _ = mt5.state.quotes[GOLD]
    mt5.state.quotes[GOLD] = (bid, bid + 1.00)  # 100 points on a 0.01 point size

    response = risk_client.post("/api/v1/orders", json=order(), headers=AUTH)
    assert response.status_code == 403
    details = response.json()["details"]
    assert details["rule"] == "max_spread"
    assert details["spread_points"] == 100.0
    assert details["max_spread_points"] == 50
    assert mt5.state.sent_requests == []


def test_wide_spread_does_not_block_a_pending_order(risk_client, mt5):
    """A pending order fills later, at a spread nobody can measure now."""
    bid, _ = mt5.state.quotes[GOLD]
    mt5.state.quotes[GOLD] = (bid, bid + 1.00)

    pending = order(type="limit", price=2380.00, sl=2376.00, tp=2392.00)
    assert risk_client.post("/api/v1/orders", json=pending, headers=AUTH).status_code == 201


def test_spread_gate_can_be_disabled(client_factory, mt5):
    bid, _ = mt5.state.quotes[GOLD]
    mt5.state.quotes[GOLD] = (bid, bid + 1.00)
    lenient = client_factory(RISK_ENABLED="true", RISK_MAX_SPREAD_POINTS="0")
    assert lenient.post("/api/v1/orders", json=order(), headers=AUTH).status_code == 201


def test_insufficient_margin_is_refused(risk_client, mt5):
    # 0.10 lots of gold at ~2400 on 1:100 leverage needs ~240; leave less free.
    mt5.state.account = mt5.state.account._replace(margin_free=50.0)

    response = risk_client.post("/api/v1/orders", json=order(), headers=AUTH)
    assert response.status_code == 403
    details = response.json()["details"]
    assert details["rule"] == "margin"
    assert details["free_margin"] == 50.0
    assert details["required_margin"] > 50.0
    assert mt5.state.sent_requests == []


def test_margin_is_reported_on_an_accepted_order(risk_client):
    body = risk_client.post("/api/v1/orders", json=order(), headers=AUTH).json()
    assert body["risk"]["required_margin"] > 0
    assert body["risk"]["free_margin_after"] > 0


def test_dry_run_is_judged_by_the_same_policy(risk_client, mt5):
    response = risk_client.post(
        "/api/v1/orders", json=order(volume=0.25, dry_run=True), headers=AUTH
    )
    assert response.status_code == 403
    assert response.json()["details"]["rule"] == "max_lot"
    assert mt5.state.sent_requests == []


def test_risk_endpoint_reports_the_live_budget(risk_client, mt5):
    _seed_closed_loss(mt5, -100.0)
    body = risk_client.get("/api/v1/risk", headers=AUTH).json()

    assert body["enabled"] is True
    assert body["daily"]["realized"] == -100.0
    assert body["daily_loss"] == 100.0
    assert body["opening_balance"] == 10_100.0
    assert body["daily_loss_budget"] == 202.0
    assert body["daily_loss_remaining"] == 102.0
    assert body["daily_loss_limit_hit"] is False
    assert body["positions_remaining"] == 2
    assert body["limits"] == {
        "risk_per_trade_pct": 0.5,
        "max_daily_loss_pct": 2.0,
        "max_positions": 2,
        "max_lot": 0.10,
        "require_sl": True,
        "require_tp": True,
        "allowed_symbols": [GOLD],
        "max_spread_points": 50,
        "check_margin": True,
        "demo_only": True,
    }


def test_policy_can_be_switched_off(client_factory, mt5):
    """RISK_ENABLED=false leaves only the older bridge-level guards."""
    unguarded = client_factory(RISK_ENABLED="false")
    payload = order(symbol="EURUSD", volume=0.5, sl=None, tp=None)
    payload.pop("sl")
    payload.pop("tp")
    assert unguarded.post("/api/v1/orders", json=payload, headers=AUTH).status_code == 201


def _seed_closed_loss(mt5, profit: float, deal_type: int = 0) -> None:
    mt5.state.deals.append(
        mt5.DealInfo(
            ticket=mt5.state.ticket(),
            order=mt5.state.ticket(),
            time=int(datetime.now(tz=timezone.utc).timestamp()),
            symbol=GOLD,
            type=deal_type,
            volume=0.10,
            price=2400.0,
            profit=profit,
            swap=0.0,
            commission=0.0,
            comment="seeded",
        )
    )
