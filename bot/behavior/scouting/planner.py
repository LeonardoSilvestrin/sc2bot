"""PLAN: spend one unit on information when the information is missing.

The only proposal in the bot that cannot preempt: scouting never takes a
unit already committed to something else. Information is worth a spare unit,
not worth interrupting a raid or a defense.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.behavior.contracts import BehaviorLog
from bot.engine.missions.models import MissionProposal, UnitRequirement
from bot.engine.missions.planning import ProposalCadence
from bot.ports.logging import BotLogger
from bot.world.attention import AttentionSnapshot
from bot.world.awareness import AwarenessSnapshot

from .assessment import IntelAssessor
from .model import IntelAssessment, IntelConfig, ScoutPlan

COMPONENT = "behavior.scouting"


@dataclass(slots=True)
class IntelPlanner:
    """Proposes one scout when selected enemy information is unknown or stale."""

    config: IntelConfig = field(default_factory=IntelConfig)
    logger: BotLogger | None = None
    planner_id: str = "intel_planner"
    _assessor: IntelAssessor = field(init=False, repr=False)
    _log: BehaviorLog = field(init=False, repr=False)
    _cadence: ProposalCadence = field(
        default_factory=ProposalCadence, init=False, repr=False
    )
    last_assessment: IntelAssessment | None = field(
        default=None, init=False, repr=False
    )
    last_plan: ScoutPlan | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._assessor = IntelAssessor(config=self.config)
        self._log = BehaviorLog(component=COMPONENT, logger=self.logger)

    def propose(
        self,
        attention: AttentionSnapshot,
        awareness: AwarenessSnapshot,
    ) -> tuple[MissionProposal, ...]:
        now = attention.world.time
        assessment = self._assessor.assess(attention, awareness)
        self.last_assessment = assessment

        plan = self._plan(assessment)
        if plan is None:
            self.last_plan = None
            return ()
        if not self._cadence.ready(now, self.config.proposal_cadence):
            return ()

        self._cadence.mark(now)
        self.last_plan = plan
        self._log.assessed(assessment, now=now, decision="propose")
        self._log.proposed(plan, now=now, planner=self.planner_id)
        return (self._proposal_for(plan, now),)

    def _plan(self, assessment: IntelAssessment) -> ScoutPlan | None:
        target = assessment.target
        if target is None or not target.is_stale:
            return None
        if assessment.workers < self.config.minimum_workers:
            return None
        # A location seen at least once is only revisited in the periodic
        # phase; before that, one look is enough.
        if (
            not target.never_seen
            and assessment.now < self.config.repeat_scouts_after
        ):
            return None
        if not assessment.scout_unit_types:
            return None
        return ScoutPlan(
            target=target,
            unit_types=assessment.scout_unit_types,
            priority=self.config.priority,
            reason=(
                f"{target.key}_information_unknown"
                if target.never_seen
                else f"{target.key}_information_stale"
            ),
        )

    def _proposal_for(self, plan: ScoutPlan, now: float) -> MissionProposal:
        sequence = self._cadence.next_sequence()
        key = plan.target.key
        return MissionProposal(
            proposal_id=f"{self.planner_id}:scout:{key}:{sequence}",
            deduplication_key=f"scout:{key}",
            planner=self.planner_id,
            kind=self.config.mission_kind,
            priority=plan.priority,
            target_key=key,
            target=plan.target.position,
            reason=plan.reason,
            requirement=UnitRequirement.combat(
                unit_types=plan.unit_types,
                desired=1,
                minimum=1,
                minimum_health=self.config.minimum_unit_health,
            ),
            created_at=now,
            evidence_last_observed_at=plan.target.last_observed_at,
            evidence_age=plan.target.age,
            evidence_stale_after=plan.target.stale_after,
            timeout_seconds=self.config.mission_timeout,
            cooldown_seconds=self.config.failure_cooldown,
            can_preempt=False,
            commitment_seconds=5.0,
        )
