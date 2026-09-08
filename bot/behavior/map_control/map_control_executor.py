from __future__ import annotations

import math
from dataclasses import dataclass, field

from sc2.position import Point2

from bot.engine.missions.execution import (
    MissionContext,
    MissionExecutor,
    MissionOutcome,
    MissionResult,
)
from bot.world.attention import MapFacts, UnitSnapshot
from bot.world.awareness import MacroPosture
from bot.world.awareness.bases import BaseSecurityLevel


@dataclass(slots=True)
class MapControlExecutor(MissionExecutor):
    """Patrols the friendly half of the map and disengages from every fight."""

    mission_id: str
    target_key: str
    target: Point2
    started_at: float
    danger_radius: float = 20.0
    arrival_radius: float = 5.0
    retreat_arrival_radius: float = 7.0
    retreat_health: float = 0.6
    _waypoint_index: int = field(default=0, init=False, repr=False)

    async def step(self, context: MissionContext) -> MissionResult:
        units = context.assigned_units
        if not units:
            return MissionResult(MissionOutcome.FAILED, "assigned_unit_missing")

        retreat_reason = self._retreat_reason(context, units)
        if retreat_reason is not None:
            retreat_target = self._retreat_target(context, units)
            if all(
                unit.position.distance_to(retreat_target)
                <= self.retreat_arrival_radius
                for unit in units
            ):
                return MissionResult(
                    MissionOutcome.COMPLETED,
                    f"{retreat_reason}_returned_home",
                )
            self._move_safely(context, units, retreat_target)
            return MissionResult(
                MissionOutcome.ACTIVE,
                f"{retreat_reason}_retreating",
            )

        waypoints = self._patrol_points(context.attention.world.map)
        waypoint = waypoints[self._waypoint_index % len(waypoints)]
        if all(
            unit.position.distance_to(waypoint) <= self.arrival_radius
            for unit in units
        ):
            self._waypoint_index = (self._waypoint_index + 1) % len(waypoints)
            waypoint = waypoints[self._waypoint_index]

        self._move_safely(context, units, waypoint)
        return MissionResult(MissionOutcome.ACTIVE, "patrolling_safe_map_route")

    def _retreat_reason(
        self,
        context: MissionContext,
        units: tuple[UnitSnapshot, ...],
    ) -> str | None:
        if context.awareness.macro_posture in {
            MacroPosture.DEFENSE,
            MacroPosture.RECOVERY,
        } or context.awareness.bases.threatened:
            return "strategic_danger"
        if any(unit.health_percentage <= self.retreat_health for unit in units):
            return "squad_health_low"
        if any(
            enemy.is_visible_combat_threat(against_air=False)
            and any(
                enemy.position.distance_to(unit.position) <= self.danger_radius
                for unit in units
            )
            for enemy in context.attention.world.enemy_units
        ):
            return "enemy_too_close"
        return None

    def _retreat_target(
        self,
        context: MissionContext,
        units: tuple[UnitSnapshot, ...],
    ) -> Point2:
        anchor = units[0].position
        safe_bases = tuple(
            base
            for base in context.awareness.bases
            if base.security is BaseSecurityLevel.SAFE
        )
        if not safe_bases:
            return context.attention.world.map.own_start
        return min(
            safe_bases,
            key=lambda base: base.position.distance_to(anchor),
        ).position

    def _move_safely(
        self,
        context: MissionContext,
        units: tuple[UnitSnapshot, ...],
        target: Point2,
    ) -> None:
        for unit in units:
            context.commands.safe_path_to(
                mission_id=self.mission_id,
                unit_tag=unit.tag,
                target=target,
                success_at_distance=self.arrival_radius,
            )

    @staticmethod
    def _patrol_points(map_facts: MapFacts) -> tuple[Point2, ...]:
        own = map_facts.own_start
        center = map_facts.center
        dx = float(center.x - own.x)
        dy = float(center.y - own.y)
        distance = math.hypot(dx, dy)
        if distance <= 1.0:
            return (center,)

        perpendicular_x = -dy / distance
        perpendicular_y = dx / distance
        side_offset = min(12.0, max(4.0, distance * 0.22))
        forward = Point2((own.x + dx * 0.78, own.y + dy * 0.78))
        staging = Point2((own.x + dx * 0.48, own.y + dy * 0.48))
        return (
            Point2(
                (
                    forward.x + perpendicular_x * side_offset,
                    forward.y + perpendicular_y * side_offset,
                )
            ),
            center,
            Point2(
                (
                    forward.x - perpendicular_x * side_offset,
                    forward.y - perpendicular_y * side_offset,
                )
            ),
            staging,
        )
