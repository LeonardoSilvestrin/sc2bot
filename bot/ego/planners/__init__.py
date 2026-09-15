"""PLANNERS: what should be done.

Each planner reads Attention, Awareness and Strategy, computes its own
priority from its local signals, modulated directly by `StrategyState`, and
hands complete plans to the Body: a task, a target, a priority and the units
it requires. A planner never names a unit -- the Engine decides who gets each
proposal, and the Body's behaviors how it is carried out.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2


class Command(str, Enum):
    # Fight at the target.
    ATTACK = "ATTACK"
    # Hold the target and fight whatever comes there.
    HOLD = "HOLD"
    # Go and look at the target; a worker stops mining for it.
    SCOUT = "SCOUT"


class Domain(str, Enum):
    """Where a target is, so what a unit must be able to shoot at."""

    GROUND = "GROUND"
    AIR = "AIR"


@dataclass(frozen=True, slots=True)
class Proposal:
    proposal_id: str
    owner: str
    priority: float
    command: Command
    target: Point2
    reason: str
    # How many units; None asks for every eligible unit still free.
    count: int | None = None
    # Which unit types; None accepts any army unit. Only a proposal that names
    # a worker type can be granted workers.
    unit_types: frozenset[UnitTypeId] | None = None
    # The values the priority and size were computed from.
    inputs: tuple[tuple[str, float], ...] = ()
    # Power, in Marines, the grant should reach: the Engine grants units until
    # it does. None sizes the grant by `count` instead.
    minimum_power: float | None = None
    # What every granted unit must be able to shoot at; None asks nothing.
    must_attack: Domain | None = None
    # The coordinated demand this proposal is one part of; its parts share one
    # budget. None for a proposal that stands alone.
    demand_id: str | None = None


@dataclass(frozen=True, slots=True)
class EconomyPlan:
    # False while Ares' build runner still plays the opening.
    active: bool
    workers: int
    gas: int
    bases: int
    expand: bool
    # Spend on army regardless of the composition's proportions.
    freeflow: bool
    # (unit type, proportion, priority): lower priority numbers build first.
    composition: tuple[tuple[UnitTypeId, float, int], ...]
    reason: str


@dataclass(frozen=True, slots=True)
class StructurePlan:
    # Supply depots to lower, by tag.
    lower: tuple[int, ...]
    reason: str
    inputs: tuple[tuple[str, float], ...] = ()
    # Supply depots to raise, by tag.
    raise_: tuple[int, ...] = ()
