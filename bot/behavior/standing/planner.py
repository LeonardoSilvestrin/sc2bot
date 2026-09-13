"""PLAN: where does the heart of the army sit when nothing needs it?

This is the default behavior. Every combat unit no more specific mission has
claimed should end up owned by this one, so that no unit is ever commanded
by two behaviors at once and none is left ownerless. It proposes a
``MissionMode.STANDING`` responsibility: re-proposing the same key updates
the live mission's anchor and desired count in place (see
``MissionController._update_standing``) rather than tearing the mission down
and rebuilding it, so a posture change reshapes the army without churning
leases.

It asks for no role and scores nothing: it claims every combat unit
(``UnitRequirement.any_combat_unit``), so a surviving Marine, a new Cyclone
and a Thor all rest here until something with a real job takes them. Nor is
it an opportunity: its candidate carries fallback signals, which the Mission
Policy ranks at a fixed floor beneath every real one.

Where the army waits follows Strategy: on the way into the home base
Strategy most wants protected. It is still not a defense -- it answers
"where do uncommitted units naturally live", not "how do we beat this
attack".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sc2.position import Point2

from bot.behavior.contracts import UNRANKED_PRIORITY, BehaviorLog, MissionCandidate
from bot.engine.missions.models import MissionMode, MissionProposal, UnitRequirement
from bot.engine.missions.planning import ProposalCadence
from bot.ports.logging import BotLogger
from bot.strategy import (
    ControlObjective,
    ControlTargetKind,
    MissionSignals,
    SpatialStrategySnapshot,
    StrategicContext,
)
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
    # The base objective the army supports and the passage it holds, kept
    # until another is clearly more important.
    _supported_base: str | None = field(default=None, init=False, repr=False)
    _held_passage: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._assessor = StandingAssessor(config=self.config)
        self._log = BehaviorLog(component=COMPONENT, logger=self.logger)

    def propose(
        self,
        attention: AttentionSnapshot,
        awareness: AwarenessSnapshot,
        strategy: StrategicContext | None = None,
    ) -> tuple[MissionCandidate, ...]:
        now = attention.world.time
        if not self._cadence.ready(now, self.config.proposal_cadence):
            return ()
        self._cadence.mark(now)

        assessment = self._assessor.assess(attention, awareness)
        previous_posture = self.last_posture
        self.last_assessment = assessment
        self.last_posture = assessment.posture

        plan = self._plan(assessment, (strategy or StrategicContext.neutral()).spatial)
        self._log_plan_change(plan, assessment, previous_posture=previous_posture)
        self.last_plan = plan
        return (self._candidate_for(plan, now),)

    def _plan(
        self, assessment: StandingAssessment, spatial: SpatialStrategySnapshot
    ) -> StandingPlan:
        """Choose the anchor; the core army asks for every combat unit.

        Asking for all of them, rather than a share, is what makes this the
        fallback owner. The Mission Policy ranks every real opportunity (map
        control, defense, harass) at least the allocator's preemption margin
        above this one, so each still takes what it needs and this can never
        take those units back -- it only holds whatever nobody else does. A
        fixed share left the remainder ownerless whenever map control was not
        running to claim it.
        """

        supported = self._supported(spatial)
        # `UnitRequirement` needs desired > 0; with no army yet the claim
        # simply idles (minimum=0).
        core_count = max(1, assessment.combat_units)
        if supported is None:
            self._supported_base = self._held_passage = None
            anchor, reason = self._fallback_anchor(assessment)
            return StandingPlan(
                anchor=anchor, anchor_reason=reason, core_count=core_count
            )
        base, passage = supported
        self._supported_base = base.objective_id
        self._held_passage = passage.objective_id
        return StandingPlan(
            anchor=_inside(
                passage.position, base.position, self.config.home_anchor_standoff
            ),
            anchor_reason="holds_home_passage_objective",
            core_count=core_count,
            objective_id=passage.objective_id,
            supports=base.objective_id,
        )

    def _supported(
        self, spatial: SpatialStrategySnapshot
    ) -> tuple[ControlObjective, ControlObjective] | None:
        """The home base Strategy most wants protected, and its way in.

        Only bases with a passage Strategy wants held qualify: the army waits
        just inside that passage rather than on top of the townhall. Both
        choices hold until a rival is more important by
        ``anchor_retarget_margin``; importance never reads our own hold, so
        the army arriving does not argue it away.
        """

        bases = tuple(
            base
            for base in spatial.of_kind(ControlTargetKind.BASE)
            if spatial.protecting(base.objective_id)
        )
        if not bases:
            return None
        base = self._keep(bases, self._supported_base)
        held_passage = (
            self._held_passage if base.objective_id == self._supported_base else None
        )
        passage = self._keep(spatial.protecting(base.objective_id), held_passage)
        return base, passage

    def _keep(
        self, options: tuple[ControlObjective, ...], held_id: str | None
    ) -> ControlObjective:
        best = min(options, key=lambda item: (-item.importance, item.objective_id))
        held = next((item for item in options if item.objective_id == held_id), None)
        if (
            held is not None
            and best.importance - held.importance <= self.config.anchor_retarget_margin
        ):
            return held
        return best

    def _fallback_anchor(self, assessment: StandingAssessment) -> tuple[Point2, str]:
        """No spatial objective to support (no region graph yet): the old
        heuristic, most of the way from the previous base toward the newest."""

        newest = assessment.newest_base
        previous = assessment.previous_base
        if newest is None:
            return assessment.own_start, "fallback_no_held_base_yet"
        if previous is None:
            return newest, "fallback_single_base_held"
        fraction = self.config.anchor_fraction_to_newest_base
        return (
            Point2(
                (
                    previous.x + (newest.x - previous.x) * fraction,
                    previous.y + (newest.y - previous.y) * fraction,
                )
            ),
            "fallback_between_previous_and_newest_base",
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

    def _candidate_for(self, plan: StandingPlan, now: float) -> MissionCandidate:
        sequence = self._cadence.next_sequence()
        return MissionCandidate(
            draft=MissionProposal(
                proposal_id=f"{self.planner_id}:{SQUAD_ID}:{sequence}",
                deduplication_key=DEDUPLICATION_KEY,
                planner=self.planner_id,
                kind=MISSION_KIND,
                priority=UNRANKED_PRIORITY,
                target_key=DEDUPLICATION_KEY,
                target=plan.anchor,
                reason="main_army_holds_latest_expansion_rally",
                requirement=UnitRequirement.any_combat_unit(
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
            ),
            signals=MissionSignals.fallback(plan.anchor_reason),
        )


def _inside(passage: Point2, base: Point2, standoff: float) -> Point2:
    """``standoff`` from the passage toward the base, never past the base."""

    distance = passage.distance_to(base)
    if distance <= 0.0:
        return passage
    return passage.towards(base, min(standoff, distance))
