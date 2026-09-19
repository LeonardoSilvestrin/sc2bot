"""CONTRACTS: what the planners hand the Body.

- `Proposal`, with its `Command` and `Domain`: what a domain planner asks
  the Engine for.
- `EconomyPlan`: what Ares' macro behaviors should buy.
- `StructurePlan`: which existing structure acts, and how (`RelocationEvent`).
- `IntelPlan`: scouting proposals, detection and information infrastructure.
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
    # The mission (`bot.ego.missions`) that made it; None for a planner without
    # missions. A mission may make several proposals, and keeps a proposal's
    # id across its phases so the Engine keeps the same units.
    mission_id: str | None = None


@dataclass(frozen=True, slots=True)
class CounterAdaptation:
    enemy: UnitTypeId
    canonical: UnitTypeId
    power: float
    response: UnitTypeId | None
    # Alternatives rejected before the selected response.
    skipped: tuple[tuple[UnitTypeId, str], ...] = ()
    # selected, known_no_counter, uncatalogued or no_producible_counter.
    status: str = "selected"


@dataclass(frozen=True, slots=True)
class SurvivalComposition:
    incident_id: str
    # Types added to the normal target so freeflow can use ready capacity.
    added: tuple[tuple[UnitTypeId, str], ...]


@dataclass(frozen=True, slots=True)
class CompositionPlan:
    style: str
    baseline: tuple[tuple[UnitTypeId, float, int], ...]
    # Observed type, canonical type and remembered power.
    enemy: tuple[tuple[UnitTypeId, UnitTypeId, float], ...]
    adaptations: tuple[CounterAdaptation, ...]
    survival: SurvivalComposition | None
    # Count proportions consumed by Ares.
    units: tuple[tuple[UnitTypeId, float, int], ...]
    tech_ready: tuple[UnitTypeId, ...]
    reason: str


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
    # Put an add-on on an idle `addons_on` with none: a Reactor trains two
    # units at a time, a Tech Lab what needs one.
    addons: bool = False
    # The production structure that takes those add-ons.
    addons_on: UnitTypeId = UnitTypeId.BARRACKS
    # The share of those structures that should carry a Reactor; the rest take
    # Tech Labs.
    reactor_share: float = 1.0
    # The army style the composition and the upgrades come from.
    army: str = "bio"
    # Explanation of how the final composition was obtained.
    composition_plan: CompositionPlan | None = None


@dataclass(frozen=True, slots=True)
class RelocationEvent:
    """One step of moving a production structure out of a Siege Tank's way."""

    # tank_stuck, blocker_selected, lifting, tank_moving, tank_gone,
    # tank_still_stuck, relocating, no_landing_site, landing,
    # relocation_complete or relocation_aborted.
    transition: str
    reason: str
    tank: int | None = None
    structure: int | None = None
    # The landing site, or where the structure landed.
    site: Point2 | None = None
    inputs: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True, slots=True)
class StructurePlan:
    # Supply depots to lower, by tag.
    lower: tuple[int, ...]
    reason: str
    inputs: tuple[tuple[str, float], ...] = ()
    # Supply depots to raise, by tag.
    raise_: tuple[int, ...] = ()
    # Production structures to lift out of a Siege Tank's way, by tag.
    lift: tuple[int, ...] = ()
    # Flying structures to fly to a site and land on it: (tag, site).
    land: tuple[tuple[int, Point2], ...] = ()
    # What the relocation did this frame, in order.
    relocation: tuple[RelocationEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class DetectionPlan:
    # Where an Orbital Command should scan this frame; None for nowhere.
    scan: Point2 | None
    # Positions of our bases that need a Missile Turret, by base id.
    turrets: tuple[Point2, ...]
    # Missing prerequisite; Intel consolidates the build request.
    engineering_bay: bool
    # Energy every Orbital Command keeps for a scan instead of a MULE.
    energy_reserve: float
    reason: str
    inputs: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True, slots=True)
class SensorTowerSite:
    """A Sensor Tower wanted for one owned base.

    ``base`` selects that base's Ares placement set; ``target`` biases the
    placement toward the exposed side of the base.
    """

    base_id: str
    base: Point2
    target: Point2


@dataclass(frozen=True, slots=True)
class SensorTowerPlan:
    # Sites which do not have a Sensor Tower yet (unfinished towers count).
    sites: tuple[SensorTowerSite, ...]
    # Missing prerequisite; Intel consolidates the build request.
    engineering_bay: bool
    reason: str
    inputs: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True, slots=True)
class IntelPlan:
    """Everything the Intel domain asks the Body to do this frame."""

    proposals: tuple[Proposal, ...]
    detection: DetectionPlan
    sensor_towers: SensorTowerPlan
    # Consolidated infrastructure request; only the Intel executor builds it.
    engineering_bay: bool
