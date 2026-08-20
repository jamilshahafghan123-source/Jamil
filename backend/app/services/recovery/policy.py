"""Recovery state machine and deterministic policies (sections 4, 6).

Policies are ordered lists of allow-listed operations with a verification
step. They are data, not code paths chosen at runtime, so what the system
is willing to do to a machine can be read off one table.

THE LOOP GUARD IS THE POINT
---------------------------
A recovery system that restarts a permanently broken service forever is
worse than none: it hides the fault and burns the machine. So attempts are
counted per service in a rolling window, spaced by exponential backoff, and
capped. On reaching the cap the service goes to NEEDS_ADMIN and stays there
until a human clears it — no timer walks it back to RECOVERING.

AUTH FAILURE IS NOT A RETRY CASE
--------------------------------
Bad credentials short-circuit straight to NEEDS_ADMIN with no attempt made.
Section 4 is explicit: never guess a token, never copy secrets between
files, never rewrite .env, never disable authentication. None of those are
possible from here, because the only things this module can emit are
Operation constants and none of them touch a secret.

TIME IS INJECTED
----------------
Every decision takes `now`, so the awkward cases — the third attempt inside
the window, the cooldown that expired one second ago — are tested against
a clock we control rather than by sleeping.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .operations import Operation


class ServiceState(str, enum.Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    RECOVERING = "RECOVERING"
    MONITORING = "MONITORING"
    #: Terminal without human action. Nothing automatic leaves this state.
    NEEDS_ADMIN = "NEEDS_ADMIN"
    FAILED = "FAILED"


class Service(str, enum.Enum):
    MT5 = "MT5"
    BRIDGE = "BRIDGE"
    DOCKER = "DOCKER"
    BACKEND = "BACKEND"
    FRONTEND = "FRONTEND"
    DATABASE = "DATABASE"
    MARKET_DATA = "MARKET_DATA"


class FailureCategory(str, enum.Enum):
    UNREACHABLE = "UNREACHABLE"
    PROCESS_STOPPED = "PROCESS_STOPPED"
    PORT_UNAVAILABLE = "PORT_UNAVAILABLE"
    AUTH_FAILURE = "AUTH_FAILURE"
    STALE_DATA = "STALE_DATA"
    HEALTH_CHECK_FAILED = "HEALTH_CHECK_FAILED"
    ENGINE_STOPPED = "ENGINE_STOPPED"


#: Attempts allowed inside `ATTEMPT_WINDOW` before a service is escalated.
MAX_ATTEMPTS = 3
ATTEMPT_WINDOW = timedelta(minutes=15)
#: Backoff between attempts: 30s, 60s, 120s.
BASE_COOLDOWN = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class Policy:
    """One deterministic recovery procedure."""

    service: Service
    #: Checks run before deciding anything, in order.
    diagnose: tuple[Operation, ...]
    #: The single mutating step. None means there is no safe automatic fix.
    repair: Operation | None
    #: Re-checked after a repair. A repair is not a success until this passes.
    verify: tuple[Operation, ...]
    description: str


POLICIES: dict[Service, Policy] = {
    Service.BRIDGE: Policy(
        service=Service.BRIDGE,
        diagnose=(Operation.CHECK_BRIDGE, Operation.CHECK_PORT_8100,
                  Operation.CHECK_MT5),
        repair=Operation.RESTART_BRIDGE,
        verify=(Operation.CHECK_BRIDGE, Operation.VERIFY_HEALTH),
        description=(
            "Confirm the bridge health check fails, check port 8100 and MT5, "
            "restart the bridge, then verify health and backend-to-bridge "
            "communication."
        ),
    ),
    Service.BACKEND: Policy(
        service=Service.BACKEND,
        diagnose=(Operation.CHECK_DOCKER, Operation.CHECK_BACKEND),
        repair=Operation.RESTART_BACKEND,
        verify=(Operation.CHECK_BACKEND, Operation.VERIFY_HEALTH),
        description=(
            "Verify the Docker engine first; only restart the backend "
            "container if the engine is healthy, then verify its health."
        ),
    ),
    Service.FRONTEND: Policy(
        service=Service.FRONTEND,
        diagnose=(Operation.CHECK_DOCKER, Operation.CHECK_FRONTEND),
        repair=Operation.RESTART_FRONTEND,
        verify=(Operation.CHECK_FRONTEND,),
        description="Verify the Docker engine, restart the frontend container.",
    ),
    Service.DATABASE: Policy(
        service=Service.DATABASE,
        diagnose=(Operation.CHECK_DOCKER, Operation.CHECK_DATABASE),
        repair=Operation.RESTART_DATABASE,
        verify=(Operation.CHECK_DATABASE,),
        description="Verify the Docker engine, restart the database container.",
    ),
    Service.MT5: Policy(
        service=Service.MT5,
        diagnose=(Operation.CHECK_MT5,),
        repair=Operation.START_MT5,
        verify=(Operation.CHECK_MT5,),
        description=(
            "Start the MT5 terminal, but only where the agent has been "
            "configured to allow it."
        ),
    ),
    Service.DOCKER: Policy(
        service=Service.DOCKER,
        diagnose=(Operation.CHECK_DOCKER,),
        # No automatic repair. Starting a stopped Docker engine is not
        # something to attempt blind from a remote process; section 4 asks
        # for detection and escalation rather than unsafe repair.
        repair=None,
        verify=(Operation.CHECK_DOCKER,),
        description=(
            "Detect that the Docker engine is stopped and escalate. No "
            "automatic repair is attempted."
        ),
    ),
    Service.MARKET_DATA: Policy(
        service=Service.MARKET_DATA,
        diagnose=(Operation.CHECK_BRIDGE, Operation.CHECK_MT5),
        # Stale prices are a symptom. Restarting things to "fix" a data gap
        # risks disturbing a healthy system, so this only observes; safe mode
        # has already paused automated trading by the time we get here.
        repair=None,
        verify=(Operation.CHECK_BRIDGE,),
        description=(
            "Diagnose stale market data by checking the bridge and MT5. No "
            "automatic repair; automated trading is already paused."
        ),
    ),
}


@dataclass
class AttemptRecord:
    """Rolling attempt history for one service."""

    attempts: list[datetime] = field(default_factory=list)
    state: ServiceState = ServiceState.HEALTHY
    last_result: str = ""

    def recent(self, now: datetime) -> list[datetime]:
        cutoff = now - ATTEMPT_WINDOW
        return [t for t in self.attempts if t > cutoff]


@dataclass(frozen=True, slots=True)
class Decision:
    """What the policy engine concluded. Nothing has happened yet."""

    service: Service
    state: ServiceState
    #: The operations to run, in order. Empty when nothing should be done.
    operations: tuple[Operation, ...]
    reason: str
    attempt_number: int = 0
    notify_severity: str | None = None


class RecoveryPlanner:
    """Decides what may be attempted. Executes nothing."""

    def __init__(self) -> None:
        self._records: dict[Service, AttemptRecord] = {}

    def record_for(self, service: Service) -> AttemptRecord:
        return self._records.setdefault(service, AttemptRecord())

    def state_of(self, service: Service) -> ServiceState:
        return self.record_for(service).state

    def clear(self, service: Service) -> None:
        """Human acknowledgement. The only way out of NEEDS_ADMIN."""
        self._records[service] = AttemptRecord()

    def mark_healthy(self, service: Service, *, now: datetime | None = None) -> None:
        rec = self.record_for(service)
        if rec.state is not ServiceState.NEEDS_ADMIN:
            rec.state = ServiceState.HEALTHY
            rec.attempts.clear()

    def plan(
        self,
        service: Service,
        category: FailureCategory,
        *,
        now: datetime | None = None,
    ) -> Decision:
        """Decide the response to one detected failure."""
        now = now or datetime.now(timezone.utc)
        rec = self.record_for(service)
        policy = POLICIES[service]

        # 1. Credentials. Never retried, never guessed at.
        if category is FailureCategory.AUTH_FAILURE:
            rec.state = ServiceState.NEEDS_ADMIN
            return Decision(
                service=service,
                state=ServiceState.NEEDS_ADMIN,
                operations=(),
                reason=(
                    "Authentication to the recovery agent or bridge failed. "
                    "Credential verification is required; no automatic retry "
                    "or secret change will be attempted."
                ),
                notify_severity="CRITICAL",
            )

        # 2. Already escalated. Stay put until a human clears it.
        if rec.state is ServiceState.NEEDS_ADMIN:
            return Decision(
                service=service,
                state=ServiceState.NEEDS_ADMIN,
                operations=(),
                reason="Already awaiting an administrator; not retrying.",
            )

        # 3. No safe automatic repair exists for this service.
        if policy.repair is None:
            rec.state = ServiceState.NEEDS_ADMIN
            return Decision(
                service=service,
                state=ServiceState.NEEDS_ADMIN,
                operations=policy.diagnose,
                reason=(
                    f"{service.value} has no safe automatic recovery. "
                    "Diagnosing and escalating."
                ),
                notify_severity="HIGH",
            )

        recent = rec.recent(now)

        # 4. Attempt cap inside the window.
        if len(recent) >= MAX_ATTEMPTS:
            rec.state = ServiceState.NEEDS_ADMIN
            return Decision(
                service=service,
                state=ServiceState.NEEDS_ADMIN,
                operations=(),
                reason=(
                    f"{service.value} recovery failed {len(recent)} times in "
                    f"{int(ATTEMPT_WINDOW.total_seconds() // 60)} minutes. "
                    "Escalating rather than restarting again."
                ),
                attempt_number=len(recent),
                notify_severity="HIGH",
            )

        # 5. Backoff between attempts: 30s, 60s, 120s.
        if recent:
            wait = BASE_COOLDOWN * (2 ** (len(recent) - 1))
            elapsed = now - max(recent)
            if elapsed < wait:
                rec.state = ServiceState.MONITORING
                remaining = int((wait - elapsed).total_seconds())
                return Decision(
                    service=service,
                    state=ServiceState.MONITORING,
                    operations=(),
                    reason=f"In cooldown for another {remaining}s.",
                    attempt_number=len(recent),
                )

        # 6. Attempt it.
        rec.attempts.append(now)
        rec.state = ServiceState.RECOVERING
        attempt = len(rec.recent(now))
        return Decision(
            service=service,
            state=ServiceState.RECOVERING,
            operations=(*policy.diagnose, policy.repair, *policy.verify),
            reason=f"Attempting recovery of {service.value} ({policy.description})",
            attempt_number=attempt,
            notify_severity="WARNING",
        )

    def settle(
        self,
        service: Service,
        *,
        verified_healthy: bool,
        now: datetime | None = None,
    ) -> ServiceState:
        """Record the outcome after the planned operations were run.

        A repair only counts if verification passed — section 4 requires the
        health check after the restart, not the restart alone.
        """
        rec = self.record_for(service)
        if rec.state is ServiceState.NEEDS_ADMIN:
            return rec.state
        if verified_healthy:
            rec.state = ServiceState.HEALTHY
            rec.attempts.clear()
        else:
            recent = rec.recent(now or datetime.now(timezone.utc))
            rec.state = (
                ServiceState.NEEDS_ADMIN
                if len(recent) >= MAX_ATTEMPTS
                else ServiceState.DEGRADED
            )
        return rec.state


#: Process-wide planner, mirroring how the rest of the services module works.
planner = RecoveryPlanner()
