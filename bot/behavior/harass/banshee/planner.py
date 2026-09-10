"""PLAN: given the assessment, should we raid, where, and how badly?

The planner owns the strategic loop for this behavior. It runs on its own
slow cadence, produces at most one `MissionProposal`, and never touches a
unit: `MissionController` decides whether the proposal becomes a mission and
`UnitAllocator` decides which Banshees serve it.

The raid is a `MissionMode.STANDING` responsibility rather than a one-shot
job, because every Banshee produced afterwards should join it. Re-proposing
the same key updates the live mission's desired count in place.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.behavior.contracts import BehaviorLog
from bot.behavior.strategy_intent import BuildStrategicIntent, StrategicIntent
from bot.engine.missions.models import MissionMode, MissionProposal, UnitRequirement
from bot.engine.missions.planning import ProposalCadence
from bot.ports.logging import BotLogger
from bot.world.attention import AttentionSnapshot
from bot.world.awareness import AwarenessSnapshot

from .assessment import BansheeHarassAssessor
from .model import BansheeHarassAssessment, BansheeHarassConfig, BansheeHarassPlan

COMPONENT = "behavior.harass.banshee"


@dataclass(slots=True)
class BansheeHarassPlanner:
    """Decides whether the cloaked Banshee raid should be running."""

    config: BansheeHarassConfig = field(default_factory=BansheeHarassConfig)
    strategic_intent: StrategicIntent = field(default_factory=BuildStrategicIntent)
    logger: BotLogger | None = None
    planner_id: str = "banshee_harass_planner"
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

        Order matters only for which reason gets logged; the outcome is the
        conjunction of all of them.
        """

        target = assessment.preferred_target
        if target is None:
            return None
        if assessment.workers < self.config.minimum_workers:
            return None
        if not assessment.build_supports_harass:
            return None
        if not assessment.has_banshees:
            return None
        # Only the *initial* launch withholds on a defended target.
        if not self._activated and target.is_defended:
            return None

        return BansheeHarassPlan(
            target=target,
            # The squad must keep pulling in every Banshee produced, not just
            # the one that triggered the first proposal -- otherwise freshly
            # built Banshees sit idle instead of joining the raid.
            desired_banshees=max(1, assessment.banshees_alive),
            priority=self.config.priority,
            reason="enemy_worker_line_known_and_no_visible_anti_air",
            readiness=assessment.readiness,
            risk=assessment.risk,
        )

    def _proposal_for(self, plan: BansheeHarassPlan, now: float) -> MissionProposal:
        sequence = self._cadence.next_sequence()
        prefix = self.config.mission_kind.name.lower()
        key = f"{prefix}:{plan.target.key}"
        return MissionProposal(
            proposal_id=f"{self.planner_id}:{prefix}:{plan.target.key}:{sequence}",
            deduplication_key=key,
            planner=self.planner_id,
            kind=self.config.mission_kind,
            priority=plan.priority,
            target_key=plan.target.key,
            target=plan.target.position,
            reason=plan.reason,
            requirement=UnitRequirement.combat(
                unit_types=self.config.unit_types,
                desired=plan.desired_banshees,
                # A standing squad holding zero units is idle, not failed.
                minimum=0,
                minimum_health=self.config.minimum_unit_health,
            ),
            created_at=now,
            evidence_last_observed_at=plan.target.last_observed_at,
            evidence_age=plan.target.age,
            evidence_stale_after=plan.target.stale_after,
            timeout_seconds=self.config.mission_timeout,
            cooldown_seconds=self.config.failure_cooldown,
            # Standing missions hold most otherwise idle combat units, so the
            # raid must be able to preempt them. DEFENSE still outranks it.
            can_preempt=True,
            commitment_seconds=self.config.commitment_seconds,
            mode=MissionMode.STANDING,
            squad_id=self.config.squad_id,
        )
