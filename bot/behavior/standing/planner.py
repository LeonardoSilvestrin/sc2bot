"""PLAN: where does the heart of the army sit when nothing needs it?

This is the default behavior. Every combat unit no special mission has
claimed should end up owned by this one, so that no unit is ever commanded
by two behaviors at once and none is left ownerless. It proposes a
``MissionMode.STANDING`` responsibility: re-proposing the same key updates
the live mission's anchor and desired count in place (see
``MissionController._update_standing``) rather than tearing the mission down
and rebuilding it, so a posture change reshapes the army without churning
leases.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from sc2.position import Point2

from bot.behavior.contracts import BehaviorLog
from bot.engine.missions.models import MissionMode, MissionProposal, UnitRequirement
from bot.engine.missions.planning import ProposalCadence
from bot.ports.logging import BotLogger
from bot.world.attention import AttentionSnapshot
from bot.world.awareness import AwarenessSnapshot

from .assessment import StandingAssessor
from .model import (
    DEDUPLICATION_KEY,
    MISSION_KIND,
    SQUAD_ID,
    CombatPosture,
    StandingAssessment,
    StandingConfig,
    StandingPlan,
)

COMPONENT = "behavior.standing"


@dataclass(slots=True)
class StandingPlanner:
    """Declares the persistent core-army responsibility and its anchor."""

    config: StandingConfig = field(default_factory=StandingConfig)
    logger: BotLogger | None = None
    planner_id: str = "standing_planner"
    _assessor: StandingAssessor = field(init=False, repr=False)
    _log: BehaviorLog = field(init=False, repr=False)
    _cadence: ProposalCadence = field(
        default_factory=ProposalCadence, init=False, repr=False
    )
    last_posture: CombatPosture = field(
        default=CombatPosture.BALANCED, init=False, repr=False
    )
    last_assessment: StandingAssessment | None = field(
        default=None, init=False, repr=False
    )
    last_plan: StandingPlan | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._assessor = StandingAssessor(config=self.config)
        self._log = BehaviorLog(component=COMPONENT, logger=self.logger)

    def propose(
        self,
        attention: AttentionSnapshot,
        awareness: AwarenessSnapshot,
    ) -> tuple[MissionProposal, ...]:
        now = attention.world.time
        if not self._cadence.ready(now, self.config.proposal_cadence):
            return ()
        self._cadence.mark(now)

        assessment = self._assessor.assess(attention, awareness)
        previous_posture = self.last_posture
        self.last_assessment = assessment
        self.last_posture = assessment.posture

        plan = self._plan(assessment)
        self._log_plan_change(plan, assessment, previous_posture=previous_posture)
        self.last_plan = plan
        return (self._proposal_for(plan, now),)

    def _plan(self, assessment: StandingAssessment) -> StandingPlan:
        """Choose the anchor and how much of the army holds it.

        Deliberately unsophisticated for now: the army sits most of the way
        from the previous base toward the newest one, which is where an
        attack arrives first. Posture does not move the anchor yet -- that
        is the obvious next step, and this shape is what makes it a one-line
        change instead of a restructure.
        """

        anchor, reason = self._anchor(assessment)
        return StandingPlan(
            anchor=anchor,
            anchor_reason=reason,
            core_count=max(
                1, math.floor(assessment.eligible_units * self.config.core_fraction)
            ),
            core_fraction=self.config.core_fraction,
            roaming_fraction=self.config.roaming_fraction,
            priority=self.config.priority,
        )

    def _anchor(self, assessment: StandingAssessment) -> tuple[Point2, str]:
        newest = assessment.newest_base
        previous = assessment.previous_base
        if newest is None:
            return assessment.own_start, "no_held_base_yet"
        if previous is None:
            return newest, "single_base_held"
        fraction = self.config.anchor_fraction_to_newest_base
        return (
            Point2(
                (
                    previous.x + (newest.x - previous.x) * fraction,
                    previous.y + (newest.y - previous.y) * fraction,
                )
            ),
            "between_previous_and_newest_base",
        )

    def _log_plan_change(
        self,
        plan: StandingPlan,
        assessment: StandingAssessment,
        *,
        previous_posture: CombatPosture,
    ) -> None:
        """Only speak up when the standing disposition actually moves.

        At a five-second cadence an unconditional line would bury the one
        thing worth reading: that the army's home just changed, and why.
        """

        previous = self.last_plan
        if previous is not None and (
            previous.anchor == plan.anchor
            and previous.core_count == plan.core_count
            and previous_posture is assessment.posture
        ):
            return
        self._log.assessed(assessment, now=assessment.now, decision="hold")
        self._log.proposed(
            plan,
            now=assessment.now,
            planner=self.planner_id,
            previous_anchor=(
                None
                if previous is None
                else [
                    round(float(previous.anchor.x), 1),
                    round(float(previous.anchor.y), 1),
                ]
            ),
        )

    def _proposal_for(self, plan: StandingPlan, now: float) -> MissionProposal:
        sequence = self._cadence.next_sequence()
        return MissionProposal(
            proposal_id=f"{self.planner_id}:{SQUAD_ID}:{sequence}",
            deduplication_key=DEDUPLICATION_KEY,
            planner=self.planner_id,
            kind=MISSION_KIND,
            priority=plan.priority,
            target_key=DEDUPLICATION_KEY,
            target=plan.anchor,
            reason="main_army_holds_latest_expansion_rally",
            requirement=UnitRequirement.combat(
                unit_types=self.config.unit_types,
                desired=plan.core_count,
                # Holding zero units is idle, not failed: everything above
                # this behavior may legitimately take the whole army.
                minimum=0,
                minimum_health=self.config.minimum_unit_health,
            ),
            created_at=now,
            timeout_seconds=self.config.mission_timeout,
            cooldown_seconds=self.config.cooldown_seconds,
            can_preempt=True,
            commitment_seconds=self.config.commitment_seconds,
            mode=MissionMode.STANDING,
            squad_id=SQUAD_ID,
        )
