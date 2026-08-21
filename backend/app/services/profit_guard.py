"""Protecting an open profit before take-profit (section 44).

THIS IS NOT A SECOND POSITION MANAGER. It is the decision the existing
profit manager in `bot.py` already made, pulled out so it can be reasoned
about and tested without a broker, and given the confirmation it was
missing.

What it was doing: a profitable position was closed the moment ONE
analysis cycle stopped strongly supporting it. A single cycle returning
NO_TRADE, or the same direction at 64% instead of 65%, closed the trade.
That is closing on one candle, and it turns a position manager into a
scalper that sells every wobble.

What it does now: two stages, and closing requires BOTH of them.

    PROFIT_HOLD                the analysis still supports the position
    PROFIT_WEAKENING           support is degrading; keep watching
    PROFIT_EXIT_CONFIRMED_REVERSAL
                               enough independent evidence agrees

Confirmation means two things at once, never one:

  1. PERSISTENCE — weakening seen on at least two consecutive cycles, so
     at least two independent analyses agree. One reading cannot close a
     trade.
  2. AGREEMENT — either the engine now signals the OPPOSITE side with
     real confidence, or momentum AND the setup timeframe have both
     turned against the position.

Everything here is read from analysis the platform already computed. No
new indicator, no new data source, and nothing that guesses.

The hard stop loss is untouched by all of this, and so are the take
profit and stop loss calculations. This can only close a position that is
ALREADY IN PROFIT — it never turns a losing trade into a decision.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class ProfitAction(str, enum.Enum):
    HOLD = "PROFIT_HOLD"
    WEAKENING = "PROFIT_WEAKENING"
    EXIT = "PROFIT_EXIT_CONFIRMED_REVERSAL"


#: Confidence at which the engine's agreement still counts as support.
#:
#: A NON-ENTRY threshold. It has nothing to do with the 50% entry policy
#: and must not be lowered to match it: deciding to keep a profit is a
#: different question from deciding to open a trade, and the cost of
#: getting it wrong is different too.
HOLD_CONFIDENCE = 65

#: Confidence an OPPOSING signal needs before it counts as evidence that
#: the move has turned. Deliberately its own constant so it can diverge
#: from HOLD_CONFIDENCE without either being mistaken for an entry gate.
REVERSAL_CONFIDENCE = 65

#: Consecutive weakening cycles before an exit may even be considered.
#: Two means two independent analyses, which is the whole point.
MIN_WEAKENING_CYCLES = 2


@dataclass(slots=True)
class GuardState:
    """How long each position has been weakening, across cycles.

    Keyed by the caller. Lost on restart, which is the safe direction:
    a restarted bot demands fresh confirmation rather than acting on a
    streak it can no longer justify.
    """

    streaks: dict[str, int] = field(default_factory=dict)

    def record_weakening(self, key: str) -> int:
        self.streaks[key] = self.streaks.get(key, 0) + 1
        return self.streaks[key]

    def clear(self, key: str) -> None:
        self.streaks.pop(key, None)


@dataclass(frozen=True, slots=True)
class Decision:
    action: ProfitAction
    reason: str
    #: How many consecutive cycles this position has been weakening.
    weakening_cycles: int = 0

    @property
    def should_close(self) -> bool:
        return self.action is ProfitAction.EXIT


def _timeframe_trend(analysis: dict) -> str | None:
    """The trend on the timeframe the setup was timed on."""
    for view in analysis.get("timeframes") or []:
        if str(view.get("role", "")).upper() == "SETUP":
            trend = view.get("trend")
            return str(trend).upper() if trend else None
    return None


def _turned_against(side: str, analysis: dict) -> bool:
    """Whether momentum AND structure have both turned against the trade.

    Both, not either. Momentum alone flickers between cycles; the setup
    timeframe's trend alone is slow. Requiring the pair is what stops
    ordinary noise reading as a reversal.
    """
    market = analysis.get("market") or {}
    momentum = str(market.get("momentum") or "").upper()
    trend = _timeframe_trend(analysis)
    if side == "BUY":
        return momentum == "FALLING" and trend == "DOWN"
    if side == "SELL":
        return momentum == "RISING" and trend == "UP"
    return False


def assess(
    *,
    side: str,
    profit: float,
    ai_action: str,
    ai_confidence: int,
    analysis: dict | None,
    weakening_cycles: int,
) -> Decision:
    """What to do with one profitable position this cycle.

    `weakening_cycles` is how many consecutive previous cycles already
    reported weakening for this position, BEFORE this one.
    """
    side = side.upper()
    ai_action = (ai_action or "NO_TRADE").upper()

    # This path exists to protect a profit. It has no opinion on a losing
    # trade — that is the stop loss's job, and always has been.
    if profit <= 0:
        return Decision(ProfitAction.HOLD, "not in profit; nothing to protect")

    if ai_action == side and ai_confidence >= HOLD_CONFIDENCE:
        return Decision(
            ProfitAction.HOLD,
            f"analysis still supports {side} at {ai_confidence}% "
            f"(hold threshold {HOLD_CONFIDENCE}%)",
        )

    cycles = weakening_cycles + 1
    analysis = analysis or {}

    opposing = (
        ai_action in ("BUY", "SELL")
        and ai_action != side
        and ai_confidence >= REVERSAL_CONFIDENCE
    )
    turned = _turned_against(side, analysis)

    if cycles < MIN_WEAKENING_CYCLES:
        return Decision(
            ProfitAction.WEAKENING,
            f"support for {side} is weakening (cycle {cycles} of "
            f"{MIN_WEAKENING_CYCLES}); holding for confirmation",
            cycles,
        )

    if not (opposing or turned):
        return Decision(
            ProfitAction.WEAKENING,
            f"support for {side} has been weak for {cycles} cycles, but "
            f"nothing confirms a reversal yet; holding",
            cycles,
        )

    evidence = []
    if opposing:
        evidence.append(f"opposing {ai_action} signal at {ai_confidence}%")
    if turned:
        evidence.append("momentum and setup-timeframe trend both against it")
    return Decision(
        ProfitAction.EXIT,
        f"profit protected: {cycles} consecutive weakening cycles and "
        + " and ".join(evidence),
        cycles,
    )
