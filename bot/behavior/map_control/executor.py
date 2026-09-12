"""EXECUTE: walk the safe patrol loop, and go home from anything scary."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from sc2.position import Point2

from bot.behavior.contracts import BehaviorLog
from bot.engine.missions.execution import (
    MissionContext,
    MissionExecutor,
    MissionOutcome,
    MissionResult,
)
from bot.engine.missions.models import Mission
from bot.ports.logging import BotLogger
from bot.world.attention import UnitSnapshot
from bot.world.awareness import MacroPosture
from bot.world.awareness.bases import BaseSecurityLevel
from bot.world.awareness.spatial import SpatialField

from .model import MapControlConfig, PatrolPhase

COMPONENT = "behavior.map_control"


@dataclass(slots=True)
class MapControlExecutor(MissionExecutor):
    """Patrols the region around its spatial anchor and disengages from fights."""

    mission_id: str
    target_key: str
    target: Point2
    started_at: float
    config: MapControlConfig = field(default_factory=MapControlConfig)
    logger: BotLogger | None = None
    phase: PatrolPhase = field(default=PatrolPhase.WAITING, init=False, repr=False)
    _log: BehaviorLog = field(init=False, repr=False)
    _waypoint_index: int = field(default=0, init=False, repr=False)
    _patrol_route: tuple[Point2, ...] = field(default=(), init=False, repr=False)
    _patrol_route_key: tuple | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._log = BehaviorLog(component=COMPONENT, logger=self.logger)

    @property
    def danger_radius(self) -> float:
        return self.config.danger_radius

    @property
    def arrival_radius(self) -> float:
        return self.config.arrival_radius

    @property
    def retreat_arrival_radius(self) -> float:
        return self.config.retreat_arrival_radius

    @property
    def retreat_health(self) -> float:
        return self.config.retreat_health

    def refresh(self, mission: Mission) -> None:
        """Follow a hysteresis-approved target without replacing the mission."""

        target = mission.proposal.target
        if target != self.target:
            self.target = target
            self._waypoint_index = 0

    async def step(self, context: MissionContext) -> MissionResult:
        units = context.assigned_units
        if not units:
            self._enter(PatrolPhase.WAITING, "no_units_assigned", context)
            return MissionResult(MissionOutcome.ACTIVE, "waiting_for_squad_members")

        retreat_reason = self._retreat_reason(context, units)
        if retreat_reason is not None:
            retreat_target = self._retreat_target(context, units)
            if all(
                unit.position.distance_to(retreat_target)
                <= self.retreat_arrival_radius
                for unit in units
            ):
                self._enter(PatrolPhase.HOLDING_HOME, retreat_reason, context)
                return MissionResult(
                    MissionOutcome.ACTIVE,
                    f"{retreat_reason}_holding_home",
                )
            self._enter(PatrolPhase.RETREAT, retreat_reason, context)
            self._move_safely(context, units, retreat_target)
            return MissionResult(
                MissionOutcome.ACTIVE,
                f"{retreat_reason}_retreating",
            )

        self._enter(PatrolPhase.PATROL, "map_is_clear_enough", context)
        waypoints = self._patrol_waypoints(context.awareness.spatial)
        waypoint = waypoints[self._waypoint_index % len(waypoints)]
        if all(
            unit.position.distance_to(waypoint) <= self.arrival_radius
            for unit in units
        ):
            self._waypoint_index = (self._waypoint_index + 1) % len(waypoints)
            waypoint = waypoints[self._waypoint_index]

        self._move_safely(context, units, waypoint)
        return MissionResult(MissionOutcome.ACTIVE, "patrolling_safe_map_route")

    def _patrol_waypoints(self, spatial: SpatialField) -> tuple[Point2, ...]:
        """The anchor, then the pathable samples of its region by angle.

        The planner owns where the region is; this only walks it. Every
        waypoint is a sampled pathable point, and sweeping them by angle
        circles the anchor instead of zig-zagging across it. Without a field
        yet, the region is just the anchor.
        """

        key = (self.target, spatial.sample_spacing, len(spatial.samples))
        if key != self._patrol_route_key:
            anchor = self.target
            radius = self.config.patrol_radius_sample_steps * spatial.sample_spacing
            ring = sorted(
                (
                    sample.position
                    for sample in spatial.near(anchor, radius)
                    if sample.position != anchor
                ),
                key=lambda position: math.atan2(
                    position.y - anchor.y, position.x - anchor.x
                ),
            )
            self._patrol_route = (anchor, *ring)
            self._patrol_route_key = key
        return self._patrol_route

    def _enter(
        self, phase: PatrolPhase, reason: str, context: MissionContext
    ) -> None:
        if self.phase is phase:
            return
        self.phase = phase
        self._log.state_changed(
            now=context.attention.world.time,
            state=phase.name,
            reason=reason,
            mission_id=self.mission_id,
        )

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
