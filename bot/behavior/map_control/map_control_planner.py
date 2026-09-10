from __future__ import annotations

import math
from dataclasses import dataclass, field

from bot.engine.missions.models import (
    MissionKind,
    MissionMode,
    MissionProposal,
    UnitRequirement,
)
from bot.engine.missions.planning import ProposalCadence
from bot.world.attention import AttentionSnapshot, UnitSnapshot
from bot.world.awareness import AwarenessSnapshot

from .map_control_config import MapControlPlannerConfig


@dataclass(slots=True)
class MapControlPlanner:
    """Keeps a small, expendability-averse squad moving through the map."""

    config: MapControlPlannerConfig = field(default_factory=MapControlPlannerConfig)
    planner_id: str = "map_control_planner"
    _cadence: ProposalCadence = field(
        default_factory=ProposalCadence, init=False, repr=False
    )

    def propose(
        self,
        attention: AttentionSnapshot,
        awareness: AwarenessSnapshot,
    ) -> tuple[MissionProposal, ...]:
        world = attention.world
        if world.time < self.config.start_after:
            return ()
        if not self._cadence.ready(world.time, self.config.proposal_cadence):
            return ()

        eligible = tuple(
            unit for unit in world.own_units if self._eligible_for_patrol(unit)
        )
        if len(eligible) < self.config.minimum_force_size:
            return ()
        desired = self.config.desired_units or max(
            1, math.ceil(len(eligible) * self.config.force_ratio)
        )

        self._cadence.mark(world.time)
        sequence = self._cadence.next_sequence()
        target_key = "map_control:patrol"
        return (
            MissionProposal(
                proposal_id=f"{self.planner_id}:{sequence}",
                deduplication_key=target_key,
                planner=self.planner_id,
                kind=MissionKind.MAP_CONTROL,
                priority=self.config.priority,
                target_key=target_key,
                target=world.map.center,
                reason="persistent_map_control_share_available",
                requirement=UnitRequirement.combat(
                    unit_types=self.config.unit_types,
                    desired=desired,
                    # The standing mission survives full defense preemption.
                    minimum=0,
                    minimum_health=self.config.minimum_unit_health,
                ),
                created_at=world.time,
                timeout_seconds=self.config.mission_timeout,
                cooldown_seconds=self.config.failure_cooldown,
                # See the equivalent comment in HarassPlanner: standing
                # The main army holds most combat units, so map control must
                # be able to acquire its smaller standing share from it.
                can_preempt=True,
                commitment_seconds=self.config.commitment_seconds,
                mode=MissionMode.STANDING,
                squad_id="map_control",
            ),
        )

    def _eligible_for_patrol(self, unit: UnitSnapshot) -> bool:
        return (
            unit.unit_type in self.config.unit_types
            and unit.is_ready
            and unit.health_percentage >= self.config.minimum_unit_health
        )

    @staticmethod
    def _visible_combat_enemy(attention: AttentionSnapshot) -> bool:
        return any(
            enemy.is_visible_combat_threat() for enemy in attention.world.enemy_units
        )
