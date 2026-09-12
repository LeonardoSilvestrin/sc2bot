from __future__ import annotations

from ..heuristics import (
    EnemyBaseHeuristics,
    combat_value,
    defender_freshness,
    defense_score,
    economic_value,
)
from ..knowledge import EnemySighting
from .assessment import EnemyBaseAssessment, EnemyBaseAwareness
from .memory import EnemyBaseObservation, EnemyBaseStatus


class EnemyBaseAssessor:
    """Values each candidate enemy base slot from what Awareness remembers.

    ``EnemyBaseMemory`` says whether a slot holds a base; this says what that
    base is worth and how well it is defended, from the sightings around it.
    It keeps one thing across updates that no sighting does: how many
    workers a base had the last time any of them was in vision. Ares forgets
    an out-of-vision worker after ~30 s, but a counted mineral line is still
    the best estimate of that base until someone looks again -- the same way
    ``EnemyBaseMemory`` keeps a slot's status.
    """

    def __init__(self, config: EnemyBaseHeuristics | None = None) -> None:
        self.config = config or EnemyBaseHeuristics()
        self._worker_counts: dict[str, tuple[int, float]] = {}

    def update(
        self,
        *,
        observations: tuple[EnemyBaseObservation, ...],
        sightings: tuple[EnemySighting, ...],
        now: float,
    ) -> EnemyBaseAwareness:
        workers = tuple(sighting for sighting in sightings if sighting.is_worker)
        defenders = tuple(
            sighting
            for sighting in sightings
            if sighting.is_combat_unit or sighting.is_static_defense
        )
        return EnemyBaseAwareness(
            assessments=tuple(
                self._assess(observation, workers, defenders, now)
                for observation in observations
            )
        )

    def _assess(
        self,
        observation: EnemyBaseObservation,
        workers: tuple[EnemySighting, ...],
        defenders: tuple[EnemySighting, ...],
        now: float,
    ) -> EnemyBaseAssessment:
        config = self.config
        worker_count, counted_at = self._count_workers(observation, workers, now)
        air = ground = air_freshness = ground_freshness = 0.0
        for defender in defenders:
            if (
                defender.last_position.distance_to(observation.position)
                > config.defense_radius
            ):
                continue
            value = combat_value(defender, config.combat)
            fresh = defender_freshness(defender, now=now, config=config)
            air += value.anti_air
            ground += value.anti_ground
            air_freshness += value.anti_air * fresh
            ground_freshness += value.anti_ground * fresh

        return EnemyBaseAssessment(
            key=observation.key,
            position=observation.position,
            status=observation.status,
            economic_value=economic_value(
                confirmed=observation.status is EnemyBaseStatus.CONFIRMED,
                workers=worker_count,
                config=config,
            ),
            worker_count_estimate=worker_count,
            workers_counted_at=counted_at,
            air_defense=defense_score(air, config.full_air_defense),
            air_defense_confidence=_defense_confidence(
                air_freshness, air, observation
            ),
            ground_defense=defense_score(ground, config.full_ground_defense),
            ground_defense_confidence=_defense_confidence(
                ground_freshness, ground, observation
            ),
            last_confirmed_at=observation.last_confirmed_at,
            last_checked_at=observation.last_checked_at,
            confidence=observation.confidence,
            is_stale=observation.is_stale,
        )

    def _count_workers(
        self,
        observation: EnemyBaseObservation,
        workers: tuple[EnemySighting, ...],
        now: float,
    ) -> tuple[int, float | None]:
        """Recount a slot's workers whenever one of them is in vision.

        The count is every worker Awareness still remembers near the slot,
        not only the ones visible this frame, so a scout sweeping a mineral
        line accumulates the whole line rather than the last few it saw. A
        slot seen empty forgets its count.
        """

        key = observation.key
        if observation.status is EnemyBaseStatus.EMPTY:
            self._worker_counts.pop(key, None)
            return 0, None
        nearby = tuple(
            worker
            for worker in workers
            if worker.last_position.distance_to(observation.position)
            <= self.config.worker_radius
        )
        if any(worker.visible_now for worker in nearby):
            self._worker_counts[key] = (len(nearby), now)
        record = self._worker_counts.get(key)
        return (0, None) if record is None else record


def _defense_confidence(
    weighted_freshness: float, value: float, observation: EnemyBaseObservation
) -> float:
    """Value-weighted freshness of the defenders behind one defense reading.

    With no defender to weigh, the reading is "none seen here", which is
    exactly as current as the last look at the slot itself.
    """

    return weighted_freshness / value if value > 0.0 else observation.confidence
