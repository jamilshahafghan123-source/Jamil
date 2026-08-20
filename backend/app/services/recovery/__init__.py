"""Safe Windows health and recovery.

The LLM path and the OS path never meet: `operations.py` is a closed enum,
`agent.py` maps constants to fixed endpoints, and no function anywhere in
this package accepts a command, a script or a path.
"""

from . import notifications, policy
from .agent import WindowsAgent, agent
from .operations import (
    MUTATING,
    READ_ONLY,
    Operation,
    OperationResult,
    UnknownOperationError,
    is_mutating,
    parse,
)
from .policy import (
    POLICIES,
    Decision,
    FailureCategory,
    RecoveryPlanner,
    Service,
    ServiceState,
    planner,
)

__all__ = [
    "MUTATING", "POLICIES", "READ_ONLY", "Decision", "FailureCategory",
    "Operation", "OperationResult", "RecoveryPlanner", "Service",
    "ServiceState", "UnknownOperationError", "WindowsAgent", "agent",
    "is_mutating", "notifications", "parse", "planner", "policy",
]
