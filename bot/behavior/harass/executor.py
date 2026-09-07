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
    """Attack-moves one unit into an enemy worker line and disengages if
    the target becomes defended, rather than fighting to the death."""

    mission_id: str
    target_key: str
    target: Point2
    started_at: float
    disengage_radius: float = 12.0
    arrival_radius: float = 3.0

    async def step(self, context: MissionContext) -> MissionResult:
        defenders = tuple(
            unit
            for unit in context.attention.world.enemy_units
            if unit.visible_now
            and not unit.is_worker
            and (unit.can_attack_ground or unit.can_attack_air)
            and unit.position.distance_to(self.target) <= self.disengage_radius
        )
        if defenders:
            return MissionResult(MissionOutcome.COMPLETED, "harass_target_defended")

        if not context.assigned_units:
            return MissionResult(MissionOutcome.FAILED, "assigned_unit_missing")

        harasser = context.assigned_units[0]
        context.commands.attack_move(
            mission_id=self.mission_id,
            unit_tag=harasser.tag,
            target=self.target,
            success_at_distance=self.arrival_radius,
        )
        return MissionResult(MissionOutcome.ACTIVE, "harassing_enemy_worker_line")
