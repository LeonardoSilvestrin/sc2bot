from __future__ import annotations

from bot.attention.models import WorldFacts
from bot.awareness.models import AwarenessSnapshot, RelativeStrength, ThreatAssessment
from bot.knowledge.models import EnemyKnowledgeView


class AwarenessService:
    """Derives explicit beliefs. It does not issue commands or own facts."""

    @staticmethod
    def update(
        world: WorldFacts, knowledge: EnemyKnowledgeView | None = None
    ) -> AwarenessSnapshot:
        own_combat = sum(
            1
            for unit in world.own_units
            if not unit.is_worker and (unit.can_attack_air or unit.can_attack_ground)
        )
        enemy_combat = sum(
            1
            for unit in world.enemy_units
            if not unit.is_worker and (unit.can_attack_air or unit.can_attack_ground)
        )
        known_total = own_combat + enemy_combat
        score = 0.0 if known_total == 0 else (own_combat - enemy_combat) / known_total
        known_enemy = len(knowledge.sightings) if knowledge is not None else len(world.enemy_units)
        confidence = min(1.0, known_enemy / 12.0) if known_enemy else 0.0

        return AwarenessSnapshot(
            relative_strength=RelativeStrength(
                score=score,
                confidence=confidence,
                own_combat_units=own_combat,
                known_enemy_combat_units=enemy_combat,
            ),
            threat=ThreatAssessment(
                visible_enemy_units=sum(u.visible_now for u in world.enemy_units),
                known_anti_air_units=(
                    sum(u.can_attack_air for u in knowledge.sightings)
                    if knowledge is not None
                    else sum(u.can_attack_air for u in world.enemy_units)
                ),
                visible_anti_air_units=sum(
                    u.visible_now and u.can_attack_air for u in world.enemy_units
                ),
            ),
            updated_at=world.time,
        )
