from __future__ import annotations

from dataclasses import dataclass, field

from .base_facts import TOWNHALL_TYPES, BaseSnapshot
from .economy_facts import EconomyFacts
from .map_facts import MapFacts
from .unit_facts import UnitSnapshot


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
    # Tags the game reported dead since the previous observation, any owner.
    dead_unit_tags: frozenset[int] = frozenset()

    @property
    def bases(self) -> tuple[BaseSnapshot, ...]:
        townhalls = tuple(
            structure
            for structure in self.own_structures
            if structure.unit_type in TOWNHALL_TYPES
        )
        if not townhalls:
            return (
                BaseSnapshot(
                    base_id="own_base",
                    position=self.map.own_start,
                    is_main=True,
                    townhall=None,
                ),
            )
        return tuple(
            BaseSnapshot(
                base_id=f"base:{townhall.tag}",
                position=townhall.position,
                is_main=townhall.position.distance_to(self.map.own_start) < 3.0,
                townhall=townhall,
            )
            for townhall in townhalls
        )
