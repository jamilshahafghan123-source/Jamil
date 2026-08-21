"""Turning one analysis into opportunity-engine factors (sections 40, 49).

The opportunity engine scores thirteen named factors, each 0.0-1.0. The
analyst already measures most of them, under different names and on its
own scales. This module is the ONE place that translates between the two,
so the score stays interrogable: every factor produced here traces back
to a specific measurement, and a factor the analyst does not measure is
LEFT OUT rather than guessed. `score_opportunity` records an absent
factor as "not measured" and the score carries the cost, which is the
honest outcome — inventing a middling value to avoid the penalty would
make the total look measured when it was not.

Nothing here decides anything. It produces inputs; the opportunity engine
grades them and the Central Risk Manager still rules on whatever passes.
"""

from __future__ import annotations

from datetime import datetime

from . import sessions

#: The analyst's confidence components are absolute points against its own
#: weights. Dividing by the weight recovers the 0.0-1.0 strength the
#: opportunity engine wants, without either engine having to know the
#: other's scale.
COMPONENT_SCALE: dict[str, tuple[str, int]] = {
    # opportunity factor -> (analyst component, that component's max)
    "structure": ("structure", 20),
    "trend_alignment": ("trend_alignment", 25),
    "momentum": ("momentum", 15),
    "liquidity": ("liquidity", 5),
    "support_resistance": ("levels", 10),
}

#: Session quality, by what is actually open.
#:
#: The London/New York overlap is the deepest, most consistently liquid
#: window in this market and the Asian session the thinnest; a period with
#: nothing open at all is the worst time to be taking a discretionary
#: setup. These are the conventional desk view, stated here rather than
#: buried in a formula.


def session_quality(moment: datetime) -> float:
    """How good the session is for taking a setup, 0.0-1.0."""
    open_now = {spec.name.value for spec in sessions.active_at(moment)}
    if not open_now:
        return 0.0
    if "LONDON" in open_now and "NEW_YORK" in open_now:
        return 1.0
    if "NEW_YORK" in open_now or "LONDON" in open_now:
        return 0.75
    # Sydney and Tokyo: real sessions, thinner books.
    return 0.4


def session_label(moment: datetime) -> str:
    """The session name to record against an opportunity."""
    open_now = [spec.name.value for spec in sessions.active_at(moment)]
    if not open_now:
        return "OFF_SESSION"
    if "LONDON" in open_now and "NEW_YORK" in open_now:
        return "LONDON_NEW_YORK"
    # The largest centre open decides the label.
    for name in ("NEW_YORK", "LONDON", "TOKYO", "SYDNEY"):
        if name in open_now:
            return name
    return "OFF_SESSION"


def volatility_strength(atr: float | None, price: float | None) -> float | None:
    """Volatility as ATR against price, banded.

    Both extremes are bad for different reasons: a market with no range
    cannot reach a target, and one with too much range makes the stop a
    lottery. Returns None when either input is missing, so the factor is
    recorded as not measured rather than assumed to be fine.
    """
    if not atr or not price or price <= 0 or atr <= 0:
        return None
    pct = atr / price * 100.0
    if pct < 0.05:
        return 0.1          # effectively dead
    if pct < 0.15:
        return 0.6
    if pct <= 0.60:
        return 1.0          # the workable band
    if pct <= 1.20:
        return 0.5
    return 0.2              # disorderly


def spread_strength(
    spread_points: float | None, max_spread_points: float | None
) -> float | None:
    """How much of the permitted spread the current spread uses up."""
    if spread_points is None or not max_spread_points:
        return None
    if spread_points <= 0:
        return 1.0
    ratio = spread_points / float(max_spread_points)
    return max(0.0, min(1.0, 1.0 - ratio))


def _setup_timeframe(analysis: dict) -> dict:
    """The timeframe the setup was actually timed on."""
    for view in analysis.get("timeframes") or []:
        if str(view.get("role", "")).upper() == "SETUP":
            return view
    tfs = analysis.get("timeframes") or []
    return tfs[0] if tfs else {}


def timeframe_biases(analysis: dict) -> dict[str, str]:
    """Each timeframe's trend, for the higher-timeframe alignment factor."""
    out: dict[str, str] = {}
    for view in analysis.get("timeframes") or []:
        name = view.get("timeframe")
        trend = view.get("trend")
        if name and trend:
            out[str(name)] = str(trend)
    return out


def factors_from_analysis(
    analysis: dict,
    *,
    direction: str,
    moment: datetime,
    spread_points: float | None = None,
    max_spread_points: float | None = None,
) -> dict[str, float]:
    """The opportunity engine's factors, as far as they are measured.

    `entry_location` and `higher_timeframe` are deliberately absent: the
    opportunity engine derives both itself from the entry trigger and the
    timeframe biases, and computing them twice would let the two answers
    drift.
    """
    setup = analysis.get("setup") or {}
    components = setup.get("confidence_components") or {}
    setup_tf = _setup_timeframe(analysis)
    market = analysis.get("market") or {}
    zones = analysis.get("zones") or {}

    factors: dict[str, float] = {}

    for factor, (component, maximum) in COMPONENT_SCALE.items():
        raw = components.get(component)
        if raw is None:
            continue
        factors[factor] = max(0.0, min(1.0, float(raw) / maximum))

    factors["session_quality"] = session_quality(moment)

    volatility = volatility_strength(
        setup_tf.get("atr14") or market.get("volatility"),
        market.get("price"),
    )
    if volatility is not None:
        factors["volatility"] = volatility

    spread = spread_strength(spread_points, max_spread_points)
    if spread is not None:
        factors["spread"] = spread

    # Structural zones: present and on the right side of the trade, or
    # nothing. A zone behind the entry is not support for taking it.
    fvg = zones.get("fvg") or setup_tf.get("fvg") or []
    blocks = zones.get("order_blocks") or setup_tf.get("order_blocks") or []
    factors["fvg"] = 1.0 if _supporting(fvg, direction) else 0.0
    factors["supply_demand"] = 1.0 if _supporting(blocks, direction) else 0.0

    # candle_confirmation is not measured anywhere in the analyst, so it is
    # not supplied. The score records it as unmeasured and loses its three
    # points, which is the truthful result.
    return factors


def _supporting(zones: list, direction: str) -> bool:
    """Whether any zone backs a trade in this direction."""
    want = "BULLISH" if direction == "BUY" else "BEARISH"
    for zone in zones or []:
        if not isinstance(zone, dict):
            continue
        kind = str(zone.get("bias") or zone.get("direction") or "").upper()
        if kind == want:
            return True
        # Zones with no stated bias still count as structure being present
        # on the chart, which is what this factor is asking about.
        if not kind:
            return True
    return False


def entry_inputs(analysis: dict) -> tuple[str | None, float | None]:
    """The entry trigger and how far the stop sits, measured in ATR.

    Both feed the opportunity engine's own entry-quality assessment. The
    distance is returned in ATR rather than price so it means the same
    thing on a quiet day and a violent one.
    """
    setup = analysis.get("setup") or {}
    trigger = setup.get("trigger_text") or None
    setup_tf = _setup_timeframe(analysis)
    atr = setup_tf.get("atr14") or (analysis.get("market") or {}).get("volatility")
    entry = setup.get("trigger") or setup.get("entry_low") or setup.get("entry_high")
    stop = setup.get("stop_loss")
    if not atr or entry is None or stop is None or float(atr) <= 0:
        return trigger, None
    return trigger, abs(float(entry) - float(stop)) / float(atr)
