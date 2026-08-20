"""Safe strategy builder (sections 32-37).

The central property: a customer can DESCRIBE a strategy but can never
SUPPLY BEHAVIOUR. Everything else here follows from that.
"""

import ast
import inspect

import pytest

from app.services import strategy as S
from app.services.strategy import ActionMode, Field, Logic, Operator, StrategyError


def rule(**kw):
    base = {"field": "RSI", "operator": "GT", "value": 55, "period": 14,
            "timeframe": "M15"}
    base.update(kw)
    return base


# ------------------------------------------------- no code execution

def test_the_module_contains_no_execution_primitive():
    """Section 32 forbids running customer code.

    The safest way to honour that is to have no mechanism capable of it.
    This walks the AST rather than scanning text, so the module's own
    prose about eval cannot pass or fail the test by accident.
    """
    tree = ast.parse(inspect.getsource(S))
    called: set[str] = set()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called.add(node.func.id)
        elif isinstance(node, ast.Attribute):
            called.add(node.attr)
        elif isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])

    for forbidden in ("eval", "exec", "compile", "__import__", "getattr",
                      "setattr", "globals", "locals", "system", "popen",
                      "check_output", "Popen"):
        assert forbidden not in called, f"strategy module calls {forbidden}"
    for forbidden in ("os", "subprocess", "importlib", "sys", "pickle",
                      "marshal", "ctypes", "socket"):
        assert forbidden not in imported, f"strategy module imports {forbidden}"


def test_an_unknown_field_is_refused_not_looked_up():
    for attempt in ("__import__", "os.system", "eval", "__builtins__",
                    "subprocess", "open", "RSI; DROP TABLE users"):
        with pytest.raises(StrategyError):
            S.parse_condition(rule(field=attempt))


def test_an_unknown_operator_is_refused():
    for attempt in ("EXEC", "EVAL", "__call__", "; rm -rf /"):
        with pytest.raises(StrategyError):
            S.parse_condition(rule(operator=attempt))


def test_a_string_payload_cannot_reach_a_numeric_field():
    with pytest.raises(StrategyError):
        S.parse_condition(rule(value="os.system('id')"))


def test_real_broker_automation_is_not_an_option_that_exists():
    """A mode that does not exist cannot be selected or reached."""
    assert "REAL_AUTO" not in ActionMode.__members__
    assert {m.value for m in ActionMode} == {
        "ALERT_ONLY", "AI_ASSIST", "DEMO_AUTO"
    }
    with pytest.raises(StrategyError):
        S.parse_strategy({"name": "x", "action_mode": "REAL_AUTO",
                          "symbol": "XAUUSD", "direction": "BUY",
                          "rule": rule()})


# -------------------------------------------------------- validation

def test_the_specifications_worked_example_parses():
    """Section 33, as written."""
    parsed = S.parse_strategy({
        "name": "London EMA continuation", "action_mode": "ALERT_ONLY",
        "symbol": "XAUUSD", "timeframe": "M15", "direction": "BUY",
        "rule": {"logic": "AND", "children": [
            {"field": "EMA", "operator": "CROSSES_ABOVE", "value": "SMA",
             "period": 20, "timeframe": "M15"},
            rule(),
            {"field": "SESSION_ACTIVE", "operator": "IS_TRUE"},
            {"field": "AI_CONFIDENCE", "operator": "GTE", "value": 70},
            {"field": "RISK_REWARD", "operator": "GTE", "value": 1.5},
        ]},
    })
    assert S.count_conditions(parsed.rule) == 5


def test_depth_and_condition_count_are_bounded():
    """An unbounded tree is a denial-of-service vector, refused at parse."""
    deep = rule()
    for _ in range(S.MAX_DEPTH + 2):
        deep = {"logic": "AND", "children": [deep]}
    with pytest.raises(StrategyError):
        S.parse_node(deep)

    wide = {"logic": "AND", "children": [rule()] * (S.MAX_CONDITIONS + 5)}
    with pytest.raises(StrategyError):
        S.parse_node(wide)


def test_a_label_field_refuses_a_value_outside_its_set():
    with pytest.raises(StrategyError):
        S.parse_condition({"field": "TREND", "operator": "EQUALS",
                           "value": "SIDEWAYS-ISH"})
    parsed = S.parse_condition({"field": "TREND", "operator": "EQUALS",
                                "value": "bullish"})
    assert parsed.value == "BULLISH"


def test_a_label_field_cannot_be_compared_numerically():
    with pytest.raises(StrategyError):
        S.parse_condition({"field": "TREND", "operator": "GT",
                           "value": "BULLISH"})


