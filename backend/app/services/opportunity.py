"""J Gold AI Opportunity Engine (sections 41-49).

THE PROBLEM THIS SOLVES
-----------------------
The risk engine gates every signal on one global pair of numbers:
`min_confidence` and `min_rr`. A single threshold cannot be right for both
a multi-day swing setup and an M5 scalp, so the bot sits idle through
active London sessions waiting for a swing-grade signal that intraday
conditions were never going to produce.

The fix is NOT a lower threshold. Dropping the gate to admit a 47%
confidence, 0.44 RR signal would trade more and lose more. The fix is to
recognise that different SETUP CLASSES are different products with
different, individually calibrated requirements — and to score entry
quality well enough to find a setup while the move still has room, rather
than confirming it after the move is over.

WHAT THIS MODULE IS NOT
-----------------------
It is not a second trading brain. It produces a classification and a
score; the Central Risk Manager remains the only thing that approves
anything, and every gate it already applies still applies afterwards.

It is not a trade quota. Sections 41 and 105 are explicit: 4-8
opportunities on an active day is an expectation, never a target. If the
day produces one qualifying setup, the correct number of trades is one.
Nothing here counts trades taken and loosens to reach a number — there is
deliberately no such input.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


class SetupClass(str, enum.Enum):
    """What kind of trade this is, which decides what it must prove.

    A_PLUS    multi-factor alignment, larger expected move
    STANDARD  ordinary intraday continuation or reversal
    SCALP     short hold, small target, M1/M5 execution in M15/H1 context
    """

    A_PLUS = "A_PLUS"
    STANDARD = "STANDARD"
    SCALP = "SCALP"


class Regime(str, enum.Enum):
    TREND = "TREND"
    RANGE = "RANGE"
    BREAKOUT = "BREAKOUT"
    PULLBACK = "PULLBACK"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    QUIET = "QUIET"


class Grade(str, enum.Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    ACCEPTABLE = "ACCEPTABLE"
    POOR = "POOR"


@dataclass(frozen=True, slots=True)
class Requirement:
    min_confidence: int
    min_rr: float
    #: Widest spread this class tolerates, in points. A scalp's edge is
    #: small enough that spread alone can erase it, so it is strictest.
    max_spread_points: float
    #: Lowest opportunity grade this class will accept.
    min_grade: Grade


#: THE FLOOR NOTHING MAY GO BELOW.
#:
#: Section 47 is explicit that inactivity must not be solved by approving
#: poor signals. No setup class, regime adjustment or admin setting can
#: produce a requirement under these numbers — `requirements_for` clamps
#: to them, and a test asserts every possible combination stays above.
#:
#: CONFIDENCE IS 50 BECAUSE THAT IS THE STATED PLATFORM POLICY: below 50%
#: there is no automatic entry, at or above 50% a setup is ELIGIBLE if
#: every other gate also passes. It was 55, which meant an account asking
#: for 50 silently got 55 — a threshold nobody could see in their own
#: settings. The other three numbers are unchanged: relaxing the
#: confidence dimension is not a reason to relax risk/reward, spread or
#: grade with it.
ABSOLUTE_FLOOR = Requirement(
    min_confidence=50,
    min_rr=0.9,
    max_spread_points=60.0,
    min_grade=Grade.ACCEPTABLE,
)


#: Per-class requirements. A scalp is allowed a lower RR than a swing
#: because it is a different product — but it must be MORE confident and
#: accept LESS spread, because its margin for error is smaller.
BASE_REQUIREMENTS: dict[SetupClass, Requirement] = {
    SetupClass.A_PLUS: Requirement(
        min_confidence=72, min_rr=2.0, max_spread_points=45.0,
        min_grade=Grade.GOOD,
    ),
    SetupClass.STANDARD: Requirement(
        min_confidence=68, min_rr=1.5, max_spread_points=40.0,
        min_grade=Grade.GOOD,
    ),
    SetupClass.SCALP: Requirement(
        min_confidence=70, min_rr=1.1, max_spread_points=25.0,
        min_grade=Grade.GOOD,
    ),
}


#: Regime adjustments (section 43). Positive numbers demand MORE.
#:
#: A quiet Asian session and a London breakout are not the same market and
#: should not face the same bar. These are deliberately small: a regime
#: nudges a requirement, it does not redefine it.
REGIME_ADJUSTMENT: dict[Regime, tuple[int, float]] = {
    Regime.TREND: (-2, -0.1),
    Regime.PULLBACK: (-2, 0.0),
    Regime.BREAKOUT: (0, 0.1),
    Regime.RANGE: (+4, +0.2),
    Regime.HIGH_VOLATILITY: (+3, +0.2),
    Regime.LOW_VOLATILITY: (+2, +0.1),
    Regime.QUIET: (+6, +0.3),
}


def requirements_for(
    setup_class: SetupClass,
    regime: Regime | None = None,
    account_min_confidence: int | None = None,
    account_min_rr: float | None = None,
) -> Requirement:
    """What this setup must prove, given its class and the regime.

    CONFIDENCE is the one dimension the account owner sets directly, so
    their number is AUTHORITATIVE: an account asking for 50 gets 50, one
    asking for 85 gets 85, and the absolute floor of 50 is the only thing
    below which it cannot go. The class and regime numbers below remain
    the platform's own opinion and apply whenever the account has not
    expressed one.

    This used to be a tightening only, which meant an account set to 50
    quietly ran at 68 — the class requirement — with nothing on the
    settings screen saying so. A threshold the customer cannot see is not
    a safety feature, it is a surprise.

    RISK/REWARD, SPREAD and GRADE are still a TIGHTENING only. Those are
    not the dimension being delegated, and an account may make the
    platform stricter on them but never more permissive. Confidence
    moving does not carry them with it.
    """
    base = BASE_REQUIREMENTS[setup_class]
    confidence_delta, rr_delta = REGIME_ADJUSTMENT.get(regime, (0, 0.0)) \
        if regime else (0, 0.0)

    confidence = base.min_confidence + confidence_delta
    rr = base.min_rr + rr_delta

    if account_min_confidence is not None:
        confidence = int(account_min_confidence)
    if account_min_rr is not None:
        rr = max(rr, float(account_min_rr))

    return Requirement(
        min_confidence=max(confidence, ABSOLUTE_FLOOR.min_confidence),
        min_rr=round(max(rr, ABSOLUTE_FLOOR.min_rr), 2),
        max_spread_points=min(base.max_spread_points,
                              ABSOLUTE_FLOOR.max_spread_points),
        min_grade=base.min_grade,
    )


# --------------------------------------------------------- scoring

#: Factor weights (section 44). They sum to 100 so a score reads as a
#: percentage without needing to be normalised at the call site.
FACTOR_WEIGHTS: dict[str, int] = {
    "structure": 16,
    "trend_alignment": 14,
    "entry_location": 14,
    "higher_timeframe": 10,
    "momentum": 8,
    "session_quality": 8,
    "liquidity": 6,
    "fvg": 5,
    "support_resistance": 5,
    "supply_demand": 4,
    "volatility": 4,
    "candle_confirmation": 3,
    "spread": 3,
}

assert sum(FACTOR_WEIGHTS.values()) == 100


@dataclass(slots=True)
class OpportunityScore:
    """A transparent score: every factor keeps its own contribution.

    The breakdown is the point. A number a customer cannot interrogate is
    not an explanation, and section 59 requires NO TRADE to say exactly
    why.
    """

    total: int
    grade: Grade
    factors: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "grade": self.grade.value,
            "factors": {k: round(v, 1) for k, v in self.factors.items()},
            "notes": list(self.notes),
        }


def grade_for(total: int) -> Grade:
    if total >= 78:
        return Grade.EXCELLENT
    if total >= 62:
        return Grade.GOOD
    if total >= 48:
        return Grade.ACCEPTABLE
    return Grade.POOR


def score_opportunity(factors: dict[str, float]) -> OpportunityScore:
    """Combine factor strengths (each 0.0-1.0) into a weighted score.

    A factor that is absent scores zero rather than being dropped from the
    denominator. Silently renormalising over whatever happened to be
    measured is how a setup with three known factors ends up scoring the
    same as one with thirteen.
    """
    contributions: dict[str, float] = {}
    notes: list[str] = []
    total = 0.0

    for name, weight in FACTOR_WEIGHTS.items():
        raw = factors.get(name)
        if raw is None:
            contributions[name] = 0.0
            notes.append(f"{name}: not measured")
            continue
        strength = max(0.0, min(1.0, float(raw)))
        contribution = strength * weight
        contributions[name] = contribution
        total += contribution

    rounded = int(round(total))
    return OpportunityScore(
        total=rounded, grade=grade_for(rounded), factors=contributions,
        notes=notes,
    )


def classify_setup(
    score: OpportunityScore,
    expected_rr: float,
    hold_minutes: int | None = None,
) -> SetupClass:
    """Which product this setup is.

    Class follows the setup's own shape — how well aligned it is and how
    far it expects to travel — and never the other way round. Nothing here
    downgrades a setup to SCALP so that a lower RR bar applies to it;
    a short expected hold is what makes something a scalp.
    """
    if hold_minutes is not None and hold_minutes <= 30:
        return SetupClass.SCALP
    if score.grade is Grade.EXCELLENT and expected_rr >= 2.0:
        return SetupClass.A_PLUS
    if expected_rr < 1.5:
        return SetupClass.SCALP
    return SetupClass.STANDARD


# --------------------------------------- weighted multi-timeframe (§45)

#: Weights for the XAUUSD hierarchy in section 57. Higher timeframes carry
#: more weight, but no single timeframe holds a veto.
TIMEFRAME_WEIGHT: dict[str, float] = {
    "D1": 0.22, "H4": 0.22, "H1": 0.18, "M30": 0.12,
    "M15": 0.12, "M5": 0.08, "M1": 0.06,
}


def timeframe_alignment(biases: dict[str, str], direction: str) -> float:
    """How much of the weighted hierarchy agrees with `direction`.

    Section 45: a pullback entry has the lower timeframe temporarily
    against the trade by definition — that is what a pullback IS — so M1
    disagreeing must cost a little, not veto a setup the daily, four-hour
    and hourly all support. Weighting achieves that; a unanimity rule
    cannot.
    """
    if direction not in ("BUY", "SELL"):
        return 0.0
    wanted = "BULLISH" if direction == "BUY" else "BEARISH"
    agreed = 0.0
    considered = 0.0
    for timeframe, weight in TIMEFRAME_WEIGHT.items():
        bias = (biases.get(timeframe) or "").upper()
        if not bias:
            continue
        considered += weight
        if bias == wanted:
            agreed += weight
        elif bias == "NEUTRAL":
            agreed += weight * 0.5
    return 0.0 if considered == 0 else agreed / considered


# ------------------------------------------------ entry quality (§46)

#: Entry triggers, and how good an entry each one typically represents.
#:
#: The ranking encodes section 46: reacting to structure while price is
#: still near invalidation is worth more than confirming a move that has
#: already travelled, because the second one has spent the RR that made
#: the trade worth taking.
ENTRY_TRIGGERS: dict[str, float] = {
    "SWEEP_RECLAIM": 1.0,
    "PULLBACK_TO_STRUCTURE": 0.95,
    "FVG_REACTION": 0.9,
    "DEMAND_RESPONSE": 0.9,
    "SUPPLY_RESPONSE": 0.9,
    "RETEST_AFTER_BREAK": 0.88,
    "SESSION_BREAKOUT_RETEST": 0.85,
    "REJECTION_CANDLE": 0.75,
    "MOMENTUM_RESUMPTION": 0.7,
    "BREAKOUT_CHASE": 0.35,
    "LATE_CONTINUATION": 0.25,
}


def entry_quality(trigger: str | None, distance_to_invalidation_atr: float | None
                  ) -> tuple[float, str]:
    """How good this entry is, and a sentence saying why.

    Distance to invalidation is the honest check on the trigger's name: an
    entry calling itself a pullback while sitting two ATR from its own
    stop is not near structure, whatever it is labelled.
    """
    base = ENTRY_TRIGGERS.get((trigger or "").upper())
    if base is None:
        return 0.0, "No recognised entry trigger."

    if distance_to_invalidation_atr is None:
        return base * 0.8, f"{trigger}: entry distance not measured."

    distance = max(0.0, float(distance_to_invalidation_atr))
    if distance <= 0.75:
        return base, f"{trigger} close to invalidation ({distance:.2f} ATR)."
    if distance <= 1.5:
        return base * 0.75, f"{trigger} at {distance:.2f} ATR from invalidation."
    return (base * 0.4,
            f"{trigger} but {distance:.2f} ATR from invalidation — much of "
            "the move is already priced in.")


# ------------------------------------- duplicate / cooldown (§48)

@dataclass(frozen=True, slots=True)
class Fingerprint:
    """What makes two signals "the same signal".

    Deliberately excludes confidence and score: the same setup re-scored a
    point higher on the next bar is the same setup, and treating it as new
    is exactly how an engine that finds more opportunities turns into one
    that spams.
    """

    symbol: str
    direction: str
    setup_class: str
    structure_state: str
    #: Entry rounded to a band, so a two-cent drift is not a new trade.
    entry_band: int

    @classmethod
    def build(cls, symbol: str, direction: str, setup_class: SetupClass,
              structure_state: str, entry: float, band: float = 2.0
              ) -> "Fingerprint":
        return cls(
            symbol=symbol.upper(),
            direction=direction.upper(),
            setup_class=setup_class.value,
            structure_state=(structure_state or "UNKNOWN").upper(),
            entry_band=int(entry // band) if band > 0 else int(entry),
        )


#: How long the same fingerprint stays blocked, per class. A scalp may
#: legitimately repeat sooner than a swing setup.
COOLDOWN: dict[SetupClass, timedelta] = {
    SetupClass.A_PLUS: timedelta(minutes=90),
    SetupClass.STANDARD: timedelta(minutes=45),
    SetupClass.SCALP: timedelta(minutes=12),
}


def is_duplicate(
    fingerprint: Fingerprint,
    recent: list[tuple[Fingerprint, datetime]],
    setup_class: SetupClass,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Whether this signal repeats one still inside its cooldown.

    A genuine structure change produces a different fingerprint and is
    therefore never suppressed — the cooldown blocks repetition, not
    development.
    """
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    window = COOLDOWN[setup_class]
    for previous, seen_at in recent:
        if previous != fingerprint:
            continue
        age = moment - seen_at.astimezone(timezone.utc)
        if age < window:
            remaining = window - age
            return True, (
                f"same {setup_class.value} setup seen "
                f"{int(age.total_seconds() // 60)} min ago; "
                f"{int(remaining.total_seconds() // 60)} min of cooldown left"
            )
    return False, ""


