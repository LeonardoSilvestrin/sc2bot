from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2


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


@dataclass(frozen=True, slots=True)
class EnemyKnowledgeView:
    """Immutable public interface to persistent enemy facts."""

    sightings: tuple[EnemySighting, ...]
    updated_at: float

    def by_tag(self, tag: int) -> EnemySighting | None:
        return next((item for item in self.sightings if item.tag == tag), None)