def test_a_boolean_operator_needs_a_boolean_field():
    with pytest.raises(StrategyError):
        S.parse_condition({"field": "RSI", "operator": "IS_TRUE"})


def test_a_zone_operator_needs_a_zone_field():
    with pytest.raises(StrategyError):
        S.parse_condition({"field": "RSI", "operator": "ENTERS_ZONE",
                           "value": 1})


def test_unsupported_timeframes_and_periods_are_refused():
    with pytest.raises(StrategyError):
        S.parse_condition(rule(timeframe="M7"))
    with pytest.raises(StrategyError):
        S.parse_condition(rule(period=0))
    with pytest.raises(StrategyError):
        S.parse_condition(rule(period=10_000))
    with pytest.raises(StrategyError):
        S.parse_condition(rule(period=True))


def test_not_takes_exactly_one_condition():
    with pytest.raises(StrategyError):
        S.parse_node({"logic": "NOT", "children": [rule(), rule()]})


def test_a_partially_valid_strategy_is_refused_whole():
    """Never a partial acceptance: half a strategy is not a strategy."""
    with pytest.raises(StrategyError):
        S.parse_strategy({
            "name": "half good", "action_mode": "ALERT_ONLY",
            "symbol": "XAUUSD", "direction": "BUY",
            "rule": {"logic": "AND", "children": [rule(), rule(field="NONSENSE")]},
        })


# -------------------------------------------------------- evaluation

def test_conditions_evaluate_against_a_snapshot():
    node = S.parse_node(rule())
    assert S.evaluate(node, {"RSI:M15:14": 60}) is True
    assert S.evaluate(node, {"RSI:M15:14": 50}) is False


def test_missing_data_is_unknown_rather_than_false():
    """Section 30: absent data must not masquerade as a market opinion."""
    node = S.parse_node(rule())
    assert S.evaluate(node, {}) is None


def test_and_settles_on_a_definite_failure_but_not_on_a_gap():
    node = S.parse_node({"logic": "AND", "children": [
        rule(), rule(field="ADX", operator="GT", value=25, period=14)]})
    # One definite failure settles it even with the other unknown.
    assert S.evaluate(node, {"RSI:M15:14": 10}) is False
    # One known success plus one gap is not a match — it is unknown.
    assert S.evaluate(node, {"RSI:M15:14": 60}) is None


def test_or_settles_on_a_definite_success():
    node = S.parse_node({"logic": "OR", "children": [
        rule(), rule(field="ADX", operator="GT", value=25, period=14)]})
    assert S.evaluate(node, {"RSI:M15:14": 60}) is True
    assert S.evaluate(node, {}) is None


def test_not_propagates_unknown():
    node = S.parse_node({"logic": "NOT", "children": [rule()]})
    assert S.evaluate(node, {"RSI:M15:14": 10}) is True
    assert S.evaluate(node, {}) is None


def test_a_cross_without_a_previous_bar_is_unknown_not_false():
    """"Did not cross" and "cannot tell" are different answers."""
    node = S.parse_node({"field": "EMA", "operator": "CROSSES_ABOVE",
                         "value": "SMA", "period": 20})
    market = {"EMA:M15:20": 10, "SMA:M15:20": 9}
    assert S.evaluate(node, market) is None
    previous = {"EMA:M15:20": 8, "SMA:M15:20": 9}
    assert S.evaluate(node, market, previous) is True
    # No cross when it was already above.
    assert S.evaluate(node, market, {"EMA:M15:20": 9.5, "SMA:M15:20": 9}) is False


def test_comparing_incompatible_types_is_unknown_rather_than_crashing():
    node = S.parse_node(rule())
    assert S.evaluate(node, {"RSI:M15:14": "not a number"}) is None


def test_describe_renders_a_reviewable_rule():
    parsed = S.parse_node({"logic": "AND", "children": [
        rule(), {"field": "SESSION_ACTIVE", "operator": "IS_TRUE"}]})
    lines = S.describe(parsed)
    assert lines[0] == "AND"
    assert any("RSI(14)" in line for line in lines)
    assert any("is true" in line for line in lines)


def test_a_strategy_carries_no_execution_authority():
    """Section 37: a strategy proposes; it never places.

    The definition is data only — it has no method that could place,
    close, or send anything.
    """
    parsed = S.parse_strategy({
        "name": "n", "action_mode": "DEMO_AUTO", "symbol": "XAUUSD",
        "direction": "BUY", "rule": rule(),
    })
    for forbidden in ("place", "execute", "send", "order", "close", "submit"):
        assert not any(
            forbidden in attribute.lower() for attribute in dir(parsed)
            if not attribute.startswith("_")
        ), f"strategy definition exposes {forbidden}"
