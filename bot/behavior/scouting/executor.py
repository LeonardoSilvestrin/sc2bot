from __future__ import annotations

from dataclasses import dataclass

from sc2.position import Point2

from bot.engine.missions.execution import (
    MissionContext,
    MissionExecutor,
    MissionOutcome,
    MissionResult,
)


@dataclass(slots=True)
class ScoutExecutor(MissionExecutor):
    mission_id: str
    target_key: str
    target: Point2
    started_at: float
    arrival_radius: float = 7.0

    async def step(self, context: MissionContext) -> MissionResult:
        location = context.awareness.enemy.location(self.target_key)
        if (
            location is not None
            and location.last_observed_at is not None
            and location.last_observed_at > self.started_at
        ):
            return MissionResult(
                MissionOutcome.COMPLETED,
                "target_observed_after_mission_started",
            )

        if not context.assigned_units:
            return MissionResult(MissionOutcome.FAILED, "assigned_unit_missing")

        scout = context.assigned_units[0]
        context.commands.path_to(
            mission_id=self.mission_id,
            unit_tag=scout.tag,
            target=self.target,
            success_at_distance=self.arrival_radius,
        )
        return MissionResult(MissionOutcome.ACTIVE, "moving_to_stale_location")
