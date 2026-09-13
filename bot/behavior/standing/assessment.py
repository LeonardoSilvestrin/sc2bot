"""ASSESS: what is our army holding, and what is pressing on it?"""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.world.attention import AttentionSnapshot
from bot.world.awareness import AwarenessSnapshot, RelativePosition

from .model import STANDING_ROSTER, CombatPosture, StandingAssessment, StandingConfig


def derive_combat_posture(*, awareness: AwarenessSnapshot) -> CombatPosture:
    """A small, deterministic reading of already-computed Awareness signals.

    No new observation is introduced here -- ``bases.threatened`` and the
    stabilized army belief already answer "is something wrong right now" and
    "are we ahead". The army belief already weighs how sure it is, so its
    stable state is read as is: gating it again on its confidence is what
    used to make this flap. Strategic caution is not read here at all; it is
    Strategy's intent.
    """

    army = awareness.army.relative
    if awareness.bases.threatened or army.stable_state is RelativePosition.BEHIND:
        return CombatPosture.TURTLE

    if (
        army.stable_state is RelativePosition.AHEAD
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
        combat_units = sum(
            unit.unit_type in STANDING_ROSTER
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
            combat_units=combat_units,
            own_start=world.map.own_start,
        )
