from __future__ import annotations

from dataclasses import dataclass, field

from sc2.ids.unit_typeid import UnitTypeId


@dataclass(frozen=True, slots=True)
class CountFacts:
    """Current and pending counts for an entity category."""

    existing: int = 0
    ready: int = 0
    pending: int = 0

    @property
    def total(self) -> int:
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
