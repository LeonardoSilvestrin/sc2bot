from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.ability_id import AbilityId
from sc2.position import Point2

from bot.engine.missions.execution import (
    MissionContext,
    MissionExecutor,
    MissionOutcome,
    MissionResult,
)
from bot.engine.missions.models import Mission
from bot.world.attention import UnitSnapshot
from bot.world.awareness.bases import BaseSecurityLevel


@dataclass(slots=True)
class CloakedBansheeHarassExecutor(MissionExecutor):
    """Persistent attack/retreat/recover loop for the Banshee squad."""

    mission_id: str
    target_key: str
    target: Point2
    started_at: float
    disengage_radius: float = 12.0
    arrival_radius: float = 3.0
    retreat_health: float = 0.45
    recover_health: float = 0.8
    _retreating: bool = False

    def refresh(self, mission: Mission) -> None:
        self.target_key = mission.proposal.target_key
        self.target = mission.proposal.target

    async def step(self, context: MissionContext) -> MissionResult:
        defenders = tuple(
            unit
            for unit in context.attention.world.enemy_units
            if unit.is_visible_combat_threat(against_ground=False)
            and unit.position.distance_to(self.target) <= self.disengage_radius
        )
        harassers = context.assigned_units
        if not harassers:
            return MissionResult(MissionOutcome.ACTIVE, "waiting_for_banshee_squad")

        weakest_health = min(unit.health_percentage for unit in harassers)
        if defenders or weakest_health <= self.retreat_health:
            self._retreating = True
        if self._retreating:
            home = self._home_anchor(context, self._centroid(harassers))
            recovered = (
                not defenders
                and weakest_health >= self.recover_health
                and all(
                    unit.position.distance_to(home) <= self.arrival_radius
                    for unit in harassers
                )
            )
            if not recovered:
                for harasser in harassers:
                    context.commands.safe_path_to(
                        mission_id=self.mission_id,
                        unit_tag=harasser.tag,
                        target=home,
                        success_at_distance=self.arrival_radius,
                    )
                return MissionResult(
                    MissionOutcome.ACTIVE, "banshee_squad_retreating_or_recovering"
                )
            self._retreating = False

        for harasser in harassers:
            context.commands.use_ability(
                mission_id=self.mission_id,
                unit_tag=harasser.tag,
                ability=AbilityId.BEHAVIOR_CLOAKON_BANSHEE,
            )
            context.commands.attack_move(
                mission_id=self.mission_id,
                unit_tag=harasser.tag,
                target=self.target,
                success_at_distance=self.arrival_radius,
            )
        return MissionResult(
            MissionOutcome.ACTIVE, "harassing_enemy_worker_line_cloaked"
        )

    @staticmethod
    def _centroid(units: tuple[UnitSnapshot, ...]) -> Point2:
        x = sum(unit.position.x for unit in units) / len(units)
        y = sum(unit.position.y for unit in units) / len(units)
        return Point2((x, y))

    @staticmethod
    def _home_anchor(context: MissionContext, position: Point2) -> Point2:
        safe = tuple(
            base
            for base in context.awareness.bases
            if base.security is BaseSecurityLevel.SAFE
        )
        if not safe:
            return context.attention.world.map.own_start
        return min(safe, key=lambda base: base.position.distance_to(position)).position
