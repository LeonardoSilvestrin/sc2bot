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
        if not context.assigned_units:
            return MissionResult(MissionOutcome.ACTIVE, "waiting_for_banshee_squad")

        harasser = context.assigned_units[0]
        if defenders or harasser.health_percentage <= self.retreat_health:
            self._retreating = True
        if self._retreating:
            home = self._home_anchor(context, harasser.position)
            recovered = (
                not defenders
                and harasser.health_percentage >= self.recover_health
                and harasser.position.distance_to(home) <= self.arrival_radius
            )
            if not recovered:
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
    def _home_anchor(context: MissionContext, position: Point2) -> Point2:
        safe = tuple(
            base
            for base in context.awareness.bases
            if base.security is BaseSecurityLevel.SAFE
        )
        if not safe:
            return context.attention.world.map.own_start
        return min(safe, key=lambda base: base.position.distance_to(position)).position
