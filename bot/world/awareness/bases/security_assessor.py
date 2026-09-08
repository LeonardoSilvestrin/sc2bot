from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId

from bot.world.attention import BaseSnapshot, WorldFacts

from .security import (
    BaseAssessment,
    BaseAwareness,
    BaseSecurityLevel,
)

_STATIC_DEFENSE_TYPES: frozenset[UnitTypeId] = frozenset(
    {
        UnitTypeId.BUNKER,
        UnitTypeId.MISSILETURRET,
        UnitTypeId.PLANETARYFORTRESS,
    }
)


@dataclass(slots=True)
class BaseSecurityAssessor:
    """Scores threat vs protection around each held base, every frame.

    Stateless on purpose for this first cut: everything is recomputed from
    currently visible units, no memory of past frames. Hysteresis similar to
    ``AwarenessService``'s ``MacroPosture`` (avoid flapping between security
    levels) can be layered on later without changing ``BaseAssessment``.
    """

    proximity_radius: float = 25.0
    static_defense_weight: float = 2.0

    def update(self, world: WorldFacts) -> BaseAwareness:
        return BaseAwareness(
            assessments=tuple(self._assess(base, world) for base in world.bases)
        )

    def _assess(self, base: BaseSnapshot, world: WorldFacts) -> BaseAssessment:
        nearby_enemies = [
            enemy
            for enemy in world.enemy_units
            if enemy.visible_now
            and not enemy.is_worker
            and (enemy.can_attack_ground or enemy.can_attack_air)
            and enemy.position.distance_to(base.position) <= self.proximity_radius
        ]
        nearby_own_combat = sum(
            1
            for unit in world.own_units
            if not unit.is_worker
            and (unit.can_attack_ground or unit.can_attack_air)
            and unit.position.distance_to(base.position) <= self.proximity_radius
        )
        nearby_static_defense = sum(
            1
            for structure in world.own_structures
            if structure.unit_type in _STATIC_DEFENSE_TYPES
            and structure.position.distance_to(base.position) <= self.proximity_radius
        )

        threat_score = float(len(nearby_enemies))
        protection_score = float(nearby_own_combat) + (
            nearby_static_defense * self.static_defense_weight
        )
        nearest_threat = min(
            nearby_enemies,
            key=lambda enemy: enemy.position.distance_to(base.position),
            default=None,
        )

        return BaseAssessment(
            base_id=base.base_id,
            position=base.position,
            is_main=base.is_main,
            threat_score=threat_score,
            protection_score=protection_score,
            security=self._security_for(threat_score, protection_score),
            nearest_threat_position=(
                nearest_threat.position if nearest_threat is not None else None
            ),
        )

    @staticmethod
    def _security_for(
        threat_score: float, protection_score: float
    ) -> BaseSecurityLevel:
        if threat_score <= 0.0:
            return BaseSecurityLevel.SAFE
        if protection_score <= 0.0:
            return BaseSecurityLevel.CRITICAL
        return BaseSecurityLevel.THREATENED
