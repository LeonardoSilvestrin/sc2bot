"""EXECUTE: engage whatever is attacking the base, until nothing is left."""

from __future__ import annotations

from dataclasses import dataclass, field

from sc2.position import Point2

from bot.engine.missions.execution import (
    MissionContext,
    MissionExecutor,
    MissionOutcome,
    MissionResult,
)

from .model import DefenseConfig


@dataclass(slots=True)
class DefendBaseExecutor(MissionExecutor):
    """Attack-moves the assigned team onto the nearest observed threat and
    completes once no threat remains near where it was admitted to fight."""

    mission_id: str
    target_key: str
    target: Point2
    started_at: float
    config: DefenseConfig = field(default_factory=DefenseConfig)

    @property
    def engagement_radius(self) -> float:
        return self.config.engagement_radius

    @property
    def arrival_radius(self) -> float:
        return self.config.arrival_radius

    async def step(self, context: MissionContext) -> MissionResult:
        threats = tuple(
            unit
            for unit in context.attention.world.enemy_units
            if unit.is_visible_combat_threat()
            and unit.position.distance_to(self.target) <= self.engagement_radius
        )
        if not threats:
            return MissionResult(
                MissionOutcome.COMPLETED, "threat_cleared_near_own_base"
            )

        if not context.assigned_units:
            return MissionResult(MissionOutcome.FAILED, "assigned_unit_missing")

        nearest = min(threats, key=lambda unit: unit.position.distance_to(self.target))
        for defender in context.assigned_units:
            context.commands.attack_move(
                mission_id=self.mission_id,
                unit_tag=defender.tag,
                target=nearest.position,
                success_at_distance=self.arrival_radius,
            )
        return MissionResult(MissionOutcome.ACTIVE, "engaging_enemy_near_own_base")
