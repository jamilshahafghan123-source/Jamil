"""The BrokerAdapter contract (section 41).

One interface, so a second venue is an implementation rather than a fork
of every call site. The internal demo and the MT5 bridge are separate
implementations of it and share nothing but this shape — which is the
point: the demo adapter physically cannot reach a broker, because it has
no broker to reach.

`place_order` and `close_position` are the only methods that can move
anything, and every implementation of them stays behind the central risk
manager and the existing safe-mode, maintenance and emergency-stop gates.
Implementing this protocol grants no authority on its own.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class BrokerAdapter(Protocol):
    """What every venue must be able to answer.

    A method a venue genuinely cannot provide raises NotImplementedError
    rather than returning an empty or invented result. "I cannot tell you"
    and "the answer is nothing" are different answers, and a trading
    platform that confuses them will eventually confuse them about a
    position.
    """

    #: Registry key. Must match a key in services.brokers.
    key: str

    #: Whether orders from this adapter can ever reach a real counterparty.
    #: The internal simulator sets this False and nothing may flip it.
    real_money: bool

    async def health(self) -> dict:
        """Connectivity and whether the venue is usable right now."""
        ...

    async def account(self) -> dict:
        """Balance, equity, margin. Currency always stated explicitly."""
        ...

    async def symbols(self) -> list[dict]:
        """Instruments this venue can actually price."""
        ...

    async def tick(self, symbol: str) -> dict:
        """Current bid/ask. Raises rather than guessing a stale price."""
        ...

    async def bars(self, symbol: str, timeframe: str, count: int) -> list[dict]:
        """Historical candles, oldest first."""
        ...

    async def positions(self) -> list[dict]:
        """Open positions on this venue only."""
        ...

    async def place_order(self, **kwargs) -> dict:
        """Open a position. Always downstream of the central risk manager."""
        ...

    async def close_position(self, position_id: int | str) -> dict:
        """Close a position. Permitted in states that block opening."""
        ...

    def funding_url(self) -> str | None:
        """Where the customer funds this account.

        Always the broker's own page, never a J Gold AI form: this
        platform does not custody customer trading money. The internal
        simulator returns None, because virtual money is reset rather
        than deposited.
        """
        ...
