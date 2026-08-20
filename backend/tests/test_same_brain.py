"""One authoritative trading brain (sections 38-40).

The rule: Demo and Real must share the analysis, the strategy logic, the
scoring, the decision and the risk manager, and differ ONLY in which
execution adapter receives the approved order.

These tests are structural on purpose. Asserting that two code paths
happen to agree on one sample input proves nothing; asserting that only
one implementation exists is what actually holds the property.
"""

import ast
import inspect
from pathlib import Path

from app.services import demo_execution, executor, opportunity, risk_engine

SERVICES = Path(risk_engine.__file__).parent


def _calls(module) -> set[str]:
    """Every dotted call target in a module's source."""
    tree = ast.parse(inspect.getsource(module))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        parts: list[str] = []
        while isinstance(target, ast.Attribute):
            parts.append(target.attr)
            target = target.value
        if isinstance(target, ast.Name):
            parts.append(target.id)
            found.add(".".join(reversed(parts)))
    return found


def test_both_venues_call_the_same_risk_manager():
    """Neither venue may carry a risk check of its own."""
    assert "risk_engine.evaluate" in _calls(demo_execution)
    assert "risk_engine.evaluate" in _calls(executor)


def test_there_is_exactly_one_risk_engine():
    matches = sorted(p.name for p in SERVICES.glob("*risk*"))
    assert matches == ["risk_engine.py"]


def test_no_venue_specific_trading_brain_exists():
    """No DemoStrategyEngine / RealStrategyEngine split (section 38).

    A second engine is how Demo results stop predicting Real behaviour,
    which makes every hour of demo calibration worthless.
    """
    forbidden = (
        "demo_strategy", "real_strategy", "demo_analysis", "real_analysis",
        "demo_setup", "real_setup", "demo_opportunity", "real_opportunity",
        "demo_risk", "real_risk", "demo_analyst", "real_analyst",
    )
    names = [p.stem.lower() for p in SERVICES.rglob("*.py")]
    for name in names:
        for banned in forbidden:
            assert banned not in name, f"venue-specific brain: {name}.py"


def test_the_shared_decision_modules_are_venue_agnostic():
    """The brain must not know which venue it is deciding for.

    If `opportunity` or `risk_engine` ever branches on "demo" or "broker",
    the single-brain property is gone even with one file.
    """
    for module in (opportunity, risk_engine):
        source = inspect.getsource(module).lower()
        for banned in ("is_demo", "if demo:", "if broker:", "demo_only",
                       "real_only"):
            assert banned not in source, f"{module.__name__} branches on venue"


def test_setup_classification_is_shared_not_duplicated():
    """One SetupClass definition, used by whatever executes."""
    assert [c.value for c in opportunity.SetupClass] == [
        "A_PLUS", "STANDARD", "SCALP"
    ]
    matches = sorted(p.name for p in SERVICES.glob("*opportunit*"))
    assert matches == ["opportunity.py"]


def test_demo_execution_still_cannot_reach_a_broker():
    """The isolation rule, restated alongside the shared-brain rule.

    Sharing a brain must never become sharing an execution path.
    """
    calls = _calls(demo_execution)
    source = inspect.getsource(demo_execution)
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
    for banned in ("mt5", "mt5_client", "executor", "bridge", "broker_adapter"):
        assert banned not in imported, f"demo_execution imported {banned}"
        assert not any(c.startswith(f"{banned}.") for c in calls), \
            f"demo_execution called {banned}"


def test_risk_decision_reports_what_it_required():
    """Section 59: a refusal must say exactly what it wanted.

    Carrying the applied thresholds on the decision is what lets the AI
    panel explain a NO TRADE instead of merely announcing one.
    """
    decision = risk_engine.RiskDecision(approved=True)
    for attribute in ("setup_class", "required_confidence", "required_rr"):
        assert hasattr(decision, attribute)


def test_an_unknown_setup_label_defaults_to_the_stricter_class():
    """An unrecognised label must never land on the most permissive class."""
    for label in (None, "", "nonsense", "SCALPY", 42):
        assert risk_engine.requirement_class(label) == "STANDARD"
