from __future__ import annotations

from dataclasses import dataclass, field

from sc2.position import Point2

from bot.behavior.harass.config import HarassOption, HarassPlannerConfig
from bot.engine.missions.models import MissionProposal, UnitRequirement
from bot.engine.missions.planning import ProposalCadence
from bot.world.knowledge.enemy.models import EnemyLocationKnowledge
from bot.world.knowledge.models import AwarenessSnapshot
from bot.world.observation.models import AttentionSnapshot, UnitSnapshot


@dataclass(slots=True)
class HarassPlanner:
    """Calls whichever configured harass raid (Reaper, cloaked Banshee, ...)
    currently has a launchable unit and a known, safe-enough target.

    Each `HarassOption` in `config.options` is gated and rate-limited
    independently (its own cadence and sequence numbers), so more than one
    can be live at once -- e.g. a Reaper harassing while a Banshee raid is
    also in flight, each with its own `MissionKind` and dedup key.
    """

    config: HarassPlannerConfig = field(default_factory=HarassPlannerConfig)
    planner_id: str = "harass_planner"
    _cadences: dict[str, ProposalCadence] = field(
        default_factory=dict, init=False, repr=False
    )

    def propose(
        self,
        attention: AttentionSnapshot,
        awareness: AwarenessSnapshot,
    ) -> tuple[MissionProposal, ...]:
        world = attention.world
        location = awareness.enemy.location(self.config.target_key)
        if location is None or location.last_observed_at is None:
            return ()
        workers = sum(unit.is_worker for unit in world.own_units)

        proposals: list[MissionProposal] = []
        for option in self.config.options:
            cadence = self._cadences.setdefault(option.name, ProposalCadence())
            if not cadence.ready(world.time, option.proposal_cadence):
                continue
            if workers < option.minimum_workers:
                continue
            if not self._has_launchable_unit(option, world.own_units):
                continue
            if not self._is_target_safe(option, world.enemy_units, location.position):
                continue

            cadence.mark(world.time)
            sequence = cadence.next_sequence()
            proposals.append(
                self._build_proposal(option, location, sequence, world.time)
            )
        return tuple(proposals)

    @staticmethod
    def _has_launchable_unit(
        option: HarassOption, own_units: tuple[UnitSnapshot, ...]
    ) -> bool:
        if not option.require_ready_unit:
            return any(unit.unit_type in option.unit_types for unit in own_units)
        return any(
            unit.unit_type in option.unit_types
            and unit.available_for_mission
            and unit.is_ready
            and unit.health_percentage >= option.minimum_unit_health
            for unit in own_units
        )

    @staticmethod
    def _is_target_safe(
        option: HarassOption,
        enemy_units: tuple[UnitSnapshot, ...],
        position: Point2,
    ) -> bool:
        if option.anti_air_check_radius is None:
            return True
        return not any(
            unit.visible_now
            and unit.can_attack_air
            and unit.position.distance_to(position) <= option.anti_air_check_radius
            for unit in enemy_units
        )

    def _build_proposal(
        self,
        option: HarassOption,
        location: EnemyLocationKnowledge,
        sequence: int,
        now: float,
    ) -> MissionProposal:
        prefix = option.mission_kind.name.lower()
        return MissionProposal(
            proposal_id=(
                f"{self.planner_id}:{prefix}:{self.config.target_key}:{sequence}"
            ),
            deduplication_key=f"{prefix}:{self.config.target_key}",
            planner=self.planner_id,
            kind=option.mission_kind,
            priority=option.priority,
            target_key=self.config.target_key,
            target=location.position,
            reason=option.reason,
            requirement=UnitRequirement.combat(
                unit_types=option.unit_types,
                desired=1,
                minimum=1,
                minimum_health=option.minimum_unit_health,
            ),
            created_at=now,
            evidence_last_observed_at=location.last_observed_at,
            evidence_age=location.age,
            evidence_stale_after=location.stale_after,
            timeout_seconds=option.mission_timeout,
            cooldown_seconds=option.failure_cooldown,
            can_preempt=False,
            commitment_seconds=option.commitment_seconds,
        )
