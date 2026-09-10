"""ASSESS: can we spare a squad to hold the map right now?"""

from __future__ import annotations

from dataclasses import dataclass, field

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
        return MapControlAssessment(
            now=world.time,
            eligible_units=sum(
                self._eligible(unit) for unit in world.own_units
            ),
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

    def _eligible(self, unit: UnitSnapshot) -> bool:
        return (
            unit.unit_type in self.config.unit_types
            and unit.is_ready
            and unit.health_percentage >= self.config.minimum_unit_health
        )
