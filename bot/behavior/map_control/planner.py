"""PLAN: keep a small, expendability-averse share of the army on the map.

This is the roaming counterpart to `behavior/standing/`: the core army holds
its anchor, and this claims the remainder. It only declares the squad once
enough suitable units exist that taking a fifth of them still leaves a real
army at home.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from bot.behavior.contracts import BehaviorLog
from bot.engine.missions.models import MissionMode, MissionProposal, UnitRequirement
from bot.engine.missions.planning import ProposalCadence
from bot.ports.logging import BotLogger
from bot.world.attention import AttentionSnapshot
from bot.world.awareness import AwarenessSnapshot

from .assessment import MapControlAssessor
from .model import MapControlAssessment, MapControlConfig, MapControlPlan

COMPONENT = "behavior.map_control"
DEDUPLICATION_KEY = "map_control:patrol"


@dataclass(slots=True)
class MapControlPlanner:
    """Declares the standing patrol squad and its share of the army."""

    config: MapControlConfig = field(default_factory=MapControlConfig)
    logger: BotLogger | None = None
    planner_id: str = "map_control_planner"
    _assessor: MapControlAssessor = field(init=False, repr=False)
    _log: BehaviorLog = field(init=False, repr=False)
    _cadence: ProposalCadence = field(
        default_factory=ProposalCadence, init=False, repr=False
    )
    last_assessment: MapControlAssessment | None = field(
        default=None, init=False, repr=False
    )
    last_plan: MapControlPlan | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._assessor = MapControlAssessor(config=self.config)
        self._log = BehaviorLog(component=COMPONENT, logger=self.logger)

    def propose(
        self,
        attention: AttentionSnapshot,
        awareness: AwarenessSnapshot,
    ) -> tuple[MissionProposal, ...]:
        now = attention.world.time
        if now < self.config.start_after:
            return ()
        if not self._cadence.ready(now, self.config.proposal_cadence):
            return ()

        assessment = self._assessor.assess(attention, awareness)
        self.last_assessment = assessment
        if assessment.eligible_units < self.config.minimum_force_size:
            self.last_plan = None
            return ()

        self._cadence.mark(now)
        plan = MapControlPlan(
            anchor=attention.world.map.center,
            desired_units=self.config.desired_units
            or max(
                1, math.ceil(assessment.eligible_units * self.config.force_ratio)
            ),
            priority=self.config.priority,
        )
        self._log_plan_change(plan, assessment)
        self.last_plan = plan
        return (self._proposal_for(plan, now),)

    def _log_plan_change(
        self, plan: MapControlPlan, assessment: MapControlAssessment
    ) -> None:
        """Only speak up when the squad's size or anchor actually moves."""

        if self.last_plan == plan:
            return
        self._log.assessed(assessment, now=assessment.now, decision="propose")
        self._log.proposed(plan, now=assessment.now, planner=self.planner_id)

    def _proposal_for(self, plan: MapControlPlan, now: float) -> MissionProposal:
        sequence = self._cadence.next_sequence()
        return MissionProposal(
            proposal_id=f"{self.planner_id}:{sequence}",
            deduplication_key=DEDUPLICATION_KEY,
            planner=self.planner_id,
            kind=self.config.mission_kind,
            priority=plan.priority,
            target_key=DEDUPLICATION_KEY,
            target=plan.anchor,
            reason="persistent_map_control_share_available",
            requirement=UnitRequirement.combat(
                unit_types=self.config.unit_types,
                desired=plan.desired_units,
                # The standing mission survives full defense preemption.
                minimum=0,
                minimum_health=self.config.minimum_unit_health,
            ),
            created_at=now,
            timeout_seconds=self.config.mission_timeout,
            cooldown_seconds=self.config.failure_cooldown,
            # The core army holds most combat units, so map control must be
            # able to acquire its smaller standing share from it.
            can_preempt=True,
            commitment_seconds=self.config.commitment_seconds,
            mode=MissionMode.STANDING,
            squad_id=self.config.squad_id,
        )
