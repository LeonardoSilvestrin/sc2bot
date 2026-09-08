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
class WorkerLineHarassExecutor(MissionExecutor):
    """Pressure a worker line, focus weak workers, and preserve the Reaper."""

    mission_id: str
    target_key: str
    target: Point2
    started_at: float
    worker_search_radius: float = 16.0
    arrival_radius: float = 3.0
    retreat_health: float = 0.40
    retreat_arrival_radius: float = 10.0
    _retreating: bool = False

    async def step(self, context: MissionContext) -> MissionResult:
        if not context.assigned_units:
            return MissionResult(MissionOutcome.FAILED, "assigned_unit_missing")

        harasser = context.assigned_units[0]
        if harasser.health_percentage <= self.retreat_health:
            self._retreating = True

        if self._retreating:
            retreat_target = context.attention.world.map.own_start
            if (
                harasser.position.distance_to(retreat_target)
                <= self.retreat_arrival_radius
            ):
                return MissionResult(
                    MissionOutcome.COMPLETED,
                    "critical_reaper_returned_to_safety",
                )
            context.commands.safe_path_to(
                mission_id=self.mission_id,
                unit_tag=harasser.tag,
                target=retreat_target,
                success_at_distance=self.retreat_arrival_radius,
                search_radius=6.0,
            )
            return MissionResult(
                MissionOutcome.ACTIVE,
                "retreating_critical_reaper",
            )

        workers = tuple(
            unit
            for unit in context.attention.world.enemy_units
            if unit.visible_now
            and unit.is_worker
            and unit.position.distance_to(self.target) <= self.worker_search_radius
        )
        if workers:
            target = min(
                workers,
                key=lambda unit: (
                    unit.health_percentage,
                    unit.position.distance_to(harasser.position),
                    unit.tag,
                ),
            )
            context.commands.attack_unit(
                mission_id=self.mission_id,
                unit_tag=harasser.tag,
                target_unit_tag=target.tag,
            )
            return MissionResult(
                MissionOutcome.ACTIVE,
                "focusing_low_health_enemy_worker",
            )

        context.commands.attack_move(
            mission_id=self.mission_id,
            unit_tag=harasser.tag,
            target=self.target,
            success_at_distance=self.arrival_radius,
        )
        return MissionResult(MissionOutcome.ACTIVE, "harassing_enemy_worker_line")
