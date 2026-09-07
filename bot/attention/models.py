from __future__ import annotations

from dataclasses import dataclass, field

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
class CountFacts:
    """Counts for an entity whose pending instances may already be visible.

    ``existing`` is the raw number currently exposed by the game. ``pending``
    is everything not ready yet, including visible construction and queued
    production, so callers should use ``total`` rather than adding
    ``existing`` and ``pending``.
    """

    existing: int = 0
    ready: int = 0
    pending: int = 0

    @property
    def total(self) -> int:
        """Return ready entities plus everything still in progress."""

        return self.ready + self.pending


@dataclass(frozen=True, slots=True)
class UnitTypeCount:
    """Immutable current and pending counts for one unit or structure type."""

    unit_type: UnitTypeId
    existing: int = 0
    ready: int = 0
    pending: int = 0

    @property
    def total(self) -> int:
        return self.ready + self.pending


@dataclass(frozen=True, slots=True)
class ProducerFacts:
    """Availability of production structures of one type."""

    unit_type: UnitTypeId
    ready: int = 0
    idle: int = 0
    busy: int = 0
    pending: int = 0

    @property
    def total(self) -> int:
        return self.ready + self.pending


@dataclass(frozen=True, slots=True)
class EconomyFacts:
    """Immutable macroeconomic observations for the current game frame."""

    opening_name: str = ""
    opening_completed: bool = False
    mineral_collection_rate: float = 0.0
    vespene_collection_rate: float = 0.0
    workers: CountFacts = field(default_factory=CountFacts)
    ideal_harvesters: int = 0
    assigned_harvesters: int = 0
    townhalls: CountFacts = field(default_factory=CountFacts)
    supply_pending: int = 0
    unit_counts: tuple[UnitTypeCount, ...] = ()
    structure_counts: tuple[UnitTypeCount, ...] = ()
    producers: tuple[ProducerFacts, ...] = ()

    def unit_count(self, unit_type: UnitTypeId) -> UnitTypeCount:
        return next(
            (item for item in self.unit_counts if item.unit_type == unit_type),
            UnitTypeCount(unit_type),
        )

    def structure_count(self, unit_type: UnitTypeId) -> UnitTypeCount:
        return next(
            (item for item in self.structure_counts if item.unit_type == unit_type),
            UnitTypeCount(unit_type),
        )

    def producer(self, unit_type: UnitTypeId) -> ProducerFacts:
        return next(
            (item for item in self.producers if item.unit_type == unit_type),
            ProducerFacts(unit_type),
        )


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
    economy: EconomyFacts = field(default_factory=EconomyFacts)


@dataclass(frozen=True, slots=True)
class AttentionSnapshot:
    """Selected, immutable observations from the current game frame."""

    world: WorldFacts
