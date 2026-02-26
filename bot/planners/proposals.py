# bot/planners/proposals.py
from __future__ import annotations

from dataclasses import dataclass, field
import inspect
from typing import Callable, List, Optional

from sc2.ids.unit_typeid import UnitTypeId


@dataclass(frozen=True)
class UnitRequirement:
    unit_type: UnitTypeId
    count: int

    def validate(self) -> None:
        if not isinstance(self.unit_type, UnitTypeId):
            raise TypeError(f"UnitRequirement.unit_type must be UnitTypeId, got {type(self.unit_type)!r}")
        if not isinstance(self.count, int):
            raise TypeError(f"UnitRequirement.count must be int, got {type(self.count)!r}")
        if self.count <= 0:
            raise ValueError("UnitRequirement.count must be > 0")


@dataclass(frozen=True)
class TaskSpec:
    """
    One atomic task inside a proposal.

    Contract (strict):
      - task_id: non-empty string
      - task_factory: callable(mission_id: str) -> task instance
      - unit_requirements: list[UnitRequirement]
    """
    task_id: str
    task_factory: Callable[[str], object]
    unit_requirements: List[UnitRequirement] = field(default_factory=list)
    lease_ttl: Optional[float] = None

    def validate(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("TaskSpec.task_id must be a non-empty string")
        if not callable(self.task_factory):
            raise TypeError("TaskSpec.task_factory must be callable")

        # Ensure task_factory signature is (mission_id: str) (or compatible)
        try:
            sig = inspect.signature(self.task_factory)
        except (TypeError, ValueError) as e:
            raise TypeError(f"TaskSpec.task_factory must have an inspectable signature: {e}") from e

        params = list(sig.parameters.values())
        if len(params) != 1:
            raise TypeError("TaskSpec.task_factory must accept exactly 1 parameter: mission_id")

        for r in self.unit_requirements:
            if not isinstance(r, UnitRequirement):
                raise TypeError(f"TaskSpec.unit_requirements must contain UnitRequirement, got {type(r)!r}")
            r.validate()

        if self.lease_ttl is not None:
            if not isinstance(self.lease_ttl, (int, float)):
                raise TypeError("TaskSpec.lease_ttl must be a number")
            if float(self.lease_ttl) <= 0.0:
                raise ValueError("TaskSpec.lease_ttl must be > 0")


@dataclass(frozen=True)
class Proposal:
    """
    Admission request from a Planner to Ego.

    Current policy:
      - A Proposal contains EXACTLY ONE TaskSpec (single-task-per-proposal).
      - No fallbacks / compat layers. Validation is strict; invalid proposals crash fast.
    """
    proposal_id: str
    domain: str
    score: int

    tasks: List[TaskSpec] = field(default_factory=list)

    lease_ttl: float = 30.0
    cooldown_s: float = 10.0
    risk_level: int = 1
    allow_preempt: bool = True

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if not isinstance(self.proposal_id, str) or not self.proposal_id.strip():
            raise ValueError("Proposal.proposal_id must be a non-empty string")
        if not isinstance(self.domain, str) or not self.domain.strip():
            raise ValueError("Proposal.domain must be a non-empty string")
        if not isinstance(self.score, int):
            raise TypeError("Proposal.score must be int")

        if not isinstance(self.tasks, list) or len(self.tasks) != 1:
            raise ValueError("Proposal.tasks must contain exactly 1 TaskSpec (single-task-per-proposal)")

        t0 = self.tasks[0]
        if not isinstance(t0, TaskSpec):
            raise TypeError(f"Proposal.tasks[0] must be TaskSpec, got {type(t0)!r}")
        t0.validate()

        if not isinstance(self.lease_ttl, (int, float)):
            raise TypeError("Proposal.lease_ttl must be a number")
        if float(self.lease_ttl) <= 0.0:
            raise ValueError("Proposal.lease_ttl must be > 0")

        if not isinstance(self.cooldown_s, (int, float)):
            raise TypeError("Proposal.cooldown_s must be a number")
        if float(self.cooldown_s) < 0.0:
            raise ValueError("Proposal.cooldown_s must be >= 0")

        if not isinstance(self.risk_level, int):
            raise TypeError("Proposal.risk_level must be int")
        if self.risk_level < 0:
            raise ValueError("Proposal.risk_level must be >= 0")

        if not isinstance(self.allow_preempt, bool):
            raise TypeError("Proposal.allow_preempt must be bool")

    def task(self) -> TaskSpec:
        # validated in __post_init__
        return self.tasks[0]