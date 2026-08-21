"""Chart replay and backtest foundation (section 63).

STATUS: COMING SOON. Nothing here simulates a fill.

Section 63 asks for the architecture without faked results, and section
88 forbids presenting a capability the platform does not have. The
interfaces below fix the shape a real implementation must satisfy, and
`capabilities()` reports honestly what is and is not available so the UI
can say "coming soon" from a fact rather than a hard-coded label.

WHY NO SIMULATED FILLS YET
--------------------------
A backtest is only worth the fill model behind it. Doing it properly
needs answers this project does not yet have: spread at the historical
moment rather than today's, whether a bar that touched the stop hit it
before or after the target, slippage, and gaps over weekends and news. A
number produced without those is not a conservative estimate — it is a
made-up track record, and the most damaging thing a trading platform can
show a customer. So the honest position is to build the interface, state
the gap, and refuse to produce a figure until the gap is closed.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Protocol


class ReplayStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    COMING_SOON = "COMING_SOON"


@dataclass(frozen=True, slots=True)
class ReplayFrame:
    """One step of a replay: the bars visible at a point in history.

    A replay only ever REVEALS bars that already exist. It never invents
    one, which is what separates replay from simulation and is why the
    frame carries an index into real history rather than generated data.
    """

    index: int
    total: int
    bars: list[dict]

    @property
    def finished(self) -> bool:
        return self.index >= self.total - 1


class ReplaySource(Protocol):
    """Where replay bars come from. Real history only."""

    async def load(self, symbol: str, timeframe: str, count: int) -> list[dict]:
        ...


def build_frame(bars: list[dict], index: int) -> ReplayFrame:
    """Reveal history up to `index`. Pure, and adds nothing.

    This much IS implementable honestly today: showing real bars one at a
    time requires no fill model, because nothing is being executed.
    """
    if not bars:
        return ReplayFrame(index=0, total=0, bars=[])
    stop = max(0, min(index, len(bars) - 1))
    return ReplayFrame(index=stop, total=len(bars), bars=bars[: stop + 1])


#: What a backtest would need before it could report a number.
MISSING_FOR_BACKTEST: tuple[str, ...] = (
    "historical spread at each bar, rather than the current spread",
    "intrabar sequence — whether a bar that touched both stop and target "
    "reached one first",
    "slippage and requote behaviour",
    "weekend and news gaps",
)


def capabilities() -> dict:
    """What replay and backtesting can honestly do right now.

    The UI reads this rather than hard-coding a badge, so the day a fill
    model lands, the status changes here and the interface follows.
    """
    return {
        "chart_replay": {
            "status": ReplayStatus.COMING_SOON.value,
            "detail": (
                "Stepping through real history is implemented as a data "
                "shape but is not wired to the chart yet. It reveals "
                "recorded bars only and never generates one."
            ),
        },
        "strategy_backtest": {
            "status": ReplayStatus.COMING_SOON.value,
            "detail": (
                "Not available. A backtest is only worth its fill model, "
                "and producing a figure without one would be a made-up "
                "track record rather than a conservative estimate."
            ),
            "missing": list(MISSING_FOR_BACKTEST),
        },
        "ai_setup_backtest": {
            "status": ReplayStatus.COMING_SOON.value,
            "detail": (
                "Not available for the same reason. Opportunity telemetry "
                "already records every live decision, which is real "
                "evidence rather than a simulation."
            ),
        },
        "available_today": (
            "Opportunity telemetry records every setup the engine detects "
            "in the internal demo, with the thresholds that applied and "
            "what became of it. That is measured behaviour, not a "
            "simulated result."
        ),
    }
