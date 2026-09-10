"""ASSESS: is there a Reaper free, and a worker line worth visiting?"""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.world.attention import AttentionSnapshot
from bot.world.awareness import AwarenessSnapshot

from .model import ReaperHarassAssessment, ReaperHarassConfig, ReaperHarassTarget


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
        targets = tuple(
            ReaperHarassTarget(
                key=key,
                position=location.position,
                last_observed_at=location.last_observed_at,
                age=location.age,
                stale_after=location.stale_after,
            )
            for key in self.config.target_keys
            if (location := awareness.enemy.location(key)) is not None
        )
        workers = sum(unit.is_worker for unit in world.own_units)
        known = any(target.is_known for target in targets)
        return ReaperHarassAssessment(
            now=world.time,
            reapers_available=available,
            workers=workers,
            candidate_targets=targets,
            readiness=round(
                min(1.0, available)
                * min(1.0, workers / self.config.minimum_workers)
                * (1.0 if known else 0.0),
                3,
            ),
        )
