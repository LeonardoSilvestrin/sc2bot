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
class PositioningExecutor(MissionExecutor):
    """Keeps assigned units near an anchor point without command spam.

    A unit already within ``arrival_radius`` of the anchor is left alone --
    it may sit physically idle, which is the correct state for a standing
    POSITION/RESERVE responsibility (see DispositionPlanner). Only units
    that have drifted out of tolerance (freshly assigned, pushed off by
    combat, ...) get a movement command this step.

    Never fails and never completes on its own: a standing mission's
    lifecycle is driven by proposals/allocation (see
    ``MissionController._update_standing``), not by executor outcomes. With
    zero assigned units (fully preempted) it simply does nothing that tick.
    """

    mission_id: str
    target_key: str
    target: Point2
    started_at: float
    arrival_radius: float = 4.0

    async def step(self, context: MissionContext) -> MissionResult:
        units = context.assigned_units
        if not units:
            return MissionResult(MissionOutcome.ACTIVE, "no_units_assigned")

        moved = False
        for unit in units:
            if unit.position.distance_to(self.target) <= self.arrival_radius:
                continue
            context.commands.safe_path_to(
                mission_id=self.mission_id,
                unit_tag=unit.tag,
                target=self.target,
                success_at_distance=self.arrival_radius,
            )
            moved = True

        return MissionResult(
            MissionOutcome.ACTIVE,
            "moving_to_position" if moved else "holding_position",
        )
