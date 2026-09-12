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
    is_structure: bool
    is_worker: bool = False
    supply_cost: float = 0.0

    @property
    def is_combat_unit(self) -> bool:
        """A mobile enemy with a weapon: neither a worker nor a structure."""

        return (
            not self.is_worker
            and not self.is_structure
            and (self.can_attack_air or self.can_attack_ground)
        )

    @property
    def is_static_defense(self) -> bool:
        """A structure with a weapon of its own (cannon, spore, turret, ...)."""

        return self.is_structure and (self.can_attack_air or self.can_attack_ground)


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
