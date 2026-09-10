from __future__ import annotations

import math
from dataclasses import dataclass, field

from sc2.position import Point2

from bot.engine.missions.models import (
    MissionKind,
    MissionMode,
    MissionProposal,
    UnitRequirement,
)
from bot.engine.missions.planning import ProposalCadence
from bot.world.attention import AttentionSnapshot, MapFacts
from bot.world.awareness import AwarenessSnapshot

from .combat_posture import CombatPosture, derive_combat_posture
from .disposition_config import DispositionPlannerConfig


@dataclass(slots=True)
class DispositionPlanner:
    """Declares the persistent main-army squad's standing rally mission.

    This planner never touches units, leases, or commands -- like every
    other planner it only emits ``MissionProposal``s and leaves admission
    and arbitration to ``MissionController``/``UnitAllocator``. Its
    proposals use ``MissionMode.STANDING``: re-proposing the same
    ``deduplication_key`` updates the live
    mission's requirement/priority in place instead of being rejected as a
    duplicate (see ``MissionController._update_standing``), so a posture
    change reshapes the standing disposition without destroying and
    recreating missions every tick.

    The former absolute main/natural/third/forward/reserve slots are replaced
    by one proportional responsibility. MapControlPlanner owns the smaller
    map-control share; higher-priority missions may still preempt either squad.
    """

    config: DispositionPlannerConfig = field(default_factory=DispositionPlannerConfig)
    planner_id: str = "disposition_planner"
    _cadence: ProposalCadence = field(
        default_factory=ProposalCadence, init=False, repr=False
    )
    last_posture: CombatPosture = field(
        default=CombatPosture.BALANCED, init=False, repr=False
    )

    def propose(
        self,
        attention: AttentionSnapshot,
        awareness: AwarenessSnapshot,
    ) -> tuple[MissionProposal, ...]:
        world = attention.world
        if not self._cadence.ready(world.time, self.config.proposal_cadence):
            return ()
        self._cadence.mark(world.time)

        posture = derive_combat_posture(awareness=awareness)
        self.last_posture = posture
        eligible = sum(
            unit.unit_type in self.config.unit_types
            and unit.is_ready
            and unit.health_percentage >= self.config.minimum_unit_health
            for unit in world.own_units
        )
        desired = max(1, math.floor(eligible * self.config.main_army_ratio))
        return (
            self._main_army_proposal(
                target=self._rally_anchor(world.map, awareness),
                desired=desired,
                now=world.time,
            ),
        )

    def _main_army_proposal(
        self, *, target: Point2, desired: int, now: float
    ) -> MissionProposal:
        sequence = self._cadence.next_sequence()
        key = "hold_rally:main_army"
        return MissionProposal(
            proposal_id=f"{self.planner_id}:main_army:{sequence}",
            deduplication_key=key,
            planner=self.planner_id,
            kind=MissionKind.HOLD_RALLY,
            priority=self.config.main_priority,
            target_key=key,
            target=target,
            reason="main_army_holds_latest_expansion_rally",
            requirement=UnitRequirement.combat(
                unit_types=self.config.unit_types,
                desired=desired,
                minimum=0,
                minimum_health=self.config.minimum_unit_health,
            ),
            created_at=now,
            timeout_seconds=self.config.mission_timeout,
            cooldown_seconds=self.config.cooldown_seconds,
            can_preempt=True,
            commitment_seconds=self.config.commitment_seconds,
            mode=MissionMode.STANDING,
            squad_id="main_army",
        )

    def _rally_anchor(
        self, map_facts: MapFacts, awareness: AwarenessSnapshot
    ) -> Point2:
        """Deterministic point from the prior base toward the newest expansion.

        We do not have construction timestamps yet, so distance from the main
        is the deliberately simple proxy for expansion order.
        """

        held = sorted(
            awareness.bases,
            key=lambda base: (
                base.position.distance_to(map_facts.own_start),
                base.base_id,
            ),
        )
        if len(held) < 2:
            return held[0].position if held else map_facts.own_start
        newest = held[-1].position
        previous = held[-2].position
        fraction = self.config.rally_fraction_to_newest_expansion
        return Point2(
            (
                previous.x + (newest.x - previous.x) * fraction,
                previous.y + (newest.y - previous.y) * fraction,
            )
        )
