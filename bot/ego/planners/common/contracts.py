"""CONTRACTS: what the planners hand the Body.

- `Proposal`, with its `Command` and `Domain`: what a domain planner asks
  the Engine for.
- `StructurePlan`: which existing structure acts, and how (`RelocationEvent`).
- `IntelPlan`: scouting proposals, detection and information infrastructure,
  with `EarlyScoutReport` telling where the early scout stands.

What the economy hands the Body is in `bot.ego.economy.contracts`.
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
    # The mission (`bot.ego.planners.common.mission`) that made it; None for a planner without
    # missions. A mission may make several proposals, and keeps a proposal's
    # id across its phases so the Engine keeps the same units.
    mission_id: str | None = None


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
    # Where the Tank stood, when it was found stuck and its blocker chosen.
    at: Point2 | None = None


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
    """A Sensor Tower wanted in the barrier, on a 2x2 spot Ares solved.

    ``site_id`` is the id of the base the spot belongs to. ``base`` is the
    expansion keying Ares' placement set that holds the spot; ``target`` is
    the spot.
    """

    site_id: str
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
class EarlyScoutReport:
    """Where the early scout stands, for the log: its phase, what moved it
    there and what it is walking to."""

    mission_id: str
    phase: str
    # The phase it left; None while it has not changed phase yet.
    previous: str | None
    since: float
    # Why the phase, or the terminal status, was entered.
    reason: str
    status: str
    target: Point2 | None
    # Whether the planner has ordered the proxy search.
    proxy_search: bool
    inputs: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True, slots=True)
class IntelPlan:
    """Everything the Intel domain asks the Body to do this frame."""

    proposals: tuple[Proposal, ...]
    detection: DetectionPlan
    sensor_towers: SensorTowerPlan
    # Consolidated infrastructure request; only the Intel executor builds it.
    engineering_bay: bool
    # What information matters most under Strategy's posture: threat, offense
    # or economy.
    focus: str = "economy"
    # The early scout this frame; None without one.
    scout: EarlyScoutReport | None = None
