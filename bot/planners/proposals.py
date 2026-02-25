# bot/planners/proposals.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from sc2.ids.unit_typeid import UnitTypeId


@dataclass(frozen=True)
class UnitRequirement:
    unit_type: UnitTypeId
    count: int


@dataclass(frozen=True)
class TaskSpec:
    """
    One atomic task inside a plan proposal.

    - task_factory: builds the task object. Ego will bind mission_id + assigned_tags.
    - unit_requirements: requirements local to this task (Ego will allocate a subset of tags).
    - lease_ttl: optional override for this task's leases (defaults to proposal.lease_ttl).
    """
    task_id: str
    task_factory: Callable[[str], object]
    unit_requirements: List[UnitRequirement] = field(default_factory=list)
    lease_ttl: Optional[float] = None


@dataclass(frozen=True)
class Proposal:
    """
    Plan proposal (NO legacy fallback).

    A Proposal is a PLAN composed of N TaskSpecs.
    Ego will:
      - pick proposal
      - create mission_id
      - claim units per TaskSpec (atomic admission)
      - build each task
      - bind mission context to each task
      - execute the plan every tick
    """
    proposal_id: str
    domain: str
    score: int

    # Plan
    tasks: List[TaskSpec] = field(default_factory=list)

    # Control
    lease_ttl: float = 30.0          # default lease TTL for tasks (can be overridden per TaskSpec)
    cooldown_s: float = 10.0
    risk_level: int = 1              # 0=low,1=med,2=high

    # Policy
    allow_preempt: bool = True

    def __post_init__(self) -> None:
        # Enforce "no fallback": a proposal must contain at least 1 TaskSpec
        if not self.tasks:
            raise ValueError(f"Proposal {self.proposal_id} must contain at least one TaskSpec")