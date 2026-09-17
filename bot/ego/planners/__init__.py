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
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2


class Command(str, Enum):
    # Fight at the target.
    ATTACK = "ATTACK"
    # Hold the target and fight whatever comes there.
    HOLD = "HOLD"
    # Go and look at the target; a worker stops mining for it.
    SCOUT = "SCOUT"
    # Walk back to the target without stopping to fight.
    RETREAT = "RETREAT"


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
    # The values the plan was computed from.
    inputs: tuple[tuple[str, float], ...] = ()
    # Upgrades to research, in order; the tech they need is built on the way.
    upgrades: tuple[UpgradeId, ...] = ()
    # Turn idle Command Centers into Orbital Commands.
    orbitals: bool = False
    # Orbital Commands spend their energy on MULEs.
    mules: bool = False
    # Stop Ares' build runner: the opening is over from this frame on.
    interrupt_opening: bool = False
    # The most structures of one production type (Barracks, Factory, Starport)
    # Ares may build; how many it builds within that is its income rule.
    max_production: int = 12
    # Add a Reactor to a Barracks with no add-on: two Marines at a time.
    reactors: bool = False
    # Barracks that stay without an add-on, so Ares can still put a Tech Lab
    # on one when the composition asks for Marauders.
    techlab_reserve: int = 1


@dataclass(frozen=True, slots=True)
class StructurePlan:
    # Supply depots to lower, by tag.
    lower: tuple[int, ...]
    reason: str
    inputs: tuple[tuple[str, float], ...] = ()
    # Supply depots to raise, by tag.
    raise_: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class DetectionPlan:
    # Where an Orbital Command should scan this frame; None for nowhere.
    scan: Point2 | None
    # Positions of our bases that need a Missile Turret, by base id.
    turrets: tuple[Point2, ...]
    # Build an Engineering Bay: the turrets need one.
    engineering_bay: bool
    # Energy every Orbital Command keeps for a scan instead of a MULE.
    energy_reserve: float
    reason: str
    inputs: tuple[tuple[str, float], ...] = ()
