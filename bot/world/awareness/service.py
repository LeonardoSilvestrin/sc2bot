from __future__ import annotations

from bot.ports.logging import BotLogger
from bot.world.attention import TOWNHALL_TYPES, AttentionSnapshot

from .bases import BaseSecurityAssessor
from .belief import (
    ArmyBeliefConfig,
    BeliefState,
    EconomyBeliefConfig,
    LossTracker,
    RelativeAssessment,
    RelativePosition,
    assess_army,
    assess_economy,
)
from .enemy import (
    EnemyAwareness,
    EnemyBaseAssessor,
    EnemyBaseHeuristics,
    EnemyBaseMemory,
    EnemyForceHeuristics,
    EnemyForceTracker,
    EnemyKnowledge,
    EnemyLocationKnowledge,
    EnemyRoster,
    enemy_territory_coverage,
    scouting_coverage,
)
from .posture import PostureState, derive_macro_posture
from .snapshot import (
    AwarenessSnapshot,
    RelativeStrength,
    ThreatAssessment,
)
from .spatial import SpatialFieldModel, SpatialModelConfig


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
        enemy_base_stale_after: float = 120.0,
        enemy_base_heuristics: EnemyBaseHeuristics | None = None,
        enemy_force_heuristics: EnemyForceHeuristics | None = None,
        economy_belief_config: EconomyBeliefConfig | None = None,
        army_belief_config: ArmyBeliefConfig | None = None,
        spatial_model_config: SpatialModelConfig | None = None,
        logger: BotLogger | None = None,
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
        self.economy_belief_config = economy_belief_config or EconomyBeliefConfig()
        self.army_belief_config = army_belief_config or ArmyBeliefConfig()
        self.enemy_knowledge = EnemyKnowledge()
        self._enemy_roster = EnemyRoster()
        self._loss_tracker = LossTracker()
        self._base_assessor = BaseSecurityAssessor()
        self._enemy_base_memory = EnemyBaseMemory(stale_after=enemy_base_stale_after)
        self._enemy_base_assessor = EnemyBaseAssessor(enemy_base_heuristics)
        self._enemy_force_tracker = EnemyForceTracker(enemy_force_heuristics)
        self._spatial_model = SpatialFieldModel(
            spatial_model_config or SpatialModelConfig(), logger=logger
        )
        self._location_last_observed: dict[str, float] = {}
        self._posture_state = PostureState()
        self._economy_state = BeliefState()
        self._army_state = BeliefState()

    def update(self, attention: AttentionSnapshot) -> AwarenessSnapshot:
        world = attention.world
        sightings = self.enemy_knowledge.update(world)
        roster = self._enemy_roster.update(sightings, dead_tags=world.dead_unit_tags)
        losses = self._loss_tracker.update(world, enemy_died=roster.died)
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

        previous_economy_stable = self._economy_state.hysteresis.stable
        previous_army_stable = self._army_state.hysteresis.stable
        base_observations = self._enemy_base_memory.update(world)
        coverage = scouting_coverage(base_observations)
        scouted = any(
            observation.last_checked_at is not None
            for observation in base_observations
        )
        visibility = enemy_territory_coverage(base_observations)
        enemy_bases = self._enemy_base_assessor.update(
            observations=base_observations, sightings=sightings, now=world.time
        )
        enemy_forces = self._enemy_force_tracker.update(sightings, now=world.time)
        bases = self._base_assessor.update(world)
        economy_belief, self._economy_state = assess_economy(
            world=world,
            sightings=sightings,
            roster=roster.alive,
            base_observations=base_observations,
            losses=losses,
            coverage=coverage,
            visibility=visibility,
            scouted=scouted,
            state=self._economy_state,
            config=self.economy_belief_config,
        )
        army_belief, self._army_state = assess_army(
            world=world,
            sightings=sightings,
            roster=roster.alive,
            losses=losses,
            enemy_workers=float(economy_belief.enemy.workers.estimated),
            visibility=visibility,
            scouted=scouted,
            state=self._army_state,
            config=self.army_belief_config,
        )

        # Relative force compares our supply with the running estimate of the
        # enemy's, not a head count of whatever is on screen this frame. Unit
        # counts remain on the snapshot as current tactical telemetry.
        own_strength = army_belief.own_supply
        enemy_supply = army_belief.enemy.supply
        if own_strength > 0.0 or enemy_supply.known > 0.0:
            score = (own_strength - enemy_supply.estimated) / (
                own_strength + enemy_supply.estimated
            )
        else:
            # Some synthetic/test observers do not provide supply costs.
            # Preserve a useful fallback without weakening live-game logic.
            count_total = own_combat + enemy_combat
            score = (
                0.0
                if count_total == 0
                else (own_combat - enemy_combat) / count_total
            )

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
            strength_is_stably_ahead=(
                army_belief.relative.stable_state is RelativePosition.AHEAD
            ),
            nearby_enemy_combat=len(nearby_combat),
            state=self._posture_state,
            defense_release_after=self.defense_release_after,
            greed_safe_after=self.greed_safe_after,
            posture_min_hold=self.posture_min_hold,
        )

        belief_changes = tuple(
            message
            for message in (
                _belief_change_message(
                    "ECONOMY", previous_economy_stable, economy_belief.relative
                ),
                _belief_change_message(
                    "ARMY", previous_army_stable, army_belief.relative
                ),
            )
            if message is not None
        )

        return AwarenessSnapshot(
            enemy=EnemyAwareness(
                sightings=sightings,
                locations=tuple(locations),
                bases=enemy_bases,
                forces=enemy_forces,
            ),
            relative_strength=RelativeStrength(
                score=score,
                confidence=army_belief.relative.confidence,
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
            bases=bases,
            economy=economy_belief,
            army=army_belief,
            spatial=self._spatial_model.update(
                world, bases=bases, enemy_forces=enemy_forces
            ),
            belief_changes=belief_changes,
        )


def _belief_change_message(
    label: str, previous: RelativePosition, assessment: RelativeAssessment
) -> str | None:
    """Render one ``[Awareness] LABEL: OLD -> NEW`` line, or ``None`` if the
    stable state did not actually change this tick (never announced)."""

    if assessment.stable_state is previous:
        return None
    text = (
        f"[Awareness] {label}: {previous.name} -> {assessment.stable_state.name} "
        f"(p_ahead={assessment.advantage:.2f}, "
        f"confidence={assessment.confidence:.2f})"
    )
    if assessment.reason:
        text = f"{text} | {assessment.reason}"
    return text
