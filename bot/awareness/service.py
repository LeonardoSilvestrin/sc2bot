from __future__ import annotations

from bot.attention.models import AttentionSnapshot
from bot.awareness.enemy import EnemyAwareness, EnemyKnowledge, EnemyLocationKnowledge
from bot.awareness.models import AwarenessSnapshot, RelativeStrength, ThreatAssessment


class AwarenessService:
    """Owns world memory and derives beliefs without issuing commands."""

    def __init__(self, *, location_stale_after: float = 90.0) -> None:
        if location_stale_after <= 0.0:
            raise ValueError("location_stale_after must be positive")
        self.location_stale_after = float(location_stale_after)
        self.enemy_knowledge = EnemyKnowledge()
        self._location_last_observed: dict[str, float] = {}

    def update(self, attention: AttentionSnapshot) -> AwarenessSnapshot:
        world = attention.world
        sightings = self.enemy_knowledge.update(world)
        locations: list[EnemyLocationKnowledge] = []
        for observation in world.map.observations:
            if observation.visible_now:
                self._location_last_observed[observation.key] = world.time
            last_observed = self._location_last_observed.get(observation.key)
            age = (
                None if last_observed is None else max(0.0, world.time - last_observed)
            )
            location_confidence = (
                0.0
                if age is None
                else max(0.0, 1.0 - (age / self.location_stale_after))
            )
            locations.append(
                EnemyLocationKnowledge(
                    key=observation.key,
                    position=observation.position,
                    last_observed_at=last_observed,
                    age=age,
                    confidence=location_confidence,
                    stale_after=self.location_stale_after,
                    is_stale=age is None or age >= self.location_stale_after,
                )
            )

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
        strength_confidence = min(1.0, len(sightings) / 12.0) if sightings else 0.0

        return AwarenessSnapshot(
            enemy=EnemyAwareness(
                sightings=sightings,
                locations=tuple(locations),
            ),
            relative_strength=RelativeStrength(
                score=score,
                confidence=strength_confidence,
                own_combat_units=own_combat,
                known_enemy_combat_units=enemy_combat,
            ),
            threat=ThreatAssessment(
                visible_enemy_units=sum(u.visible_now for u in world.enemy_units),
                known_anti_air_units=sum(u.can_attack_air for u in sightings),
                visible_anti_air_units=sum(
                    u.visible_now and u.can_attack_air for u in world.enemy_units
                ),
            ),
            updated_at=world.time,
        )
