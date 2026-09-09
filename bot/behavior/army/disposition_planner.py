from __future__ import annotations

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
from bot.world.awareness.bases import BaseAssessment

from .combat_posture import CombatPosture, derive_combat_posture
from .disposition_config import DispositionPlannerConfig, PostureDesired

RESERVE_KEY = "position:reserve"


@dataclass(slots=True)
class DispositionPlanner:
    """Standing, low-priority proposals so every eligible combat unit has a
    home when nothing more urgent needs it.

    This planner never touches units, leases, or commands -- like every
    other planner it only emits ``MissionProposal``s and leaves admission
    and arbitration to ``MissionController``/``UnitAllocator``. Its
    proposals use ``MissionMode.STANDING``: re-proposing the same
    ``deduplication_key`` (e.g. ``position:third``) updates the live
    mission's requirement/priority in place instead of being rejected as a
    duplicate (see ``MissionController._update_standing``), so a posture
    change reshapes the standing disposition without destroying and
    recreating missions every tick.

    ``position:reserve`` is the catch-all: lowest priority, ``minimum=0``,
    a generous ``desired`` -- see ``DispositionPlannerConfig.reserve_capacity``
    -- so any eligible unit no other mission wants ends up leased there
    rather than left without a mission at all.
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
        profile = self.config.desired_by_posture[posture]

        proposals = list(
            self._position_proposals(world.map, awareness, profile, world.time)
        )
        proposals.append(self._reserve_proposal(world.map, world.time))
        return tuple(proposals)

    def _position_proposals(
        self,
        map_facts: MapFacts,
        awareness: AwarenessSnapshot,
        profile: PostureDesired,
        now: float,
    ) -> tuple[MissionProposal, ...]:
        main, natural, third = self._ranked_bases(map_facts, awareness)
        proposals: list[MissionProposal] = []
        if main is not None and profile.main > 0:
            proposals.append(
                self._slot_proposal(
                    "main", main.position, self.config.main_priority, profile.main, now
                )
            )
        if natural is not None and profile.natural > 0:
            proposals.append(
                self._slot_proposal(
                    "natural",
                    natural.position,
                    self.config.natural_priority,
                    profile.natural,
                    now,
                )
            )
        if third is not None and profile.third > 0:
            proposals.append(
                self._slot_proposal(
                    "third",
                    third.position,
                    self.config.third_priority,
                    profile.third,
                    now,
                )
            )
        if profile.forward > 0:
            proposals.append(
                self._slot_proposal(
                    "forward",
                    self._forward_anchor(map_facts),
                    self.config.forward_priority,
                    profile.forward,
                    now,
                )
            )
        return tuple(proposals)

    @staticmethod
    def _ranked_bases(
        map_facts: MapFacts, awareness: AwarenessSnapshot
    ) -> tuple[BaseAssessment | None, BaseAssessment | None, BaseAssessment | None]:
        """Main, then the two nearest held expansions (natural, then third).

        The project has no first-class "natural"/"third" concept -- only
        ``is_main`` and each held base's position (see
        ``bot.world.awareness.bases``). Ranking the remaining held bases by
        distance from ``own_start`` is a reasonable, data-derived stand-in:
        it names the closest expansion "natural" and the next "third"
        without hardcoding any map-specific coordinates. Bases beyond that
        are not given a named slot in this pilot -- their units still end
        up owned via ``position:reserve``.
        """

        bases = tuple(awareness.bases)
        main = next((base for base in bases if base.is_main), None)
        expansions = sorted(
            (base for base in bases if not base.is_main),
            key=lambda base: base.position.distance_to(map_facts.own_start),
        )
        natural = expansions[0] if expansions else None
        third = expansions[1] if len(expansions) > 1 else None
        return main, natural, third

    @staticmethod
    def _forward_anchor(map_facts: MapFacts) -> Point2:
        own = map_facts.own_start
        center = map_facts.center
        return Point2(
            (own.x + (center.x - own.x) * 0.5, own.y + (center.y - own.y) * 0.5)
        )

    def _slot_proposal(
        self, slot: str, target: Point2, priority: int, desired: int, now: float
    ) -> MissionProposal:
        key = f"position:{slot}"
        sequence = self._cadence.next_sequence()
        return MissionProposal(
            proposal_id=f"{self.planner_id}:{slot}:{sequence}",
            deduplication_key=key,
            planner=self.planner_id,
            kind=MissionKind.POSITION,
            priority=priority,
            target_key=key,
            target=target,
            reason=f"standing_disposition_{slot}",
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
        )

    def _reserve_proposal(self, map_facts: MapFacts, now: float) -> MissionProposal:
        sequence = self._cadence.next_sequence()
        return MissionProposal(
            proposal_id=f"{self.planner_id}:reserve:{sequence}",
            deduplication_key=RESERVE_KEY,
            planner=self.planner_id,
            kind=MissionKind.POSITION,
            priority=self.config.reserve_priority,
            target_key=RESERVE_KEY,
            target=map_facts.own_start,
            reason="standing_disposition_reserve_catch_all",
            requirement=UnitRequirement.combat(
                unit_types=self.config.unit_types,
                desired=self.config.reserve_capacity,
                minimum=0,
                minimum_health=self.config.minimum_unit_health,
            ),
            created_at=now,
            timeout_seconds=self.config.mission_timeout,
            cooldown_seconds=self.config.cooldown_seconds,
            # The catch-all never needs to preempt anything -- it is always
            # the lowest priority, so it can only ever receive free units.
            can_preempt=False,
            commitment_seconds=self.config.commitment_seconds,
            mode=MissionMode.STANDING,
        )
