"""Safe strategy rules (sections 32-37).

WHAT THIS DELIBERATELY CANNOT DO
--------------------------------
There is no eval, no exec, no compile, no import of customer text, and no
expression parser that could be coaxed into one. A strategy is DATA: a
tree of typed conditions drawn from a closed vocabulary, evaluated by the
interpreter below. A customer can describe a strategy; they cannot supply
behaviour.

That distinction is the whole design. Section 32 forbids executing
arbitrary Python, JavaScript or Pine, and the safest way to honour that
is for the system to have no mechanism capable of it — not to have one
and try to sanitise its input.

Anything not in `Field`, `Operator` or `LogicNode` is rejected at parse
time, by type, before evaluation is even considered. An unknown field
name is an error, never a lookup that might resolve to something else.

AUTHORITY
---------
A strategy produces a SETUP PROPOSAL and nothing more. It has no
execution authority: the proposal goes to the opportunity engine, then
the Central Risk Manager, then Safe Mode, Maintenance and the emergency
stop, exactly as an AI-originated signal does (section 37). No strategy
can reach a broker, and nothing here can approve a trade.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class Field(str, enum.Enum):
    """The closed vocabulary a rule may read.

    Every member maps to a value the analysis pipeline already computes.
    Adding a field is a deliberate act here; it is not something a
    customer's strategy can do by naming one.
    """

    # price and candles
    PRICE = "PRICE"
    CANDLE_BODY_RATIO = "CANDLE_BODY_RATIO"
    CANDLE_PATTERN = "CANDLE_PATTERN"
    # indicators
    EMA = "EMA"
    SMA = "SMA"
    RSI = "RSI"
    MACD_HISTOGRAM = "MACD_HISTOGRAM"
    ATR = "ATR"
    ADX = "ADX"
    STOCHASTIC = "STOCHASTIC"
    BOLLINGER_UPPER = "BOLLINGER_UPPER"
    BOLLINGER_LOWER = "BOLLINGER_LOWER"
    # structure and context
    STRUCTURE = "STRUCTURE"
    TREND = "TREND"
    SESSION = "SESSION"
    SESSION_ACTIVE = "SESSION_ACTIVE"
    LIQUIDITY_ZONE = "LIQUIDITY_ZONE"
    FVG_ZONE = "FVG_ZONE"
    SUPPLY_ZONE = "SUPPLY_ZONE"
    DEMAND_ZONE = "DEMAND_ZONE"
    SUPPORT_LEVEL = "SUPPORT_LEVEL"
    RESISTANCE_LEVEL = "RESISTANCE_LEVEL"
    PREVIOUS_DAY_HIGH = "PREVIOUS_DAY_HIGH"
    PREVIOUS_DAY_LOW = "PREVIOUS_DAY_LOW"
    # AI and risk context
    AI_CONFIDENCE = "AI_CONFIDENCE"
    OPPORTUNITY_SCORE = "OPPORTUNITY_SCORE"
    SETUP_CLASS = "SETUP_CLASS"
    RISK_REWARD = "RISK_REWARD"
    VOLATILITY_STATE = "VOLATILITY_STATE"
    SPREAD_POINTS = "SPREAD_POINTS"
    TIME_OF_DAY = "TIME_OF_DAY"


class Operator(str, enum.Enum):
    GT = "GT"
    LT = "LT"
    GTE = "GTE"
    LTE = "LTE"
    EQUALS = "EQUALS"
    NOT_EQUALS = "NOT_EQUALS"
    CROSSES_ABOVE = "CROSSES_ABOVE"
    CROSSES_BELOW = "CROSSES_BELOW"
    ENTERS_ZONE = "ENTERS_ZONE"
    LEAVES_ZONE = "LEAVES_ZONE"
    IS_TRUE = "IS_TRUE"
    IS_FALSE = "IS_FALSE"


class Logic(str, enum.Enum):
    AND = "AND"
    OR = "OR"
    NOT = "NOT"


class ActionMode(str, enum.Enum):
    """What a strategy is allowed to do when it matches (section 35).

    REAL_AUTO is deliberately absent. Real broker automation is disabled
    for the whole platform, and a mode that does not exist cannot be
    selected by accident or reached by a malformed payload.
    """

    ALERT_ONLY = "ALERT_ONLY"
    AI_ASSIST = "AI_ASSIST"
    DEMO_AUTO = "DEMO_AUTO"


class StrategyError(ValueError):
    """A rule that could not be understood. Never a partial acceptance."""


MAX_CONDITIONS = 40
MAX_DEPTH = 6


@dataclass(frozen=True, slots=True)
class Condition:
    field: Field
    operator: Operator
    #: Compared against. A number, a label from a closed set, or another
    #: Field for indicator-to-indicator comparisons such as EMA20/EMA50.
    value: Any
    #: Indicator period where the field takes one.
    period: int | None = None
    #: Which timeframe to read the field on.
    timeframe: str = "M15"

    def as_dict(self) -> dict:
        return {
            "field": self.field.value,
            "operator": self.operator.value,
            "value": self.value.value if isinstance(self.value, Field) else self.value,
            "value_is_field": isinstance(self.value, Field),
            "period": self.period,
            "timeframe": self.timeframe,
        }


@dataclass(frozen=True, slots=True)
class Group:
    logic: Logic
    children: tuple["Group | Condition", ...]

    def as_dict(self) -> dict:
        return {
            "logic": self.logic.value,
            "children": [c.as_dict() for c in self.children],
        }


Node = Group | Condition


TIMEFRAMES = frozenset(
    {"M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"}
)

#: Fields whose value is a label rather than a number, and the labels each
#: one accepts. A value outside its set is rejected rather than coerced.
LABEL_VALUES: dict[Field, frozenset[str]] = {
    Field.STRUCTURE: frozenset({"HH", "HL", "LH", "LL", "BOS_UP", "BOS_DOWN",
                                "CHOCH_UP", "CHOCH_DOWN", "RANGE"}),
    Field.TREND: frozenset({"BULLISH", "BEARISH", "NEUTRAL"}),
    Field.SESSION: frozenset({"SYDNEY", "TOKYO", "LONDON", "NEW_YORK"}),
    Field.CANDLE_PATTERN: frozenset({"ENGULFING", "REJECTION", "INSIDE_BAR",
                                     "OUTSIDE_BAR", "DOJI", "MOMENTUM"}),
    Field.SETUP_CLASS: frozenset({"A_PLUS", "STANDARD", "SCALP"}),
    Field.VOLATILITY_STATE: frozenset({"HIGH", "NORMAL", "LOW"}),
}

#: Fields that answer yes/no and therefore take no comparison value.
BOOLEAN_FIELDS = frozenset({
    Field.SESSION_ACTIVE, Field.LIQUIDITY_ZONE, Field.FVG_ZONE,
    Field.SUPPLY_ZONE, Field.DEMAND_ZONE,
})

#: Operators valid only where a zone exists to enter or leave.
ZONE_OPERATORS = frozenset({Operator.ENTERS_ZONE, Operator.LEAVES_ZONE})
ZONE_FIELDS = frozenset({
    Field.LIQUIDITY_ZONE, Field.FVG_ZONE, Field.SUPPLY_ZONE,
    Field.DEMAND_ZONE, Field.SUPPORT_LEVEL, Field.RESISTANCE_LEVEL,
})


def parse_condition(raw: Any) -> Condition:
    """Build one condition, refusing anything outside the vocabulary."""
    if not isinstance(raw, dict):
        raise StrategyError("A condition must be an object.")

    try:
        field_ = Field(str(raw.get("field", "")).upper())
    except ValueError:
        raise StrategyError(
            f"Unknown field {raw.get('field')!r}."
        ) from None

    try:
        operator = Operator(str(raw.get("operator", "")).upper())
    except ValueError:
        raise StrategyError(
            f"Unknown operator {raw.get('operator')!r}."
        ) from None

    timeframe = str(raw.get("timeframe", "M15")).upper()
    if timeframe not in TIMEFRAMES:
        raise StrategyError(f"Unsupported timeframe {timeframe!r}.")

    period = raw.get("period")
    if period is not None:
        if not isinstance(period, int) or isinstance(period, bool):
            raise StrategyError("Indicator period must be a whole number.")
        if not 1 <= period <= 500:
            raise StrategyError("Indicator period must be between 1 and 500.")

    if operator in (Operator.IS_TRUE, Operator.IS_FALSE):
        if field_ not in BOOLEAN_FIELDS:
            raise StrategyError(
                f"{field_.value} is not a yes/no field."
            )
        return Condition(field_, operator, None, period, timeframe)

    if operator in ZONE_OPERATORS and field_ not in ZONE_FIELDS:
        raise StrategyError(f"{field_.value} has no zone to enter or leave.")

    value = raw.get("value")

    # Comparing one indicator against another, e.g. EMA20 crosses EMA50.
    if isinstance(value, str) and value.upper() in Field.__members__:
        return Condition(field_, operator, Field(value.upper()), period, timeframe)

    allowed = LABEL_VALUES.get(field_)
    if allowed is not None:
        label = str(value).upper()
        if label not in allowed:
            raise StrategyError(
                f"{field_.value} does not take the value {value!r}."
            )
        if operator not in (Operator.EQUALS, Operator.NOT_EQUALS):
            raise StrategyError(
                f"{field_.value} can only be compared with EQUALS or NOT_EQUALS."
            )
        return Condition(field_, operator, label, period, timeframe)

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StrategyError(f"{field_.value} needs a numeric value.")

    return Condition(field_, operator, float(value), period, timeframe)


def parse_node(raw: Any, depth: int = 0, budget: list[int] | None = None) -> Node:
    """Build a rule tree, bounded in both depth and total conditions.

    The bounds are not politeness: an unbounded tree is a denial-of-service
    vector against the evaluator, and rejecting it at parse time keeps
    that entirely outside the running system.
    """
    if budget is None:
        budget = [MAX_CONDITIONS]
    if depth > MAX_DEPTH:
        raise StrategyError(f"Rules may nest at most {MAX_DEPTH} levels deep.")
    if not isinstance(raw, dict):
        raise StrategyError("A rule must be an object.")

    if "logic" in raw:
        try:
            logic = Logic(str(raw["logic"]).upper())
        except ValueError:
            raise StrategyError(f"Unknown logic {raw['logic']!r}.") from None
        children_raw = raw.get("children")
        if not isinstance(children_raw, list) or not children_raw:
            raise StrategyError(f"{logic.value} needs at least one condition.")
        if logic is Logic.NOT and len(children_raw) != 1:
            raise StrategyError("NOT takes exactly one condition.")
        children = tuple(
            parse_node(child, depth + 1, budget) for child in children_raw
        )
        return Group(logic, children)

    budget[0] -= 1
    if budget[0] < 0:
        raise StrategyError(
            f"A strategy may use at most {MAX_CONDITIONS} conditions."
        )
    return parse_condition(raw)


def count_conditions(node: Node) -> int:
    if isinstance(node, Condition):
        return 1
    return sum(count_conditions(child) for child in node.children)


# ------------------------------------------------------- evaluation

def _resolve(condition: Condition, market: dict) -> Any:
    """Read a field from the market snapshot.

    A field the snapshot does not carry returns None, and every operator
    treats None as "cannot say", never as zero or false. Section 30: if
    the data does not exist, the honest answer is that it is unavailable.
    """
    key = f"{condition.field.value}:{condition.timeframe}"
    if condition.period is not None:
        key = f"{key}:{condition.period}"
    if key in market:
        return market[key]
    return market.get(condition.field.value)


def evaluate_condition(condition: Condition, market: dict,
                       previous: dict | None = None) -> bool | None:
    """True, False, or None when the data needed is not available."""
    actual = _resolve(condition, market)
    if actual is None:
        return None

    expected = condition.value
    if isinstance(expected, Field):
        expected = _resolve(
            Condition(expected, condition.operator, None, condition.period,
                      condition.timeframe),
            market,
        )
        if expected is None:
            return None

    op = condition.operator
    if op is Operator.IS_TRUE:
        return bool(actual)
    if op is Operator.IS_FALSE:
        return not bool(actual)
    if op is Operator.EQUALS:
        return str(actual).upper() == str(expected).upper()
    if op is Operator.NOT_EQUALS:
        return str(actual).upper() != str(expected).upper()

    if op in (Operator.CROSSES_ABOVE, Operator.CROSSES_BELOW):
        # A cross needs the previous bar; without it the answer is unknown
        # rather than false, which would silently mean "did not cross".
        if previous is None:
            return None
        before = _resolve(condition, previous)
        before_expected = expected
        if isinstance(condition.value, Field):
            before_expected = _resolve(
                Condition(condition.value, op, None, condition.period,
                          condition.timeframe),
                previous,
            )
        if before is None or before_expected is None:
            return None
        try:
            if op is Operator.CROSSES_ABOVE:
                return before <= before_expected and actual > expected
            return before >= before_expected and actual < expected
        except TypeError:
            return None

    if op in ZONE_OPERATORS:
        inside = bool(actual)
        if previous is None:
            return None
        was_inside = bool(_resolve(condition, previous))
        return (inside and not was_inside) if op is Operator.ENTERS_ZONE \
            else (was_inside and not inside)

    try:
        if op is Operator.GT:
            return actual > expected
        if op is Operator.LT:
            return actual < expected
        if op is Operator.GTE:
            return actual >= expected
        if op is Operator.LTE:
            return actual <= expected
    except TypeError:
        return None
    return None


def evaluate(node: Node, market: dict, previous: dict | None = None
             ) -> bool | None:
    """Evaluate a rule tree.

    Unknown propagates rather than collapsing to False. A strategy whose
    data is missing has not "not matched" — nobody knows whether it
    matched, and saying so is what stops a data outage from looking like a
    market opinion.
    """
    if isinstance(node, Condition):
        return evaluate_condition(node, market, previous)

    results = [evaluate(child, market, previous) for child in node.children]

    if node.logic is Logic.NOT:
        inner = results[0]
        return None if inner is None else not inner

    if node.logic is Logic.AND:
        if any(r is False for r in results):
            return False          # one definite failure settles it
        return None if any(r is None for r in results) else True

    if any(r is True for r in results):
        return True               # one definite success settles OR
    return None if any(r is None for r in results) else False


@dataclass(slots=True)
class StrategyDefinition:
    name: str
    action_mode: ActionMode
    symbol: str
    timeframe: str
    direction: str
    rule: Node
    enabled: bool = True
    notes: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "action_mode": self.action_mode.value,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "direction": self.direction,
            "rule": self.rule.as_dict(),
            "enabled": self.enabled,
            "notes": self.notes,
            "condition_count": count_conditions(self.rule),
        }


def parse_strategy(raw: dict) -> StrategyDefinition:
    """Build a whole strategy, or refuse it. Never a partial acceptance."""
    if not isinstance(raw, dict):
        raise StrategyError("A strategy must be an object.")

    name = str(raw.get("name", "")).strip()
    if not 1 <= len(name) <= 80:
        raise StrategyError("Name must be between 1 and 80 characters.")

    try:
        mode = ActionMode(str(raw.get("action_mode", "")).upper())
    except ValueError:
        raise StrategyError(
            f"Unknown action mode {raw.get('action_mode')!r}. "
            f"Choose one of: {', '.join(m.value for m in ActionMode)}."
        ) from None

    direction = str(raw.get("direction", "")).upper()
    if direction not in ("BUY", "SELL"):
        raise StrategyError("Direction must be BUY or SELL.")

    timeframe = str(raw.get("timeframe", "M15")).upper()
    if timeframe not in TIMEFRAMES:
        raise StrategyError(f"Unsupported timeframe {timeframe!r}.")

    symbol = str(raw.get("symbol", "")).upper()
    if not 1 <= len(symbol) <= 24:
        raise StrategyError("Symbol is required.")

    notes = str(raw.get("notes", ""))
    if len(notes) > 500:
        raise StrategyError("Notes may be at most 500 characters.")

    rule = parse_node(raw.get("rule"))
    return StrategyDefinition(
        name=name, action_mode=mode, symbol=symbol, timeframe=timeframe,
        direction=direction, rule=rule,
        enabled=bool(raw.get("enabled", True)), notes=notes,
    )


def describe(node: Node, indent: int = 0) -> list[str]:
    """Render a rule as readable lines, for review before enabling it."""
    pad = "  " * indent
    if isinstance(node, Condition):
        target = node.value.value if isinstance(node.value, Field) else node.value
        period = f"({node.period})" if node.period else ""
        operator = node.operator.value.replace("_", " ").lower()
        if node.operator in (Operator.IS_TRUE, Operator.IS_FALSE):
            return [f"{pad}{node.field.value}{period} on {node.timeframe} "
                    f"is {'true' if node.operator is Operator.IS_TRUE else 'false'}"]
        return [f"{pad}{node.field.value}{period} on {node.timeframe} "
                f"{operator} {target}"]
    lines = [f"{pad}{node.logic.value}"]
    for child in node.children:
        lines.extend(describe(child, indent + 1))
    return lines
