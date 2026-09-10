"""ASSESS: what is our army holding, and what is pressing on it?"""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.world.attention import AttentionSnapshot
from bot.world.awareness import AwarenessSnapshot, MacroPosture

from .model import CombatPosture, StandingAssessment, StandingConfig


def derive_combat_posture(*, awareness: AwarenessSnapshot) -> CombatPosture:
    """A small, deterministic policy over already-computed Awareness signals.

    No new observation is introduced here -- ``bases.threatened``,
    ``relative_strength`` and ``macro_posture`` already exist precisely to
    answer "is something wrong right now" and "are we ahead". This only has
    to decide which of three postures that maps to.
    """

    strength = awareness.relative_strength
    if (
        awareness.bases.threatened
        or awareness.macro_posture in {MacroPosture.DEFENSE, MacroPosture.RECOVERY}
        or (strength.confidence > 0.0 and strength.score <= -0.25)
    ):
        return CombatPosture.TURTLE

    if (
        strength.confidence >= 0.5
        and strength.score >= 0.35
        and awareness.threat.near_own_base_enemy_combat_units == 0
    ):
        return CombatPosture.PRESSURE

    return CombatPosture.BALANCED


@dataclass(slots=True)
class StandingAssessor:
    config: StandingConfig = field(default_factory=StandingConfig)

    def assess(
        self, attention: AttentionSnapshot, awareness: AwarenessSnapshot
    ) -> StandingAssessment:
        world = attention.world
        bases = tuple(
            sorted(
                awareness.bases,
                key=lambda base: (
                    base.position.distance_to(world.map.own_start),
                    base.base_id,
                ),
            )
        )
        eligible = sum(
            unit.unit_type in self.config.unit_types
            and unit.is_ready
            and unit.health_percentage >= self.config.minimum_unit_health
            for unit in world.own_units
        )
        return StandingAssessment(
            now=world.time,
            posture=derive_combat_posture(awareness=awareness),
            bases=bases,
            threatened_base_ids=tuple(
                base.base_id for base in awareness.bases.threatened
            ),
            pressure=awareness.threat.near_own_base_enemy_combat_units,
            eligible_units=eligible,
            own_start=world.map.own_start,
        )
