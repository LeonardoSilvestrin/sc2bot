from __future__ import annotations

from dataclasses import dataclass, field

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId


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
    """Availability of production structures of one type.

    ``idle``/``busy`` are this frame; ``utilization_20s`` is the recent
    average of ``busy / ready``, so the half-second gap between two Marines
    reads differently from a structure that has done nothing for twenty
    seconds. Capacity decisions need the latter.
    """

    unit_type: UnitTypeId
    ready: int = 0
    idle: int = 0
    busy: int = 0
    pending: int = 0
    utilization_20s: float = 0.0

    @property
    def total(self) -> int:
        return self.ready + self.pending


@dataclass(frozen=True, slots=True)
class EconomyFacts:
    """Immutable macroeconomic observations for the current game frame."""

    opening_name: str = ""
    opening_completed: bool = False
    # What the opening's next steps will cost. Reported as plain amounts
    # rather than an economy type: this layer describes the world, the
    # economy layer decides what protecting them means.
    protected_minerals: int = 0
    protected_vespene: int = 0
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
    # Unit types whose tech (structure and add-on) is finished, as Ares
    # judges it. ``None`` means the question was not asked this frame, which
    # must read as "no reason to rule anything out" -- a missing observation
    # cannot be allowed to silently stop all unit production.
    tech_ready: frozenset[UnitTypeId] | None = None
    # Upgrades already researched, and how far along the ones still in
    # progress are (0.0-1.0). Behaviors that only exist because of an upgrade
    # -- cloaked Banshee harass being the obvious one -- need the progress,
    # not just the finished flag, to know whether it is worth preparing yet.
    upgrades: frozenset[UpgradeId] = frozenset()
    upgrades_in_progress: tuple[tuple[UpgradeId, float], ...] = ()

    def tech_ready_for(self, unit_type: UnitTypeId) -> bool:
        return self.tech_ready is None or unit_type in self.tech_ready

    def upgrade_ready(self, upgrade: UpgradeId) -> bool:
        return upgrade in self.upgrades

    def upgrade_progress(self, upgrade: UpgradeId) -> float:
        """How complete this upgrade is, 1.0 once researched."""

        if upgrade in self.upgrades:
            return 1.0
        for candidate, progress in self.upgrades_in_progress:
            if candidate == upgrade:
                return progress
        return 0.0

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
