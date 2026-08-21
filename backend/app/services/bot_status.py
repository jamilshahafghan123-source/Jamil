"""Bot state, derived rather than asserted (section 17).

Every state below is computed from something the platform can actually
observe: a setting, a mode flag, a health reading, a position count.
Nothing reports RUNNING because a switch was flipped — a bot whose broker
is disconnected is not running, whatever its own setting says, and saying
so is the difference between a status light and a decoration.

Order matters. The states are evaluated most-blocking first, so the
reason shown is the one the customer has to fix, not the last one checked.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


class BotState(str, enum.Enum):
    OFF = "OFF"
    READY = "READY"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WAITING_FOR_SETUP = "WAITING_FOR_SETUP"
    POSITION_OPEN = "POSITION_OPEN"
    PAUSED = "PAUSED"
    STALLED = "STALLED"
    BLOCKED_BY_RISK = "BLOCKED_BY_RISK"
    SAFE_MODE = "SAFE_MODE"
    MAINTENANCE_MODE = "MAINTENANCE_MODE"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    BROKER_DISCONNECTED = "BROKER_DISCONNECTED"
    MARKET_DATA_ERROR = "MARKET_DATA_ERROR"
    CONNECTION_ERROR = "CONNECTION_ERROR"


#: Customer-facing wording. Kept beside the enum so a state cannot be
#: displayed without someone deciding what it should say.
STATE_LABEL: dict[BotState, str] = {
    BotState.OFF: "Off",
    BotState.READY: "Ready",
    BotState.STARTING: "Starting",
    BotState.RUNNING: "Running",
    BotState.WAITING_FOR_SETUP: "Waiting for a setup",
    BotState.POSITION_OPEN: "Position open",
    BotState.PAUSED: "Paused",
    BotState.STALLED: "Not analysing",
    BotState.BLOCKED_BY_RISK: "Blocked by risk manager",
    BotState.SAFE_MODE: "Safe Mode active",
    BotState.MAINTENANCE_MODE: "Maintenance Mode active",
    BotState.EMERGENCY_STOP: "Emergency stop engaged",
    BotState.BROKER_DISCONNECTED: "Broker disconnected",
    BotState.MARKET_DATA_ERROR: "Market data unavailable",
    BotState.CONNECTION_ERROR: "Connection error",
}

#: States in which the bot is not going to open anything.
BLOCKED_STATES = frozenset({
    BotState.OFF, BotState.PAUSED, BotState.STALLED, BotState.BLOCKED_BY_RISK,
    BotState.SAFE_MODE, BotState.MAINTENANCE_MODE, BotState.EMERGENCY_STOP,
    BotState.BROKER_DISCONNECTED, BotState.MARKET_DATA_ERROR,
    BotState.CONNECTION_ERROR,
})


@dataclass(frozen=True, slots=True)
class BotStatus:
    state: BotState
    detail: str

    def as_dict(self) -> dict:
        return {
            "state": self.state.value,
            "label": STATE_LABEL[self.state],
            "detail": self.detail,
            "blocked": self.state in BLOCKED_STATES,
            "active": self.state in (
                BotState.RUNNING, BotState.WAITING_FOR_SETUP,
                BotState.POSITION_OPEN, BotState.STARTING,
            ),
        }


def derive(
    *,
    bot_enabled: bool,
    emergency_stop: bool,
    trading_mode: str,
    paused: bool = False,
    safe_mode_active: bool = False,
    safe_mode_reason: str = "",
    maintenance_active: bool = False,
    maintenance_reason: str = "",
    market_data_ok: bool = True,
    broker_connected: bool = True,
    venue_requires_broker: bool = False,
    open_positions: int = 0,
    risk_blocked_reason: str | None = None,
    started_at: datetime | None = None,
    last_cycle_at: datetime | None = None,
    interval_seconds: int = 60,
    now: datetime | None = None,
) -> BotStatus:
    """Work out what the bot is actually doing.

    The checks run most-blocking first so the reported reason is the one
    that must be resolved. An emergency stop with a wide spread underneath
    it is an emergency stop, not a spread problem.
    """
    if emergency_stop:
        return BotStatus(
            BotState.EMERGENCY_STOP,
            "Automation is halted until the emergency stop is cleared.",
        )

    if maintenance_active:
        return BotStatus(
            BotState.MAINTENANCE_MODE,
            maintenance_reason
            or "New positions are blocked. Closing remains available.",
        )

    if safe_mode_active:
        return BotStatus(
            BotState.SAFE_MODE,
            safe_mode_reason
            or "Safe Mode is blocking new positions.",
        )

    if not bot_enabled:
        return BotStatus(BotState.OFF, "The bot is switched off.")

    # IS THE LOOP ACTUALLY RUNNING? Every check below reports on what the
    # bot would decide. None of them notices that nothing is deciding at
    # all, so a loop that crashed at startup used to report "waiting for
    # a setup" indefinitely — the most reassuring possible description of
    # a bot that is not running.
    #
    # The grace window is three intervals, so one slow cycle is not an
    # alarm and a genuinely stopped loop is caught within a few minutes.
    moment = now or datetime.now(timezone.utc)
    grace = timedelta(seconds=max(interval_seconds * 3, 180))

    if started_at is None:
        return BotStatus(
            BotState.STALLED,
            "The analysis loop is not running. The bot is switched on but "
            "nothing is scanning the market.",
        )
    if last_cycle_at is None:
        if moment - started_at > grace:
            return BotStatus(
                BotState.STALLED,
                "The analysis loop started but has not completed a cycle. "
                "Something is blocking it.",
            )
        return BotStatus(
            BotState.STARTING,
            "The analysis loop is starting; no cycle has completed yet.",
        )
    if moment - last_cycle_at > grace:
        late = int((moment - last_cycle_at).total_seconds())
        return BotStatus(
            BotState.STALLED,
            f"The last analysis cycle finished {late} seconds ago, well "
            f"past the {interval_seconds}-second schedule.",
        )

    # A pause is the customer's own hold and outranks every operational
    # state below it: there is no point reporting "waiting for a setup"
    # to someone who has told the bot not to take one. It sits below the
    # platform-level blocks, though — a pause does not describe an
    # account under an emergency stop.
    if paused:
        return BotStatus(
            BotState.PAUSED,
            "Paused. Open positions are still managed; nothing new will "
            "be opened until you resume.",
        )

    # Infrastructure next: a bot with no prices is not waiting for a setup,
    # it cannot see the market at all.
    if not market_data_ok:
        return BotStatus(
            BotState.MARKET_DATA_ERROR,
            "No market data, so no setup can be assessed.",
        )

    # The internal demo has no broker, so a broker outage is only the
    # bot's problem when the chosen venue actually needs one.
    if venue_requires_broker and not broker_connected:
        return BotStatus(
            BotState.BROKER_DISCONNECTED,
            "The trading venue is unreachable.",
        )

    if risk_blocked_reason:
        return BotStatus(BotState.BLOCKED_BY_RISK, risk_blocked_reason)

    if trading_mode == "MANUAL":
        return BotStatus(
            BotState.READY,
            "Enabled, but trading mode is MANUAL — set it to DEMO for the "
            "bot to place orders.",
        )

    if open_positions > 0:
        return BotStatus(
            BotState.POSITION_OPEN,
            f"Managing {open_positions} open position"
            f"{'s' if open_positions != 1 else ''}.",
        )

    return BotStatus(
        BotState.WAITING_FOR_SETUP,
        "Analysing the market. No qualifying setup right now.",
    )
