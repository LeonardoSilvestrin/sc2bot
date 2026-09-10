"""The shape every behavior follows: assess -> plan -> execute.

These are deliberately small `Protocol`s rather than base classes. A
behavior is a *folder*, not a framework subclass: `behavior/harass/banshee/`
owns everything specific to Banshee harass, and these three names only fix
the vocabulary so that opening any behavior folder answers the same
questions in the same order.

    ASSESS    what is the situation, seen through this behavior's lens?
    PLAN      given that, what do we want, at what priority, with what units?
    EXECUTE   how do we make it happen this frame?

A behavior small enough not to need four files may collapse them; what it
may not do is blur the responsibilities. In particular an assessment only
*describes* -- it never takes ownership of a unit or creates a mission --
and a planner only *proposes* -- `MissionController` alone admits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from bot.engine.missions.execution import MissionContext, MissionResult
from bot.engine.missions.models import MissionProposal
from bot.ports.logging import BotLogger
from bot.world.attention import AttentionSnapshot
from bot.world.awareness import AwarenessSnapshot


@runtime_checkable
class BehaviorAssessment(Protocol):
    """One behavior's read of the current situation. Data, never a decision."""

    def log_fields(self) -> dict[str, Any]:
        """The handful of numbers worth seeing in the causal log."""
        ...


@runtime_checkable
class BehaviorAssessor(Protocol):
    """Turns Attention + Awareness into this behavior's own assessment.

    It reads the global world model; it never consults `MissionController`,
    leases, or mission status, and it never keeps a private second copy of
    Awareness state (e.g. its own `EnemyKnowledge`).
    """

    def assess(
        self, attention: AttentionSnapshot, awareness: AwarenessSnapshot
    ) -> BehaviorAssessment:
        ...


@runtime_checkable
class BehaviorPlanner(Protocol):
    """Turns an assessment into zero or more mission proposals."""

    planner_id: str

    def propose(
        self, attention: AttentionSnapshot, awareness: AwarenessSnapshot
    ) -> tuple[MissionProposal, ...]:
        ...


@runtime_checkable
class BehaviorExecutor(Protocol):
    """Runs one admitted mission, commanding only the units it was given."""

    mission_id: str

    async def step(self, context: MissionContext) -> MissionResult:
        ...


@dataclass(frozen=True, slots=True)
class BehaviorLog:
    """One behavior's slice of the causal log, safe to leave unwired.

    Behaviors are constructed in tests far more often than in a game, so the
    logger is optional and a missing one is silently a no-op rather than
    something every call site has to guard. The three verbs mirror the
    lifecycle: what the behavior saw, what it asked for, and what its
    executor is doing now -- `MissionController` already logs the admission,
    ownership and completion in between.
    """

    component: str
    logger: BotLogger | None = None

    def event(self, name: str, *, now: float, **data: Any) -> None:
        if self.logger is None:
            return
        self.logger.event(
            name, component=self.component, game_time=now, data=dict(data)
        )

    def assessed(
        self, assessment: BehaviorAssessment, *, now: float, decision: str
    ) -> None:
        self.event(
            "behavior.assessed", now=now, decision=decision, **assessment.log_fields()
        )

    def proposed(self, plan: Any, *, now: float, **extra: Any) -> None:
        fields = plan.log_fields() if hasattr(plan, "log_fields") else {}
        self.event("behavior.proposed", now=now, **fields, **extra)

    def state_changed(
        self, *, now: float, state: str, reason: str, **extra: Any
    ) -> None:
        self.event(
            "behavior.state_changed", now=now, state=state, reason=reason, **extra
        )


__all__ = [
    "BehaviorAssessment",
    "BehaviorAssessor",
    "BehaviorExecutor",
    "BehaviorLog",
    "BehaviorPlanner",
]
