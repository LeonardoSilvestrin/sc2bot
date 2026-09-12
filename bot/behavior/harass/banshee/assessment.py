"""ASSESS: what is the Banshee-harass situation right now?

Attention supplies observed facts, Awareness supplies memory and inference,
and this module reads both through one lens: *is there a raid to be flown,
and which enemy base would a cloaked Banshee most like to fly it at?* It
answers with numbers only. It never claims a unit, never creates a mission,
never decides which target the raid holds -- the planner does -- and keeps
no second copy of enemy knowledge: everything about the enemy comes from
`AwarenessSnapshot`.

Awareness describes each enemy base and force cluster once, for everyone.
What they mean to a Banshee is decided here, through
`BansheeTargetHeuristics`; the Reaper raid reads the very same bases through
its own lens and can rank them the other way round.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sc2.position import Point2

from bot.behavior.strategy_intent import BuildStrategicIntent, StrategicIntent
from bot.world.attention import AttentionSnapshot
from bot.world.awareness import (
    AwarenessSnapshot,
    EnemyBaseAssessment,
    EnemyForceAwareness,
    EnemyLocationKnowledge,
)

from .model import (
    BansheeHarassAssessment,
    BansheeHarassConfig,
    BansheeTargetAssessment,
)


@dataclass(slots=True)
class BansheeHarassAssessor:
    """Builds a `BansheeHarassAssessment` from the world model."""

    config: BansheeHarassConfig = field(default_factory=BansheeHarassConfig)
    strategic_intent: StrategicIntent = field(default_factory=BuildStrategicIntent)

    def assess(
        self, attention: AttentionSnapshot, awareness: AwarenessSnapshot
    ) -> BansheeHarassAssessment:
        world = attention.world
        banshees = tuple(
            unit for unit in world.own_units if unit.unit_type in self.config.unit_types
        )
        ready = sum(unit.is_ready for unit in banshees)
        pending = sum(
            world.economy.unit_count(unit_type).pending
            for unit_type in self.config.unit_types
        )
        cloak_progress = world.economy.upgrade_progress(self.config.cloak_upgrade)
        cloak_ready = world.economy.upgrade_ready(self.config.cloak_upgrade)
        targets = self._targets(awareness, now=world.time)
        return BansheeHarassAssessment(
            now=world.time,
            banshees_alive=len(banshees),
            banshees_ready=ready,
            banshees_pending=pending,
            cloak_ready=cloak_ready,
            cloak_progress=cloak_progress,
            workers=sum(unit.is_worker for unit in world.own_units),
            build_supports_harass=self.strategic_intent.allows(
                self.config.strategic_intent, world
            ),
            targets=targets,
            known_anti_air_units=awareness.threat.known_anti_air_units,
            enemy_army_position=self._enemy_army_position(awareness),
            readiness=self._readiness(
                len(banshees), pending, cloak_progress, targets
            ),
            risk=self._risk(targets),
        )

    # --- targets ------------------------------------------------------------

    def _targets(
        self, awareness: AwarenessSnapshot, *, now: float
    ) -> tuple[BansheeTargetAssessment, ...]:
        """Every candidate target, best score first.

        Candidates are the enemy bases Awareness has confirmed, whichever
        expansions they are. Only while there is none do the configured
        fallback locations, once observed, stand in for them.
        """

        forces = awareness.enemy.forces
        targets = [
            self._base_target(base, forces, now=now)
            for base in awareness.enemy.bases.confirmed
        ]
        if not targets:
            targets = [
                self._fallback_target(location, forces)
                for key in self.config.fallback_target_keys
                if (location := awareness.enemy.location(key)) is not None
                and location.last_observed_at is not None
            ]
        return tuple(sorted(targets, key=lambda target: -target.score))

    def _base_target(
        self, base: EnemyBaseAssessment, forces: EnemyForceAwareness, *, now: float
    ) -> BansheeTargetAssessment:
        heuristics = self.config.targeting
        worker_line = _clamp01(
            base.worker_count_estimate / heuristics.full_worker_line
        )
        return self._scored(
            key=base.key,
            position=base.position,
            economic_opportunity=(
                heuristics.value_share * base.economic_value
                + (1.0 - heuristics.value_share) * worker_line
            ),
            air_defense_risk=_believed(
                base.air_defense,
                base.air_defense_confidence,
                assumed=heuristics.assumed_air_defense,
            ),
            ground_defense=base.ground_defense,
            army_risk=self._army_risk(forces, base.position),
            information_confidence=base.confidence,
            workers=base.worker_count_estimate,
            last_observed_at=base.last_checked_at,
            age=(
                None
                if base.last_checked_at is None
                else max(0.0, now - base.last_checked_at)
            ),
            stale_after=None,
        )

    def _fallback_target(
        self, location: EnemyLocationKnowledge, forces: EnemyForceAwareness
    ) -> BansheeTargetAssessment:
        """An observed location with no base reading: its value is assumed and
        its anti-air entirely unknown."""

        heuristics = self.config.targeting
        return self._scored(
            key=location.key,
            position=location.position,
            economic_opportunity=heuristics.fallback_opportunity,
            air_defense_risk=_believed(
                0.0, 0.0, assumed=heuristics.assumed_air_defense
            ),
            ground_defense=0.0,
            army_risk=self._army_risk(forces, location.position),
            information_confidence=location.confidence,
            workers=0,
            last_observed_at=location.last_observed_at,
            age=location.age,
            stale_after=location.stale_after,
            is_fallback=True,
        )

    def _scored(
        self,
        *,
        key: str,
        position: Point2,
        economic_opportunity: float,
        air_defense_risk: float,
        ground_defense: float,
        army_risk: float,
        information_confidence: float,
        workers: int,
        last_observed_at: float | None,
        age: float | None,
        stale_after: float | None,
        is_fallback: bool = False,
    ) -> BansheeTargetAssessment:
        """Add the components up, as `BansheeTargetHeuristics` describes."""

        heuristics = self.config.targeting
        score = (
            heuristics.opportunity_weight * economic_opportunity
            - heuristics.air_defense_weight * air_defense_risk
            - heuristics.ground_defense_weight * ground_defense
            - heuristics.army_weight * army_risk
            - heuristics.uncertainty_weight * (1.0 - information_confidence)
        )
        return BansheeTargetAssessment(
            key=key,
            position=position,
            score=score,
            economic_opportunity=economic_opportunity,
            air_defense_risk=air_defense_risk,
            army_risk=army_risk,
            information_confidence=information_confidence,
            workers=workers,
            viable=(
                air_defense_risk <= heuristics.max_air_defense_risk
                and army_risk <= heuristics.max_army_risk
            ),
            last_observed_at=last_observed_at,
            age=age,
            stale_after=stale_after,
            is_fallback=is_fallback,
        )

    def _army_risk(self, forces: EnemyForceAwareness, position: Point2) -> float:
        """Anti-air strength that may reach ``position``, over a certain loss."""

        heuristics = self.config.targeting
        floor = heuristics.army_confidence_floor
        threat = sum(
            cluster.anti_air_strength
            * _proximity(
                cluster.distance_to(position),
                heuristics.army_contact_radius,
                heuristics.army_reach,
            )
            * (floor + (1.0 - floor) * cluster.confidence)
            for cluster in forces.near(position, heuristics.army_reach)
        )
        return _clamp01(threat / heuristics.dangerous_anti_air_strength)

    # --- descriptive readings ---------------------------------------------

    @staticmethod
    def _enemy_army_position(awareness: AwarenessSnapshot) -> Point2 | None:
        """Where Awareness believes the enemy's main army is.

        Neither a launch gate nor how targets are ranked -- that reads every
        force cluster, so a split army still counts wherever each part of it
        is. It is here because "where is their army" is the first thing a
        human asks before flying two Banshees somewhere.
        """

        main_force = awareness.enemy.main_force
        return None if main_force is None else main_force.center

    def _readiness(
        self,
        alive: int,
        pending: int,
        cloak_progress: float,
        targets: tuple[BansheeTargetAssessment, ...],
    ) -> float:
        """How close the raid is to being worth launching, 0.0-1.0.

        Descriptive only: the planner's gates are explicit booleans, not a
        threshold on this number. It exists so the log can show "one Banshee,
        cloak at 30%" as a low number and "two Banshees, cloak done" as a
        high one without re-deriving that at the reading end.
        """

        squad = self.config.preferred_squad_size
        force = min(1.0, (alive + 0.5 * pending) / squad)
        known = bool(targets)
        return round(force * cloak_progress * (1.0 if known else 0.0), 3)

    @staticmethod
    def _risk(targets: tuple[BansheeTargetAssessment, ...]) -> float:
        """How dangerous flying in looks, 0.0-1.0.

        The worse of the two risks at the best target it would be safe to
        launch at -- or, with none, at the best target there is.
        """

        lead = next((target for target in targets if target.viable), None)
        if lead is None and targets:
            lead = targets[0]
        if lead is None:
            return 0.0
        return round(max(lead.air_defense_risk, lead.army_risk), 3)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _believed(reading: float, confidence: float, *, assumed: float) -> float:
    """``reading`` where ``confidence`` covers it, at least ``assumed`` where not."""

    covered = _clamp01(confidence)
    return covered * reading + (1.0 - covered) * max(reading, assumed)


def _proximity(distance: float, contact: float, reach: float) -> float:
    """1.0 within ``contact``, fading linearly to 0.0 at ``reach``."""

    return _clamp01((reach - distance) / (reach - contact))
