"""ASSESS: can we spare a squad to hold the map right now?"""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.domain import is_combat_unit
from bot.world.attention import AttentionSnapshot, UnitSnapshot
from bot.world.awareness import AwarenessSnapshot, MacroPosture

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
            # Reported, not gated on: the planner keeps declaring the squad
            # under pressure and lets the executor pull it home, so the
            # standing mission survives instead of being torn down and
            # rebuilt every time a base is threatened.
            strategically_safe=(
                not awareness.bases.threatened
                and awareness.macro_posture
                not in {MacroPosture.DEFENSE, MacroPosture.RECOVERY}
            ),
        )

    def _counts(self, unit: UnitSnapshot) -> bool:
        return (
            is_combat_unit(unit.unit_type)
            and unit.is_ready
            and unit.health_percentage >= self.config.minimum_unit_health
        )
