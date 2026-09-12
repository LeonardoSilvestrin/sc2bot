"""PLAN: given the assessment, should we raid, where, and how badly?

The planner owns the strategic loop for this behavior. It runs on its own
slow cadence, produces at most one `MissionProposal`, and never touches a
unit: `MissionController` decides whether the proposal becomes a mission and
`UnitAllocator` decides which Banshees serve it.

The raid is a `MissionMode.STANDING` responsibility rather than a one-shot
job, because every Banshee produced afterwards should join it. Its
deduplication key names the squad, not the target, so re-proposing updates
the live mission in place: its desired count, and its target whenever the
planner retargets. The assessment ranks every enemy base; the planner holds
on to the one it chose until another is clearly better
(`BansheeTargetHeuristics.retarget_margin`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.behavior.contracts import BehaviorLog
from bot.behavior.strategy_intent import BuildStrategicIntent, StrategicIntent
from bot.engine.missions.models import MissionMode, MissionProposal, UnitRequirement
from bot.engine.missions.planning import (
    ProposalCadence,
    TargetChoice,
    choose_target,
)
from bot.ports.logging import BotLogger
from bot.world.attention import AttentionSnapshot
from bot.world.awareness import AwarenessSnapshot

from .assessment import BansheeHarassAssessor
from .model import (
    BansheeHarassAssessment,
    BansheeHarassConfig,
    BansheeHarassPlan,
    BansheeTargetAssessment,
)

COMPONENT = "behavior.harass.banshee"


@dataclass(slots=True)
class BansheeHarassPlanner:
    """Decides whether the cloaked Banshee raid should be running, and where."""

    config: BansheeHarassConfig = field(default_factory=BansheeHarassConfig)
    strategic_intent: StrategicIntent = field(default_factory=BuildStrategicIntent)
    logger: BotLogger | None = None
    planner_id: str = "banshee_harass_planner"
    # The candidate ranking is logged whenever the target changes, and at
    # least this often while it holds.
    target_log_interval: float = 30.0
    _assessor: BansheeHarassAssessor = field(init=False, repr=False)
    _log: BehaviorLog = field(init=False, repr=False)
    _cadence: ProposalCadence = field(
        default_factory=ProposalCadence, init=False, repr=False
    )
    # Once the raid has launched, a defender arriving at the target is the
    # in-flight executor's problem (it disengages), not a reason for the
    # planner to stop re-declaring the standing squad and strand every
    # Banshee it owns.
    _activated: bool = field(default=False, init=False, repr=False)
    # The target the raid was last declared against; a retarget has to beat
    # it by the margin.
    _target_key: str | None = field(default=None, init=False, repr=False)
    _target_logged_at: float = field(default=float("-inf"), init=False, repr=False)
    last_assessment: BansheeHarassAssessment | None = field(
        default=None, init=False, repr=False
    )
    last_plan: BansheeHarassPlan | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._assessor = BansheeHarassAssessor(
            config=self.config, strategic_intent=self.strategic_intent
        )
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
        self._activated = True
        self.last_plan = plan
        self._log.proposed(plan, now=now, planner=self.planner_id)
        return (self._proposal_for(plan, now),)

    def _plan(
        self, assessment: BansheeHarassAssessment
    ) -> BansheeHarassPlan | None:
        """The launch decision, as a sequence of explicit, readable gates.

        The target comes last: it is only chosen, held and logged once every
        other gate lets the raid run, so the log never shows a target picked
        for a raid that was not proposed.
        """

        if assessment.workers < self.config.minimum_workers:
            return None
        if not assessment.build_supports_harass:
            return None
        if not assessment.has_banshees:
            return None

        choice = self._choose_target(assessment)
        self._log_target(choice, assessment)
        target = choice.target
        self._target_key = None if target is None else target.key
        if target is None:
            return None

        return BansheeHarassPlan(
            target=target,
            # The squad must keep pulling in every Banshee produced, not just
            # the one that triggered the first proposal -- otherwise freshly
            # built Banshees sit idle instead of joining the raid.
            desired_banshees=max(1, assessment.banshees_alive),
            priority=self.config.priority,
            reason=(
                "best_ranked_banshee_target"
                if target.viable
                else "raid_live_without_a_viable_target"
            ),
            readiness=assessment.readiness,
            risk=max(target.air_defense_risk, target.army_risk),
        )

    def _choose_target(
        self, assessment: BansheeHarassAssessment
    ) -> TargetChoice[BansheeTargetAssessment]:
        """The best viable target, held until another is clearly better.

        Only a viable target launches the raid. Once it is live, though,
        running out of viable targets must not stop the standing squad from
        being re-declared (see `_activated`), so the best of what remains is
        chosen instead.
        """

        candidates = assessment.viable_targets
        if not candidates and self._activated:
            candidates = assessment.targets
        return choose_target(
            candidates,
            current_key=self._target_key,
            margin=self.config.targeting.retarget_margin,
        )

    def _log_target(
        self,
        choice: TargetChoice[BansheeTargetAssessment],
        assessment: BansheeHarassAssessment,
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

    def _proposal_for(self, plan: BansheeHarassPlan, now: float) -> MissionProposal:
        sequence = self._cadence.next_sequence()
        prefix = self.config.mission_kind.name.lower()
        target = plan.target
        return MissionProposal(
            proposal_id=f"{self.planner_id}:{prefix}:{target.key}:{sequence}",
            # Keyed by squad, not target: a retarget re-declares the same live
            # mission rather than replacing it -- and the squad keeps its one
            # home mission key for life.
            deduplication_key=f"{prefix}:{self.config.squad_id}",
            planner=self.planner_id,
            kind=self.config.mission_kind,
            priority=plan.priority,
            target_key=target.key,
            target=target.position,
            reason=plan.reason,
            requirement=UnitRequirement.combat(
                unit_types=self.config.unit_types,
                desired=plan.desired_banshees,
                # A standing squad holding zero units is idle, not failed.
                minimum=0,
                minimum_health=self.config.minimum_unit_health,
            ),
            created_at=now,
            evidence_last_observed_at=target.last_observed_at,
            evidence_age=target.age,
            evidence_stale_after=target.stale_after,
            timeout_seconds=self.config.mission_timeout,
            cooldown_seconds=self.config.failure_cooldown,
            # Standing missions hold most otherwise idle combat units, so the
            # raid must be able to preempt them. DEFENSE still outranks it.
            can_preempt=True,
            commitment_seconds=self.config.commitment_seconds,
            mode=MissionMode.STANDING,
            squad_id=self.config.squad_id,
        )
