"""Broker registry and adapter contract (sections 40-44).

WHAT THIS FILE REFUSES TO DO
----------------------------
It does not claim an integration that does not exist. Every broker below
carries a status, and only a broker with a real, documented connector
this project has actually implemented may be anything other than
COMING_SOON. Listing a name is not a claim of partnership, endorsement or
support; it is a statement of where that broker sits in the roadmap.

Two brokers are real today:

    J_GOLD_DEMO   the internal simulator — virtual money, no counterparty
    MT5_BRIDGE    the existing MetaTrader 5 bridge

Everything else is declared so the connection centre can answer "not yet"
honestly instead of pretending the name is unknown.

CREDENTIALS
-----------
Nothing here stores, requests or transports a password. `auth_method`
records how a broker expects to be connected — almost always OAuth or an
API token issued by the broker itself — and the funding flow is always a
redirect to the broker's own site. J Gold AI never custodies customer
trading money and never asks a customer to type a broker password into
this application.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class BrokerStatus(str, enum.Enum):
    """How far a broker actually is, with nothing flattering implied.

    CONNECTED    implemented, and this installation is configured for it
    AVAILABLE    implemented and ready to configure
    COMING_SOON  declared, not yet implemented
    UNSUPPORTED  will not be offered
    """

    CONNECTED = "CONNECTED"
    AVAILABLE = "AVAILABLE"
    COMING_SOON = "COMING_SOON"
    UNSUPPORTED = "UNSUPPORTED"


class BrokerCategory(str, enum.Enum):
    INTERNAL = "INTERNAL"
    FOREX_CFD = "FOREX_CFD"
    MULTI_ASSET = "MULTI_ASSET"
    STOCKS = "STOCKS"
    CRYPTO = "CRYPTO"
    FUTURES = "FUTURES"
    MT5 = "MT5"
    FUNDED = "FUNDED"


class AuthMethod(str, enum.Enum):
    """How a connection is authorised. NONE is the internal simulator.

    There is deliberately no PASSWORD member. A broker that could only be
    connected by collecting a customer's login would not be added; it
    would be left COMING_SOON until it offers something better.
    """

    NONE = "NONE"
    OAUTH = "OAUTH"
    API_TOKEN = "API_TOKEN"
    BROKER_HOSTED = "BROKER_HOSTED"
    #: The MT5 bridge authenticates host-to-host with a token held only on
    #: the bridge machine. The customer never sees or supplies it.
    BRIDGE_TOKEN = "BRIDGE_TOKEN"


@dataclass(frozen=True, slots=True)
class Broker:
    key: str
    display_name: str
    category: BrokerCategory
    status: BrokerStatus
    auth_method: AuthMethod
    #: What this connection can do once established. Empty while forthcoming.
    capabilities: tuple[str, ...] = ()
    #: Plain-language note shown in the connection centre.
    note: str = ""

    @property
    def connectable(self) -> bool:
        return self.status in (BrokerStatus.CONNECTED, BrokerStatus.AVAILABLE)

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "category": self.category.value,
            "status": self.status.value,
            "auth_method": self.auth_method.value,
            "connectable": self.connectable,
            "capabilities": list(self.capabilities),
            "note": self.note,
        }


_BROKERS: tuple[Broker, ...] = (
    Broker(
        key="J_GOLD_DEMO", display_name="J Gold AI Demo",
        category=BrokerCategory.INTERNAL, status=BrokerStatus.CONNECTED,
        auth_method=AuthMethod.NONE,
        capabilities=("bars", "tick", "positions", "place_order", "close"),
        note="Virtual money inside J Gold AI. No broker, no counterparty, "
             "and no funding — the balance is reset, never deposited.",
    ),
    Broker(
        key="MT5_BRIDGE", display_name="MetaTrader 5 (own bridge)",
        category=BrokerCategory.MT5, status=BrokerStatus.AVAILABLE,
        auth_method=AuthMethod.BRIDGE_TOKEN,
        capabilities=("health", "account", "bars", "tick", "positions"),
        note="Connects to a MetaTrader 5 terminal you already run. The "
             "bridge token stays on the bridge host and is never entered "
             "here. Real order placement stays disabled by its own latch.",
    ),
)

_FORTHCOMING = (
    # Forex / CFD
    ("OANDA", "OANDA", BrokerCategory.FOREX_CFD, AuthMethod.API_TOKEN),
    ("PEPPERSTONE", "Pepperstone", BrokerCategory.FOREX_CFD, AuthMethod.OAUTH),
    ("FOREX_COM", "FOREX.com", BrokerCategory.FOREX_CFD, AuthMethod.OAUTH),
    ("FXCM", "FXCM", BrokerCategory.FOREX_CFD, AuthMethod.API_TOKEN),
    ("THINKMARKETS", "ThinkMarkets", BrokerCategory.FOREX_CFD, AuthMethod.OAUTH),
    ("EIGHTCAP", "Eightcap", BrokerCategory.FOREX_CFD, AuthMethod.OAUTH),
    ("TICKMILL", "Tickmill", BrokerCategory.FOREX_CFD, AuthMethod.OAUTH),
    ("VANTAGE", "Vantage", BrokerCategory.FOREX_CFD, AuthMethod.OAUTH),
    ("FXPRO", "FxPro", BrokerCategory.FOREX_CFD, AuthMethod.OAUTH),
    ("CAPITAL_COM", "Capital.com", BrokerCategory.FOREX_CFD, AuthMethod.API_TOKEN),
    ("CMC_MARKETS", "CMC Markets", BrokerCategory.FOREX_CFD, AuthMethod.OAUTH),
    ("CITY_INDEX", "City Index", BrokerCategory.FOREX_CFD, AuthMethod.OAUTH),
    # Multi-asset
    ("IG", "IG", BrokerCategory.MULTI_ASSET, AuthMethod.API_TOKEN),
    ("SAXO", "Saxo", BrokerCategory.MULTI_ASSET, AuthMethod.OAUTH),
    ("IBKR", "Interactive Brokers", BrokerCategory.MULTI_ASSET, AuthMethod.OAUTH),
    # Stocks
    ("TRADESTATION", "TradeStation", BrokerCategory.STOCKS, AuthMethod.OAUTH),
    ("WEBULL", "Webull", BrokerCategory.STOCKS, AuthMethod.OAUTH),
    # Crypto
    ("KRAKEN", "Kraken", BrokerCategory.CRYPTO, AuthMethod.API_TOKEN),
)

_BROKERS = _BROKERS + tuple(
    Broker(
        key=key, display_name=name, category=category,
        status=BrokerStatus.COMING_SOON, auth_method=auth,
        note="Not connected yet. Listing a broker is not a claim of "
             "partnership or support; it is where it sits on the roadmap.",
    )
    for key, name, category, auth in _FORTHCOMING
)

_BY_KEY = {b.key: b for b in _BROKERS}


class UnknownBrokerError(Exception):
    """The key is not in the registry."""


class BrokerNotConnectableError(Exception):
    """The broker exists but has no implemented connector."""


def get(key: str) -> Broker:
    try:
        return _BY_KEY[(key or "").upper()]
    except KeyError:
        raise UnknownBrokerError(f"Unknown broker: {key!r}") from None


def all_brokers() -> tuple[Broker, ...]:
    return _BROKERS


def connectable_keys() -> tuple[str, ...]:
    return tuple(b.key for b in _BROKERS if b.connectable)


def by_category() -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for broker in _BROKERS:
        grouped.setdefault(broker.category.value, []).append(broker.as_dict())
    return grouped


def require_connectable(key: str) -> Broker:
    """The only door for anything that intends to open a connection."""
    broker = get(key)
    if not broker.connectable:
        raise BrokerNotConnectableError(
            f"{broker.display_name} is not available to connect yet."
        )
    return broker


def funded_account_status() -> dict:
    """Funded / prop accounts (section 42).

    Deliberately a single honest statement rather than a list of firm
    names. A funded account is someone else's capital under someone else's
    rules; claiming support without a documented connector would be the
    most damaging false claim this platform could make.
    """
    return {
        "supported": False,
        "status": "COMING_SOON",
        "detail": (
            "Funded and prop accounts are not connected. J Gold AI will "
            "support them only through a firm's own documented API, and "
            "will never ask you for trading-account credentials to reach "
            "one."
        ),
    }
