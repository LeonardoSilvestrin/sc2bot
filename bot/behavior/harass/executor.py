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


@dataclass(slots=True)
class CloakedBansheeHarassExecutor(MissionExecutor):
    """Attack-moves a Banshee into an enemy worker line, keeping cloak
    toggled on every step, and disengages the instant an anti-air-capable
    defender comes within range.

    A ground-only, non-anti-air defender simply cannot touch a flying
    harasser, so unlike ``WorkerLineHarassExecutor`` this checks
    ``can_attack_air`` rather than ``can_attack_ground``. Cloak is (re-)cast
    every step rather than tracked as on/off state: ``UseAbility`` is a
    no-op once already cloaked (the toggle-on ability drops out of
    ``unit.abilities``) and silently does nothing before the Banshee
    Cloaking Field upgrade completes or once energy runs out, so no local
    bookkeeping is needed to stay correct across all three cases.
    """

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
            and unit.can_attack_air
            and unit.position.distance_to(self.target) <= self.disengage_radius
        )
        if defenders:
            return MissionResult(MissionOutcome.COMPLETED, "harass_target_defended")

        if not context.assigned_units:
            return MissionResult(MissionOutcome.FAILED, "assigned_unit_missing")

        harasser = context.assigned_units[0]
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
