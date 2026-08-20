"""Broker registry and adapter contract (sections 40-44).

These tests exist to stop the platform claiming more than it does.
"""

import inspect

import pytest

from app.services import brokers
from app.services.broker_adapter import BrokerAdapter
from app.services.brokers import AuthMethod, BrokerStatus


def test_only_implemented_brokers_are_connectable():
    """The list of real connections is exactly two, and both are real.

    A broker becomes connectable only when a connector for it has been
    written. This assertion is what forces that to be a deliberate act.
    """
    assert brokers.connectable_keys() == ("J_GOLD_DEMO", "MT5_BRIDGE")


def test_every_other_broker_is_marked_forthcoming():
    for broker in brokers.all_brokers():
        if broker.connectable:
            continue
        assert broker.status in (
            BrokerStatus.COMING_SOON, BrokerStatus.UNSUPPORTED
        ), broker.key


def test_no_broker_authenticates_with_a_password():
    """A customer's broker password must never reach this application.

    AuthMethod has no PASSWORD member at all, so this checks the enum
    itself rather than only the current rows: a future broker cannot be
    added with password auth without someone deliberately widening the
    enum and failing this test.
    """
    assert not hasattr(AuthMethod, "PASSWORD")
    assert "PASSWORD" not in {m.value for m in AuthMethod}
    for broker in brokers.all_brokers():
        assert broker.auth_method in AuthMethod


def test_forthcoming_brokers_claim_no_capabilities():
    """An unimplemented connector cannot advertise what it can do."""
    for broker in brokers.all_brokers():
        if not broker.connectable:
            assert broker.capabilities == (), broker.key


def test_connecting_a_forthcoming_broker_is_refused():
    with pytest.raises(brokers.BrokerNotConnectableError):
        brokers.require_connectable("OANDA")


def test_unknown_broker_is_refused():
    with pytest.raises(brokers.UnknownBrokerError):
        brokers.require_connectable("NOT_A_BROKER")


def test_broker_keys_are_unique():
    keys = [b.key for b in brokers.all_brokers()]
    assert len(keys) == len(set(keys))


def test_funded_accounts_are_not_claimed_as_supported():
    """The most damaging false claim this platform could make."""
    status = brokers.funded_account_status()
    assert status["supported"] is False
    assert status["status"] == "COMING_SOON"
    assert "credentials" in status["detail"].lower()


def test_registry_never_carries_a_secret():
    """No token, key or password may live in a browser-visible registry."""
    for broker in brokers.all_brokers():
        payload = broker.as_dict()
        blob = " ".join(str(v) for v in payload.values()).lower()
        for forbidden in ("token=", "secret", "password", "api_key", "apikey"):
            assert forbidden not in blob, f"{broker.key} leaked {forbidden}"
        assert set(payload) == {
            "key", "display_name", "category", "status", "auth_method",
            "connectable", "capabilities", "note",
        }


# ------------------------------------------------------ adapter contract

def test_adapter_contract_covers_the_whole_surface():
    """Section 41's method list, so a venue cannot be half-implemented."""
    required = {
        "health", "account", "symbols", "tick", "bars", "positions",
        "place_order", "close_position", "funding_url",
    }
    assert required <= set(dir(BrokerAdapter))


def test_demo_execution_satisfies_the_adapter_shape_without_a_broker():
    """The internal simulator has no broker import to reach at all.

    This is the isolation rule restated at the adapter layer: whatever
    shape the demo venue takes, it must not acquire a broker client on
    the way to satisfying it.
    """
    from app.services import demo_execution

    source = inspect.getsource(demo_execution)
    tree = compile(source, "demo_execution", "exec", flags=0, dont_inherit=True)
    names = {name for name in tree.co_names}
    for forbidden in ("mt5", "executor", "bridge"):
        assert forbidden not in names, f"demo_execution referenced {forbidden}"
