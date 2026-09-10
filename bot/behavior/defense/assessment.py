"""ASSESS: which of our bases are under attack, and by what?

`AwarenessService` already scores threat against protection per held base
(`BaseSecurityAssessor`). This reads that through the defense lens and adds
the one thing the global assessment does not carry: what the attackers
actually are.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sc2.position import Point2

from bot.world.attention import AttentionSnapshot, UnitSnapshot
from bot.world.awareness import AwarenessSnapshot
from bot.world.awareness.bases import BaseAssessment

from .model import DefenseAssessment, DefenseConfig, ThreatenedBase


@dataclass(slots=True)
class DefenseAssessor:
    config: DefenseConfig = field(default_factory=DefenseConfig)

    def assess(
        self, attention: AttentionSnapshot, awareness: AwarenessSnapshot
    ) -> DefenseAssessment:
        world = attention.world
        return DefenseAssessment(
            now=world.time,
            threatened=tuple(
                self._threatened(base, world.enemy_units)
                for base in awareness.bases.threatened
            ),
            held_bases=len(awareness.bases),
            pressure=awareness.threat.near_own_base_enemy_combat_units,
        )

    def _threatened(
        self, base: BaseAssessment, enemy_units: tuple[UnitSnapshot, ...]
    ) -> ThreatenedBase:
        nearby = tuple(
            unit
            for unit in enemy_units
            if unit.is_visible_combat_threat()
            and self._near(unit, base.position)
        )
        return ThreatenedBase(
            base=base,
            air_threats=sum(unit.is_flying for unit in nearby),
            ground_threats=sum(not unit.is_flying for unit in nearby),
        )

    def _near(self, unit: UnitSnapshot, position: Point2) -> bool:
        return unit.position.distance_to(position) <= self.config.engagement_radius
