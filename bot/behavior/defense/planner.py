"""PLAN: one defense mission per threatened base.

A base only gets a proposal once its security drops to THREATENED or
CRITICAL, so several bases under attack at the same time get independent
missions instead of competing for a single global "own_base" slot, and a
base that already has enough defenders nearby does not pull reinforcements
it does not need. Requested unit count grows with how outnumbered the base's
current defenders are.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from bot.behavior.contracts import BehaviorLog
from bot.engine.missions.models import MissionProposal, UnitRequirement
from bot.engine.missions.planning import ProposalCadence
from bot.ports.logging import BotLogger
from bot.world.attention import AttentionSnapshot
from bot.world.awareness import AwarenessSnapshot

from .assessment import DefenseAssessor
from .model import DefenseAssessment, DefenseConfig, DefensePlan, ThreatenedBase

COMPONENT = "behavior.defense"


@dataclass(slots=True)
class DefensePlanner:
    """Proposes one defense mission per currently threatened base."""

    config: DefenseConfig = field(default_factory=DefenseConfig)
    logger: BotLogger | None = None
    planner_id: str = "defense_planner"
    _assessor: DefenseAssessor = field(init=False, repr=False)
    _log: BehaviorLog = field(init=False, repr=False)
    _cadence: ProposalCadence = field(
        default_factory=ProposalCadence, init=False, repr=False
    )
    last_assessment: DefenseAssessment | None = field(
        default=None, init=False, repr=False
    )
    last_plans: tuple[DefensePlan, ...] = field(
        default=(), init=False, repr=False
    )

    def __post_init__(self) -> None:
        self._assessor = DefenseAssessor(config=self.config)
        self._log = BehaviorLog(component=COMPONENT, logger=self.logger)

    def propose(
        self,
        attention: AttentionSnapshot,
        awareness: AwarenessSnapshot,
    ) -> tuple[MissionProposal, ...]:
        now = attention.world.time
        if not self._cadence.ready(now, self.config.proposal_cadence):
            return ()

        assessment = self._assessor.assess(attention, awareness)
        self.last_assessment = assessment
        if not assessment.under_attack:
            # Nothing to defend: do not consume the cadence, so the very next
            # frame an attack starts can react immediately.
            self.last_plans = ()
            return ()

        self._cadence.mark(now)
        plans = tuple(self._plan(base) for base in assessment.threatened)
        self.last_plans = plans
        self._log.assessed(assessment, now=now, decision="propose")
        for plan in plans:
            self._log.proposed(plan, now=now, planner=self.planner_id)
        return tuple(self._proposal_for(plan, now) for plan in plans)

    def _plan(self, base: ThreatenedBase) -> DefensePlan:
        return DefensePlan(
            base=base,
            desired_units=min(
                self.config.max_desired_units,
                max(self.config.minimum_units, math.ceil(base.gap)),
            ),
            priority=(
                self.config.critical_priority
                if base.is_critical
                else self.config.threatened_priority
            ),
            reason=(
                "base_undefended_against_observed_threat"
                if base.is_critical
                else "base_outnumbered_by_observed_threat"
            ),
        )

    def _proposal_for(self, plan: DefensePlan, now: float) -> MissionProposal:
        sequence = self._cadence.next_sequence()
        base_id = plan.base.base_id
        return MissionProposal(
            proposal_id=f"{self.planner_id}:defense:{base_id}:{sequence}",
            deduplication_key=f"defense:{base_id}",
            planner=self.planner_id,
            kind=self.config.mission_kind,
            priority=plan.priority,
            target_key=base_id,
            target=plan.target,
            reason=plan.reason,
            requirement=UnitRequirement.combat(
                unit_types=self.config.unit_types,
                desired=plan.desired_units,
                minimum=self.config.minimum_units,
                minimum_health=self.config.minimum_unit_health,
                # Every defender type is equally wanted for now. This is the
                # seam where "Thors and Marines against Mutalisks, and leave
                # the Banshees on their raid" will be expressed -- see
                # `ThreatenedBase.air_threats`/`ground_threats`, which the
                # assessment already carries.
            ),
            created_at=now,
            timeout_seconds=self.config.mission_timeout,
            cooldown_seconds=self.config.failure_cooldown,
            can_preempt=True,
            commitment_seconds=self.config.commitment_seconds,
        )
