"""Regression test for the rate-limit dependency signature.

`deps.py` uses `from __future__ import annotations`, so annotations are
strings at runtime. FastAPI resolves a dependency's string annotations
against `call.__globals__`. A callable *class instance* has no `__globals__`,
so `request: Request` was left unresolved and became a required **query**
parameter — every `/api/*` route then rejected all traffic with
422 "query.request Field required".

These tests fail if the dependency ever regresses to a form FastAPI cannot
introspect.
"""

from fastapi import Request
from fastapi.dependencies.utils import get_dependant

from app.deps import login_rate_limit, rate_limit


def _dependant(call):
    return get_dependant(path="/test", call=call)


def test_rate_limit_exposes_no_query_parameters():
    dep = _dependant(rate_limit)
    assert dep.query_params == [], (
        "rate_limit must not add query parameters; FastAPI failed to resolve "
        f"its annotations: {[p.name for p in dep.query_params]}"
    )


def test_login_rate_limit_exposes_no_query_parameters():
    dep = _dependant(login_rate_limit)
    assert dep.query_params == [], (
        "login_rate_limit must not add query parameters: "
        f"{[p.name for p in dep.query_params]}"
    )


def test_rate_limit_receives_the_request_object():
    """The Request must be injected as a request param, not a value param."""
    dep = _dependant(rate_limit)
    assert dep.request_param_name == "request"
    assert dep.body_params == []


def test_request_parameter_is_typed_as_request():
    """The `request` parameter must resolve to `Request`, however it is built.

    Two shapes fix the original bug: a closure (what this repo uses), or a
    callable class in a module without `from __future__ import annotations`.
    Both are correct, so this inspects the underlying callable rather than
    assuming one implementation — otherwise the test reports a false alarm
    against a perfectly valid alternative.
    """
    import inspect
    import typing

    target = rate_limit if inspect.isfunction(rate_limit) else type(rate_limit).__call__
    hints = typing.get_type_hints(target)
    assert hints.get("request") is Request
