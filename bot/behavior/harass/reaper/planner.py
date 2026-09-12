"""PLAN: launch a single-Reaper raid when one is genuinely spare.

A finite mission, not a standing one: the Reaper goes, does damage, and
comes home or dies. Nothing should keep re-declaring it, so a raid keeps the
base it was launched at for as long as it lives. Where the *next* raid goes
is chosen again from the assessment's ranking, holding on to the previous
raid's base until another is clearly better
(`ReaperTargetHeuristics.retarget_margin`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.behavior.contracts import BehaviorLog
from bot.engine.missions.models import MissionProposal, UnitRequirement
from bot.engine.missions.planning import (
    ProposalCadence,
    TargetChoice,
    choose_target,
)
from bot.ports.logging import BotLogger
from bot.world.attention import AttentionSnapshot
from bot.world.awareness import AwarenessSnapshot

from .assessment import ReaperHarassAssessor
from .model import (
    ReaperHarassAssessment,
    ReaperHarassConfig,
    ReaperHarassPlan,
    ReaperTargetAssessment,
)

COMPONENT = "behavior.harass.reaper"


@dataclass(slots=True)
class ReaperHarassPlanner:
    """Proposes a worker-line raid whenever a healthy Reaper is idle."""

    config: ReaperHarassConfig = field(default_factory=ReaperHarassConfig)
    logger: BotLogger | None = None
    planner_id: str = "reaper_harass_planner"
    # The candidate ranking is logged whenever the target changes, and at
    # least this often while it holds.
    target_log_interval: float = 30.0
    _assessor: ReaperHarassAssessor = field(init=False, repr=False)
    _log: BehaviorLog = field(init=False, repr=False)
    _cadence: ProposalCadence = field(
        default_factory=ProposalCadence, init=False, repr=False
    )
    # The base the last raid was launched at; the next raid's target has to
    # beat it by the margin.
    _target_key: str | None = field(default=None, init=False, repr=False)
    _target_logged_at: float = field(default=float("-inf"), init=False, repr=False)
    last_assessment: ReaperHarassAssessment | None = field(
        default=None, init=False, repr=False
    )
    last_plan: ReaperHarassPlan | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._assessor = ReaperHarassAssessor(config=self.config)
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
        plan = self._plan(assessment)
        self._log.assessed(
            assessment,
            now=now,
            decision="propose" if plan is not None else "withhold",
        )
        if plan is None:
            self.last_plan = None
            return ()

        self._cadence.mark(now)
        self.last_plan = plan
        self._log.proposed(plan, now=now, planner=self.planner_id)
        return (self._proposal_for(plan, now),)

    def _plan(self, assessment: ReaperHarassAssessment) -> ReaperHarassPlan | None:
        if assessment.workers < self.config.minimum_workers:
            return None
        if assessment.reapers_available < 1:
            return None

        # Light ground defense is tolerated by design -- a Reaper raid that
        # waits for an empty natural never launches at all. That tolerance
        # lives in `ReaperTargetHeuristics`: whatever it still reads as
        # viable is a candidate.
        choice = choose_target(
            assessment.viable_targets,
            current_key=self._target_key,
            margin=self.config.targeting.retarget_margin,
        )
        self._log_target(choice, assessment)
        target = choice.target
        self._target_key = None if target is None else target.key
        if target is None:
            return None
        return ReaperHarassPlan(
            target=target,
            priority=self.config.priority,
            reason="best_ranked_reaper_target",
            readiness=assessment.readiness,
        )

    def _log_target(
        self,
        choice: TargetChoice[ReaperTargetAssessment],
        assessment: ReaperHarassAssessment,
    ) -> None:
        now = assessment.now
        if (
            not choice.change.changed
            and now - self._target_logged_at < self.target_log_interval
        ):
            return
        self._target_logged_at = now
        self._log.event(
            "behavior.target_selection",
            now=now,
            change=choice.change.name,
            selected=None if choice.target is None else choice.target.key,
            previous=choice.previous_key,
            candidates=[target.summary() for target in assessment.targets],
        )

    def _proposal_for(self, plan: ReaperHarassPlan, now: float) -> MissionProposal:
        sequence = self._cadence.next_sequence()
        prefix = self.config.mission_kind.name.lower()
        target = plan.target
        return MissionProposal(
            proposal_id=f"{self.planner_id}:{prefix}:{target.key}:{sequence}",
            deduplication_key=f"{prefix}:{target.key}",
            planner=self.planner_id,
            kind=self.config.mission_kind,
            priority=plan.priority,
            target_key=target.key,
            target=target.position,
            reason=plan.reason,
            requirement=UnitRequirement.combat(
                unit_types=self.config.unit_types,
                desired=1,
                minimum=1,
                minimum_health=self.config.minimum_unit_health,
            ),
            created_at=now,
            evidence_last_observed_at=target.last_observed_at,
            evidence_age=target.age,
            evidence_stale_after=target.stale_after,
            timeout_seconds=self.config.mission_timeout,
            cooldown_seconds=self.config.failure_cooldown,
            # Standing missions hold most otherwise idle combat units, so the
            # raid must be able to preempt one just to get a Reaper at all.
            can_preempt=True,
            commitment_seconds=self.config.commitment_seconds,
        )
