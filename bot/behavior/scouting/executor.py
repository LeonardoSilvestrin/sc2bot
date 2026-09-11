"""EXECUTE: walk the scout around the target and report back.

A Reaper on a real map follows the map-derived perimeter route waypoint by
waypoint and completes only after closing the lap. Anything else -- a worker,
or a map with no extractable route -- just walks to the location and
completes as soon as Awareness records having seen it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.engine.missions.execution import (
    MissionContext,
    MissionExecutor,
    MissionOutcome,
    MissionResult,
)

from .model import IntelConfig


@dataclass(slots=True)
class ScoutExecutor(MissionExecutor):
    mission_id: str
    target_key: str
    target: Point2
    started_at: float
    config: IntelConfig = field(default_factory=IntelConfig)
    _waypoint_index: int = 0

    @property
    def arrival_radius(self) -> float:
        return self.config.arrival_radius

    @property
    def observation_radius(self) -> float:
        return self.config.observation_radius

    async def step(self, context: MissionContext) -> MissionResult:
        if not context.assigned_units:
            return MissionResult(MissionOutcome.FAILED, "assigned_unit_missing")

        scout = context.assigned_units[0]
        route = context.attention.world.map.route(self.target_key)
        if route is not None and scout.unit_type == UnitTypeId.REAPER:
            waypoints = route.waypoints
            while self._waypoint_index < len(waypoints):
                waypoint = waypoints[self._waypoint_index]
                distance = scout.position.distance_to(waypoint.position)
                if distance <= self.arrival_radius or (
                    waypoint.visible_now and distance <= self.observation_radius
                ):
                    self._waypoint_index += 1
                    continue
                context.commands.path_to(
                    mission_id=self.mission_id,
                    unit_tag=scout.tag,
                    target=waypoint.position,
                    success_at_distance=self.arrival_radius,
                )
                return MissionResult(
                    MissionOutcome.ACTIVE,
                    f"scouting_main_route_waypoint_{self._waypoint_index + 1}_of_"
                    f"{len(waypoints)}",
                )
            return MissionResult(MissionOutcome.COMPLETED, "enemy_main_route_completed")

        # Graceful fallback for workers and maps where a perimeter route could
        # not be extracted. Reaper scouts on normal ladder maps use the route.
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

        context.commands.path_to(
            mission_id=self.mission_id,
            unit_tag=scout.tag,
            target=self.target,
            success_at_distance=self.arrival_radius,
        )
        return MissionResult(MissionOutcome.ACTIVE, "moving_to_stale_location")
