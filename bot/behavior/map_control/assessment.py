"""ASSESS: how much of an army could hold the map right now?

Whether holding the map is strategically wanted is not assessed here: that
is Strategy's intent, which the planner reads and the Mission Policy weighs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.domain import is_combat_unit
from bot.world.attention import AttentionSnapshot, UnitSnapshot
from bot.world.awareness import AwarenessSnapshot

from .model import MapControlAssessment, MapControlConfig


@dataclass(slots=True)
class MapControlAssessor:
    config: MapControlConfig = field(default_factory=MapControlConfig)

    def assess(
        self, attention: AttentionSnapshot, awareness: AwarenessSnapshot
    ) -> MapControlAssessment:
        world = attention.world
        army = tuple(unit for unit in world.own_units if self._counts(unit))
        return MapControlAssessment(
            now=world.time,
            combat_units=len(army),
            combat_supply=sum(unit.supply_cost for unit in army),
            started=world.time >= self.config.start_after,
        )

    def _counts(self, unit: UnitSnapshot) -> bool:
        return (
            is_combat_unit(unit.unit_type)
            and unit.is_ready
            and unit.health_percentage >= self.config.minimum_unit_health
        )
