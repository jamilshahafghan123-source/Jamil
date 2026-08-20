"""The chokepoint. Every worker output passes through authorize().

Two things are enforced here, and they are the whole point of the module:

1. A worker may only emit intents its grant covers. Since no role holds
   FINANCIAL, a worker proposing a trade is refused here — the proposal has
   to be taken up by the execution service, which is not a worker and which
   still runs risk_engine.evaluate(). There is no argument to authorize()
   that relaxes this.

2. Only typed Intent instances are accepted. A str, dict or JSON blob is
   refused on type, not on content. That is deliberate: content inspection
   is a filter someone eventually gets past, whereas "a string is not an
   intent" has no bypass. This is what stops customer chat text — the
   likeliest injection vector on a support surface — from ever reaching a
   dispatcher.
"""

from __future__ import annotations

import logging

from .capabilities import (
    Capability,
    PermissionDeniedError,
    WorkerRole,
    require_capability,
)
from .intents import Intent

log = logging.getLogger(__name__)


class UnsafeInstructionError(Exception):
    """Something that was not a typed Intent was offered for dispatch."""


def authorize(role: WorkerRole, intent: object) -> Intent:
    """Check a worker's output. Returns it on success, raises otherwise.

    Callers must use the return value, not the object they passed in, so
    that the check cannot be skipped by accident.
    """
    if not isinstance(intent, Intent):
        # Refused on type. Never inspect the value and decide it looks safe.
        log.warning(
            "worker %s offered a non-intent (%s); refusing",
            role.value,
            type(intent).__name__,
        )
        raise UnsafeInstructionError(
            f"worker {role.value} returned {type(intent).__name__}, not an Intent; "
            "free-form output is never dispatched"
        )

    capability = intent.required_capability
    require_capability(role, capability)

    if capability is Capability.FINANCIAL:
        # Unreachable while no grant includes FINANCIAL, and kept as a second
        # lock so that adding such a grant is not quietly sufficient to move
        # money: execution still belongs to the validated services.
        raise PermissionDeniedError(
            f"worker {role.value} may not take financial action directly; "
            "route the proposal through the execution service"
        )

    return intent


def authorize_all(role: WorkerRole, intents: object) -> tuple[Intent, ...]:
    """authorize() over a sequence, all-or-nothing.

    A batch that contains one bad intent is refused entirely rather than
    partially applied, so a worker cannot smuggle an action through by
    burying it among valid ones.
    """
    if isinstance(intents, (str, bytes, dict)) or not hasattr(intents, "__iter__"):
        raise UnsafeInstructionError(
            f"expected a sequence of Intent, got {type(intents).__name__}"
        )
    return tuple(authorize(role, item) for item in intents)
