"""ASSESS: is there a Reaper free, and a worker line worth visiting?

Every enemy base Awareness has confirmed is read as a Reaper target through
`ReaperTargetHeuristics` -- the Reaper's own reading of the same bases and
force clusters the Banshee raid reads for air. Like every assessment it only
describes: which base the next raid goes to is the planner's call.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sc2.position import Point2

from bot.world.attention import AttentionSnapshot
from bot.world.awareness import (
    AwarenessSnapshot,
    EnemyBaseAssessment,
    EnemyForceAwareness,
    EnemyLocationKnowledge,
)

from .model import (
    ReaperHarassAssessment,
    ReaperHarassConfig,
    ReaperTargetAssessment,
)


@dataclass(slots=True)
class ReaperHarassAssessor:
    config: ReaperHarassConfig = field(default_factory=ReaperHarassConfig)

    def assess(
        self, attention: AttentionSnapshot, awareness: AwarenessSnapshot
    ) -> ReaperHarassAssessment:
        world = attention.world
        available = sum(
            unit.unit_type in self.config.unit_types
            and unit.available_for_mission
            and unit.is_ready
            and unit.health_percentage >= self.config.minimum_unit_health
            for unit in world.own_units
        )
        targets = self._targets(awareness, now=world.time)
        workers = sum(unit.is_worker for unit in world.own_units)
        viable = any(target.viable for target in targets)
        return ReaperHarassAssessment(
            now=world.time,
            reapers_available=available,
            workers=workers,
            targets=targets,
            readiness=round(
                min(1.0, available)
                * min(1.0, workers / self.config.minimum_workers)
                * (1.0 if viable else 0.0),
                3,
            ),
        )

    # --- targets ------------------------------------------------------------

    def _targets(
        self, awareness: AwarenessSnapshot, *, now: float
    ) -> tuple[ReaperTargetAssessment, ...]:
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
    ) -> ReaperTargetAssessment:
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
            ground_defense_risk=self._ground_defense_risk(
                base.ground_defense, base.ground_defense_confidence
            ),
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
    ) -> ReaperTargetAssessment:
        """An observed location with no base reading: its value is assumed and
        its ground defense entirely unknown."""

        heuristics = self.config.targeting
        return self._scored(
            key=location.key,
            position=location.position,
            economic_opportunity=heuristics.fallback_opportunity,
            ground_defense_risk=self._ground_defense_risk(0.0, 0.0),
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
        ground_defense_risk: float,
        army_risk: float,
        information_confidence: float,
        workers: int,
        last_observed_at: float | None,
        age: float | None,
        stale_after: float | None,
        is_fallback: bool = False,
    ) -> ReaperTargetAssessment:
        """Add the components up, as `ReaperTargetHeuristics` describes."""

        heuristics = self.config.targeting
        score = (
            heuristics.opportunity_weight * economic_opportunity
            - heuristics.ground_defense_weight * ground_defense_risk
            - heuristics.army_weight * army_risk
            - heuristics.uncertainty_weight * (1.0 - information_confidence)
        )
        return ReaperTargetAssessment(
            key=key,
            position=position,
            score=score,
            economic_opportunity=economic_opportunity,
            ground_defense_risk=ground_defense_risk,
            army_risk=army_risk,
            information_confidence=information_confidence,
            workers=workers,
            viable=(
                ground_defense_risk <= heuristics.max_ground_defense_risk
                and army_risk <= heuristics.max_army_risk
            ),
            last_observed_at=last_observed_at,
            age=age,
            stale_after=stale_after,
            is_fallback=is_fallback,
        )

    def _ground_defense_risk(self, reading: float, confidence: float) -> float:
        """Believed ground defense beyond what a Reaper shrugs off, 0..1."""

        heuristics = self.config.targeting
        covered = _clamp01(confidence)
        believed = covered * reading + (1.0 - covered) * max(
            reading, heuristics.assumed_ground_defense
        )
        tolerated = heuristics.tolerated_ground_defense
        return _clamp01((believed - tolerated) / (1.0 - tolerated))

    def _army_risk(self, forces: EnemyForceAwareness, position: Point2) -> float:
        """Anti-ground strength at hand beyond what a Reaper shrugs off.

        No confidence floor: a Reaper outruns a force it did not expect, so
        only one believed to be there now keeps it away.
        """

        heuristics = self.config.targeting
        threat = sum(
            cluster.anti_ground_strength
            * _proximity(
                cluster.distance_to(position),
                heuristics.army_contact_radius,
                heuristics.army_reach,
            )
            * cluster.confidence
            for cluster in forces.near(position, heuristics.army_reach)
        )
        return _clamp01(
            (threat - heuristics.tolerated_army_strength)
            / heuristics.dangerous_ground_strength
        )


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _proximity(distance: float, contact: float, reach: float) -> float:
    """1.0 within ``contact``, fading linearly to 0.0 at ``reach``."""

    return _clamp01((reach - distance) / (reach - contact))