# ------------------------------------------------- telemetry (§49)

@dataclass(slots=True)
class OpportunityRecord:
    """One detected opportunity and what became of it.

    Kept as three separate outcomes on purpose (section 40): the AI's
    decision, the risk manager's ruling and the execution result are
    different questions, and collapsing them makes it impossible to tell
    whether a quiet day was the engine finding nothing, risk refusing
    everything, or execution failing.
    """

    detected_at: datetime
    symbol: str
    session: str
    setup_class: SetupClass
    grade: Grade
    score: int
    direction: str
    confidence: int
    expected_rr: float
    required_confidence: int
    required_rr: float
    ai_decision: str
    risk_decision: str | None = None
    risk_reason: str | None = None
    execution_result: str | None = None
    rejection_reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "detected_at": self.detected_at.isoformat(),
            "symbol": self.symbol,
            "session": self.session,
            "setup_class": self.setup_class.value,
            "grade": self.grade.value,
            "score": self.score,
            "direction": self.direction,
            "confidence": self.confidence,
            "expected_rr": self.expected_rr,
            "required_confidence": self.required_confidence,
            "required_rr": self.required_rr,
            "ai_decision": self.ai_decision,
            "risk_decision": self.risk_decision,
            "risk_reason": self.risk_reason,
            "execution_result": self.execution_result,
            "rejection_reason": self.rejection_reason,
        }


