from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2


@dataclass(frozen=True, slots=True)
class UnitSnapshot:
    tag: int
    unit_type: UnitTypeId
    position: Point2
    health_percentage: float
    is_flying: bool
    is_worker: bool
    can_attack_air: bool
    can_attack_ground: bool
    visible_now: bool = True
    is_ready: bool = True
    is_carrying_resource: bool = False
    is_structure: bool = False
    is_constructing: bool = False
    available_for_mission: bool = True


@dataclass(frozen=True, slots=True)
class MapObservation:
    """A selected map point and whether the game currently exposes it."""

    key: str
    position: Point2
    visible_now: bool


@dataclass(frozen=True, slots=True)
class MapFacts:
    center: Point2
    own_start: Point2
    enemy_starts: tuple[Point2, ...]
    observations: tuple[MapObservation, ...] = ()

    def observation(self, key: str) -> MapObservation | None:
        return next((item for item in self.observations if item.key == key), None)


@dataclass(frozen=True, slots=True)
class WorldFacts:
    iteration: int
    time: float
    minerals: int
    vespene: int
    supply_used: float
    supply_cap: float
    own_units: tuple[UnitSnapshot, ...]
    enemy_units: tuple[UnitSnapshot, ...]
    map: MapFacts
    own_structures: tuple[UnitSnapshot, ...] = ()
    enemy_structures: tuple[UnitSnapshot, ...] = ()


@dataclass(frozen=True, slots=True)
class AttentionSnapshot:
    """Selected, immutable observations from the current game frame."""

    world: WorldFacts
