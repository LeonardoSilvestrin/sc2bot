from __future__ import annotations

from dataclasses import dataclass, field

from bot.world.attention import TOWNHALL_TYPES

from .bases.assessment import EnemyBaseAwareness
from .forces.cluster import EnemyForceAwareness, EnemyForceCluster
from .knowledge import EnemyLocationKnowledge, EnemySighting


@dataclass(frozen=True, slots=True)
class EnemyAwareness:
    """Everything Awareness currently holds about the enemy.

    ``sightings`` and ``locations`` are remembered observations. ``bases``
    and ``forces`` are beliefs derived from them, each carrying its own
    confidence, so an old reading is never mistaken for a current one.
    """

    sightings: tuple[EnemySighting, ...]
    locations: tuple[EnemyLocationKnowledge, ...]
    bases: EnemyBaseAwareness = field(default_factory=EnemyBaseAwareness)
    forces: EnemyForceAwareness = field(default_factory=EnemyForceAwareness)

    def sighting(self, tag: int) -> EnemySighting | None:
        return next((item for item in self.sightings if item.tag == tag), None)

    def location(self, key: str) -> EnemyLocationKnowledge | None:
        return next((item for item in self.locations if item.key == key), None)

    @property
    def main_force(self) -> EnemyForceCluster | None:
        """The cluster that best stands for the enemy's main army right now."""

        return self.forces.main

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
