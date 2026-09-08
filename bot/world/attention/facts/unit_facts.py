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

    def is_visible_combat_threat(
        self, *, against_ground: bool = True, against_air: bool = True
    ) -> bool:
        """Return whether this unit can currently threaten a requested domain."""

        if not self.visible_now or self.is_worker:
            return False
        return (against_ground and self.can_attack_ground) or (
            against_air and self.can_attack_air
        )
