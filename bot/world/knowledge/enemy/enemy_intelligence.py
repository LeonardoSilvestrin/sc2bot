from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.world.observation import TOWNHALL_TYPES


@dataclass(frozen=True, slots=True)
class EnemySighting:
    tag: int
    unit_type: UnitTypeId
    last_position: Point2
    first_seen_at: float
    last_seen_at: float
    visible_now: bool
    can_attack_air: bool
    can_attack_ground: bool
    is_structure: bool


@dataclass(frozen=True, slots=True)
class EnemyLocationKnowledge:
    """Typed freshness information about one strategically relevant location."""

    key: str
    position: Point2
    last_observed_at: float | None
    age: float | None
    confidence: float
    stale_after: float
    is_stale: bool


@dataclass(frozen=True, slots=True)
class EnemyAwareness:
    sightings: tuple[EnemySighting, ...]
    locations: tuple[EnemyLocationKnowledge, ...]

    def sighting(self, tag: int) -> EnemySighting | None:
        return next((item for item in self.sightings if item.tag == tag), None)

    def location(self, key: str) -> EnemyLocationKnowledge | None:
        return next((item for item in self.locations if item.key == key), None)

    @property
    def known_base_count(self) -> int:
        """Count enemy townhalls retained in the current world knowledge."""

        return sum(
            sighting.is_structure and sighting.unit_type in TOWNHALL_TYPES
            for sighting in self.sightings
        )

    @property
    def known_structure_count(self) -> int:
        return sum(sighting.is_structure for sighting in self.sightings)
