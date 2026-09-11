"""ASSESS: what is our army holding, and what is pressing on it?"""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.world.attention import AttentionSnapshot
from bot.world.awareness import AwarenessSnapshot, MacroPosture, RelativePosition

from .model import CombatPosture, StandingAssessment, StandingConfig


def derive_combat_posture(*, awareness: AwarenessSnapshot) -> CombatPosture:
    """A small, deterministic policy over already-computed Awareness signals.

    No new observation is introduced here -- ``bases.threatened``,
    The stabilized army belief and ``macro_posture`` already exist precisely
    to answer "is something wrong right now" and "are we ahead". This only
    has to decide which of three postures that maps to.
    """

    army = awareness.army.relative
    if (
        awareness.bases.threatened
        or awareness.macro_posture in {MacroPosture.DEFENSE, MacroPosture.RECOVERY}
        or (
            army.stable_state is RelativePosition.BEHIND
            and army.confidence >= 0.35
        )
    ):
        return CombatPosture.TURTLE

    if (
        army.stable_state is RelativePosition.AHEAD
        and army.confidence >= 0.60
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
