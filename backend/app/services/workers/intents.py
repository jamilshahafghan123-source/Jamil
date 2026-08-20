"""What a worker is allowed to *return*.

Section 76's hard rule: no natural-language output may become SQL, a broker
API call, a payment-provider command, a withdrawal or a trade. The way that
is enforced here is by construction rather than by filtering — there is no
sanitiser to get wrong, because there is no code path that accepts a string
as an instruction in the first place.

A worker returns an Intent: a frozen, typed value naming a proposal. Every
field a downstream service acts on is a number, an enum or an identifier
the worker did not invent. Free text exists only in `rationale`, which is
for humans and is never dispatched on.

Executing an intent is somebody else's job. Nothing in this module touches
the database, the broker or the payment provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .capabilities import Capability


@dataclass(frozen=True, slots=True)
class Intent:
    """Base class. `required_capability` is what dispatching one would cost."""

    #: Human-readable justification. Displayed, logged — never executed.
    rationale: str = field(default="", kw_only=True)

    @property
    def required_capability(self) -> Capability:  # pragma: no cover - abstract
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class Explanation(Intent):
    """The default output: an answer, with the facts it leaned on.

    `facts` are copied out of a projection the worker was granted, so an
    explanation can be checked against real state rather than trusted. This
    is what stops a support answer being invented.
    """

    summary: str = ""
    facts: tuple[tuple[str, str], ...] = ()

    @property
    def required_capability(self) -> Capability:
        return Capability.RECOMMEND


@dataclass(frozen=True, slots=True)
class EscalateToAdmin(Intent):
    """The worker could not safely resolve it. Section 66's NEEDS_ADMIN."""

    category: Literal[
        "ACCOUNT",
        "LOGIN",
        "SUBSCRIPTION",
        "PAYMENT",
        "BROKER",
        "DEPOSIT_WITHDRAW",
        "TRADING",
        "DEMO",
        "CHART",
        "AI",
        "TECHNICAL",
        "OTHER",
    ] = "OTHER"
    priority: Literal["LOW", "NORMAL", "HIGH"] = "NORMAL"
    summary: str = ""

    @property
    def required_capability(self) -> Capability:
        return Capability.RECOMMEND


@dataclass(frozen=True, slots=True)
class ProposeSettingChange(Intent):
    """A suggested change to an application setting.

    Deliberately a *proposal*. Applying it is a WRITE, performed by the
    validated settings service against its own bounds checks — a worker
    naming a field does not make the value legal.
    """

    setting: str = ""
    proposed_value: float | int | bool | str = ""

    @property
    def required_capability(self) -> Capability:
        return Capability.WRITE


@dataclass(frozen=True, slots=True)
class ProposeTrade(Intent):
    """A trade a worker believes is warranted. Never an instruction.

    Carries a `signal_id` rather than prices: the signal was produced by the
    deterministic setup engine and stored, so the execution path re-reads it
    and cannot be handed levels an AI made up. It still passes through
    risk_engine.evaluate() exactly as a manual trade does.
    """

    signal_id: int = 0

    @property
    def required_capability(self) -> Capability:
        return Capability.FINANCIAL
