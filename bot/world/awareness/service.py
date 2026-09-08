from __future__ import annotations

from bot.world.attention import TOWNHALL_TYPES, AttentionSnapshot

from .bases import BaseSecurityAssessor
from .enemy import (
    EnemyAwareness,
    EnemyKnowledge,
    EnemyLocationKnowledge,
)
from .posture import PostureState, derive_macro_posture
from .snapshot import (
    AwarenessSnapshot,
    RelativeStrength,
    ThreatAssessment,
)


class AwarenessService:
    """Owns world memory and derives beliefs without issuing commands."""

    def __init__(
        self,
        *,
        location_stale_after: float = 90.0,
        own_base_threat_radius: float = 28.0,
        defense_release_after: float = 10.0,
        posture_min_hold: float = 8.0,
        greed_safe_after: float = 20.0,
    ) -> None:
        if location_stale_after <= 0.0:
            raise ValueError("location_stale_after must be positive")
        if own_base_threat_radius <= 0.0:
            raise ValueError("own_base_threat_radius must be positive")
        if min(defense_release_after, posture_min_hold, greed_safe_after) < 0.0:
            raise ValueError("posture timings must not be negative")
        self.location_stale_after = float(location_stale_after)
        self.own_base_threat_radius = float(own_base_threat_radius)
        self.defense_release_after = float(defense_release_after)
        self.posture_min_hold = float(posture_min_hold)
        self.greed_safe_after = float(greed_safe_after)
        self.enemy_knowledge = EnemyKnowledge()
        self._base_assessor = BaseSecurityAssessor()
        self._location_last_observed: dict[str, float] = {}
        self._posture_state = PostureState()

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
            if unit.visible_now
            and not unit.is_worker
            and (unit.can_attack_air or unit.can_attack_ground)
        )
        known_total = own_combat + enemy_combat
        score = 0.0 if known_total == 0 else (own_combat - enemy_combat) / known_total
        strength_confidence = min(1.0, len(sightings) / 12.0) if sightings else 0.0

        anchors = tuple(
            structure.position
            for structure in world.own_structures
            if structure.is_ready and not structure.is_flying
        ) or (world.map.own_start,)
        nearby_enemies = tuple(
            unit
            for unit in world.enemy_units
            if unit.visible_now
            and any(
                unit.position.distance_to(anchor) <= self.own_base_threat_radius
                for anchor in anchors
            )
        )
        nearby_combat = tuple(
            unit
            for unit in nearby_enemies
            if not unit.is_worker and (unit.can_attack_air or unit.can_attack_ground)
        )
        visible_enemy_combat = sum(
            unit.visible_now
            and not unit.is_worker
            and (unit.can_attack_air or unit.can_attack_ground)
            for unit in world.enemy_units
        )
        workers = sum(unit.is_worker for unit in world.own_units)
        townhalls = sum(
            structure.is_ready
            and not structure.is_flying
            and structure.unit_type in TOWNHALL_TYPES
            for structure in world.own_structures
        )
        self._posture_state = derive_macro_posture(
            now=world.time,
            workers=workers,
            townhalls=townhalls,
            own_combat=own_combat,
            strength_score=score,
            strength_confidence=strength_confidence,
            nearby_enemy_combat=len(nearby_combat),
            state=self._posture_state,
            defense_release_after=self.defense_release_after,
            greed_safe_after=self.greed_safe_after,
            posture_min_hold=self.posture_min_hold,
        )

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
                visible_enemy_combat_units=visible_enemy_combat,
                near_own_base_enemy_units=len(nearby_enemies),
                near_own_base_enemy_combat_units=len(nearby_combat),
            ),
            updated_at=world.time,
            macro_posture=self._posture_state.posture,
            bases=self._base_assessor.update(world),
        )