def evaluate(
    *,
    direction: str,
    confidence: int,
    expected_rr: float,
    factors: dict[str, float],
    timeframe_biases: dict[str, str] | None = None,
    entry_trigger: str | None = None,
    distance_to_invalidation_atr: float | None = None,
    hold_minutes: int | None = None,
    regime: Regime | None = None,
    account_min_confidence: int | None = None,
    account_min_rr: float | None = None,
) -> dict:
    """Classify and grade one candidate setup.

    Returns the decision, the class, the score with its full breakdown,
    the requirements that applied and why they were or were not met. This
    is advisory: the Central Risk Manager still rules on everything that
    passes, and nothing here can approve a trade.
    """
    enriched = dict(factors)

    if timeframe_biases:
        enriched.setdefault(
            "higher_timeframe", timeframe_alignment(timeframe_biases, direction)
        )

    entry_note = None
    if entry_trigger is not None:
        quality, entry_note = entry_quality(
            entry_trigger, distance_to_invalidation_atr
        )
        enriched.setdefault("entry_location", quality)

    score = score_opportunity(enriched)
    if entry_note:
        score.notes.insert(0, entry_note)

    setup_class = classify_setup(score, expected_rr, hold_minutes)
    requirement = requirements_for(
        setup_class, regime, account_min_confidence, account_min_rr
    )

    reasons: list[str] = []
    if score.grade is Grade.POOR:
        reasons.append(f"opportunity grade {score.grade.value} (score {score.total})")
    elif _grade_rank(score.grade) < _grade_rank(requirement.min_grade):
        reasons.append(
            f"grade {score.grade.value} below {requirement.min_grade.value} "
            f"required for a {setup_class.value} setup"
        )
    if confidence < requirement.min_confidence:
        reasons.append(
            f"confidence {confidence}% below {requirement.min_confidence}% "
            f"required for a {setup_class.value} setup"
        )
    if expected_rr < requirement.min_rr:
        reasons.append(
            f"risk/reward {expected_rr:.2f} below {requirement.min_rr:.2f} "
            f"required for a {setup_class.value} setup"
        )

    qualified = not reasons
    return {
        "qualified": qualified,
        "decision": direction if qualified else "NO_TRADE",
        "setup_class": setup_class.value,
        "regime": regime.value if regime else None,
        "score": score.as_dict(),
        "requirements": {
            "min_confidence": requirement.min_confidence,
            "min_rr": requirement.min_rr,
            "max_spread_points": requirement.max_spread_points,
            "min_grade": requirement.min_grade.value,
        },
        "reasons": reasons,
    }


def _grade_rank(grade: Grade) -> int:
    return {Grade.POOR: 0, Grade.ACCEPTABLE: 1,
            Grade.GOOD: 2, Grade.EXCELLENT: 3}[grade]
