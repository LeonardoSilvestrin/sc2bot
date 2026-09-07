from __future__ import annotations

import math
from dataclasses import dataclass, field

from bot.behavior.defense.config import DefensePlannerConfig
from bot.engine.missions.models import MissionKind, MissionProposal, UnitRequirement
from bot.engine.missions.planning import ProposalCadence
from bot.world.knowledge.bases.models import BaseAssessment, BaseSecurityLevel
from bot.world.knowledge.models import AwarenessSnapshot
from bot.world.observation.models import AttentionSnapshot


@dataclass(slots=True)
class DefensePlanner:
    """Proposes one defense mission per currently threatened base.

    Reads ``awareness.bases`` -- one ``BaseAssessment`` per base the bot
    currently holds, each already scoring nearby enemy threat against nearby
    own protection (see ``BaseSecurityAssessor``). A base only gets a
    proposal once its security drops to THREATENED or CRITICAL, so several
    bases under attack at the same time get independent missions instead of
    all competing for a single global "own_base" slot, and a base that
    already has enough defenders nearby does not pull reinforcements it
    doesn't need. Requested unit count grows with how outnumbered the base's
    current defenders are.
    """

    config: DefensePlannerConfig = field(default_factory=DefensePlannerConfig)
    planner_id: str = "defense_planner"
    _cadence: ProposalCadence = field(
        default_factory=ProposalCadence, init=False, repr=False
    )

    def propose(
        self,
        attention: AttentionSnapshot,
        awareness: AwarenessSnapshot,
    ) -> tuple[MissionProposal, ...]:
        world = attention.world
        if not self._cadence.ready(world.time, self.config.proposal_cadence):
            return ()

        threatened = awareness.bases.threatened
        if not threatened:
            return ()

        self._cadence.mark(world.time)
        return tuple(self._proposal_for(base, world.time) for base in threatened)

    def _proposal_for(self, base: BaseAssessment, now: float) -> MissionProposal:
        sequence = self._cadence.next_sequence()
        is_critical = base.security is BaseSecurityLevel.CRITICAL
        target = base.nearest_threat_position or base.position
        return MissionProposal(
            proposal_id=f"{self.planner_id}:defense:{base.base_id}:{sequence}",
            deduplication_key=f"defense:{base.base_id}",
            planner=self.planner_id,
            kind=MissionKind.DEFENSE,
            priority=(
                self.config.critical_priority
                if is_critical
                else self.config.threatened_priority
            ),
            target_key=base.base_id,
            target=target,
            reason=(
                "base_undefended_against_observed_threat"
                if is_critical
                else "base_outnumbered_by_observed_threat"
            ),
            requirement=UnitRequirement.combat(
                unit_types=self.config.unit_types,
                desired=self._desired_units(base),
                minimum=self.config.minimum_units,
                minimum_health=self.config.minimum_unit_health,
            ),
            created_at=now,
            timeout_seconds=self.config.mission_timeout,
            cooldown_seconds=self.config.failure_cooldown,
            can_preempt=True,
            commitment_seconds=self.config.commitment_seconds,
        )

    def _desired_units(self, base: BaseAssessment) -> int:
        gap = base.threat_score - base.protection_score
        desired = max(self.config.minimum_units, math.ceil(gap))
        return min(self.config.max_desired_units, desired)
