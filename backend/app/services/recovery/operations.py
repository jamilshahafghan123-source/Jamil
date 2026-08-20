"""The complete set of things the recovery system can ask a machine to do.

Section 2. This enum *is* the allow-list. There is no operation that takes
a command, a script, a path or any other caller-supplied string, so there
is nothing for an LLM, a customer message, a web page or a webhook to inject
into. A request either names one of these constants or it is rejected — and
it is rejected on type, not by inspecting the string for danger, because
inspection is a filter somebody eventually gets past.

Nothing here executes anything. `agent.py` maps a constant to a fixed
endpoint on the Windows-side agent; that mapping is the only place an
operation becomes a request, and it is a lookup, never a format string.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Operation(str, enum.Enum):
    """Every permitted operation. Adding one is a deliberate diff here."""

    CHECK_MT5 = "CHECK_MT5"
    CHECK_BRIDGE = "CHECK_BRIDGE"
    CHECK_PORT_8100 = "CHECK_PORT_8100"
    CHECK_DOCKER = "CHECK_DOCKER"
    CHECK_BACKEND = "CHECK_BACKEND"
    CHECK_FRONTEND = "CHECK_FRONTEND"
    CHECK_DATABASE = "CHECK_DATABASE"
    RESTART_BRIDGE = "RESTART_BRIDGE"
    RESTART_BACKEND = "RESTART_BACKEND"
    RESTART_FRONTEND = "RESTART_FRONTEND"
    RESTART_DATABASE = "RESTART_DATABASE"
    START_MT5 = "START_MT5"
    VERIFY_HEALTH = "VERIFY_HEALTH"


#: Operations that only observe. Safe to run at any time, any number of
#: times: they change nothing, so they need no cooldown and no approval.
READ_ONLY: frozenset[Operation] = frozenset(
    {
        Operation.CHECK_MT5,
        Operation.CHECK_BRIDGE,
        Operation.CHECK_PORT_8100,
        Operation.CHECK_DOCKER,
        Operation.CHECK_BACKEND,
        Operation.CHECK_FRONTEND,
        Operation.CHECK_DATABASE,
        Operation.VERIFY_HEALTH,
    }
)

#: Operations that change machine state. Rate-limited, attempt-capped and
#: audited. Never triggered by anything a customer or a model can influence.
MUTATING: frozenset[Operation] = frozenset(Operation) - READ_ONLY


class UnknownOperationError(Exception):
    """Something that is not a member of Operation was offered."""


def parse(value: object) -> Operation:
    """Turn caller input into an Operation, or refuse.

    Accepts an Operation, or the exact string name of one. Anything else —
    a shell fragment, a dict, a model's prose — raises. This is the only
    door into the operation set, so "is it allow-listed" and "does it exist"
    are the same question.
    """
    if isinstance(value, Operation):
        return value
    if isinstance(value, str):
        try:
            return Operation(value)
        except ValueError:
            raise UnknownOperationError(
                f"{value!r} is not a permitted recovery operation"
            ) from None
    raise UnknownOperationError(
        f"expected a recovery operation, got {type(value).__name__}"
    )


def is_mutating(op: Operation) -> bool:
    return op in MUTATING


@dataclass(frozen=True, slots=True)
class OperationResult:
    """What came back. `detail` is operator-facing and carries no secret."""

    operation: Operation
    ok: bool
    detail: str = ""
    #: True when the agent itself rejected our credentials, which is a
    #: different problem from the operation failing. See policy.py.
    auth_failure: bool = False
    #: True when no agent is configured at all.
    unavailable: bool = False

    def as_dict(self) -> dict:
        return {
            "operation": self.operation.value,
            "ok": self.ok,
            "detail": self.detail,
            "auth_failure": self.auth_failure,
            "unavailable": self.unavailable,
        }
