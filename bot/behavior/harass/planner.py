from __future__ import annotations

from dataclasses import dataclass, field

from bot.behavior.harass.config import (
    BansheeHarassPlannerConfig,
    HarassPlannerConfig,
)
from bot.engine.missions.models import MissionKind, MissionProposal, UnitRequirement
from bot.engine.missions.planning import ProposalCadence
from bot.world.knowledge.models import AwarenessSnapshot
from bot.world.observation.models import AttentionSnapshot


@dataclass(slots=True)
class HarassPlanner:
    """Proposes worker-line pressure for a known base when a Reaper is free."""

    config: HarassPlannerConfig = field(default_factory=HarassPlannerConfig)
    planner_id: str = "harass_planner"
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

        location = awareness.enemy.location(self.config.target_key)
        if location is None or location.last_observed_at is None:
            return ()
        workers = sum(unit.is_worker for unit in world.own_units)
        if workers < self.config.minimum_workers:
            return ()
        if not any(
            unit.unit_type in self.config.unit_types
            and unit.available_for_mission
            and unit.is_ready
            and unit.health_percentage >= self.config.minimum_unit_health
            for unit in world.own_units
        ):
            return ()

        self._cadence.mark(world.time)
        sequence = self._cadence.next_sequence()
        return (
            MissionProposal(
                proposal_id=(
                    f"{self.planner_id}:harass:{self.config.target_key}:"
                    f"{sequence}"
                ),
                deduplication_key=f"harass:{self.config.target_key}",
                planner=self.planner_id,
                kind=MissionKind.HARASS,
                priority=self.config.priority,
                target_key=self.config.target_key,
                target=location.position,
                reason="enemy_worker_line_known_and_reaper_available",
                requirement=UnitRequirement.combat(
                    unit_types=self.config.unit_types,
                    desired=1,
                    minimum=1,
                    minimum_health=self.config.minimum_unit_health,
                ),
                created_at=world.time,
                evidence_last_observed_at=location.last_observed_at,
                evidence_age=location.age,
                evidence_stale_after=location.stale_after,
                timeout_seconds=self.config.mission_timeout,
                cooldown_seconds=self.config.failure_cooldown,
                can_preempt=False,
                commitment_seconds=self.config.commitment_seconds,
            ),
        )


@dataclass(slots=True)
class BansheeHarassPlanner:
    """Proposes one cloaked-Banshee raid once one is alive and the target
    worker line is known.

    Unlike ``HarassPlanner``'s ground Reaper, a flying Banshee cannot be
    threatened by a ground-only defender, so this withholds on a currently
    visible *anti-air* unit (``AwarenessSnapshot.threat.visible_anti_air_units``,
    already tracked for exactly this kind of air-safety judgement) rather
    than any enemy unit anywhere. It never checks cloak research directly --
    ``CloakedBansheeHarassExecutor`` casts cloak every step and the ability
    simply no-ops until the tech finishes, so the Banshee harasses visibly
    for a few seconds rather than waiting idle.
    """

    config: BansheeHarassPlannerConfig = field(
        default_factory=BansheeHarassPlannerConfig
    )
    planner_id: str = "banshee_harass_planner"
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

        location = awareness.enemy.location(self.config.target_key)
        if location is None or location.last_observed_at is None:
            return ()
        if awareness.threat.visible_anti_air_units > 0:
            return ()
        workers = sum(unit.is_worker for unit in world.own_units)
        if workers < self.config.minimum_workers:
            return ()
        if not any(
            unit.unit_type in self.config.unit_types for unit in world.own_units
        ):
            return ()

        self._cadence.mark(world.time)
        sequence = self._cadence.next_sequence()
        return (
            MissionProposal(
                proposal_id=(
                    f"{self.planner_id}:air_harass:{self.config.target_key}:"
                    f"{sequence}"
                ),
                deduplication_key=f"air_harass:{self.config.target_key}",
                planner=self.planner_id,
                kind=MissionKind.AIR_HARASS,
                priority=self.config.priority,
                target_key=self.config.target_key,
                target=location.position,
                reason="enemy_worker_line_known_and_no_visible_anti_air",
                requirement=UnitRequirement.combat(
                    unit_types=self.config.unit_types,
                    desired=1,
                    minimum=1,
                    minimum_health=self.config.minimum_unit_health,
                ),
                created_at=world.time,
                evidence_last_observed_at=location.last_observed_at,
                evidence_age=location.age,
                evidence_stale_after=location.stale_after,
                timeout_seconds=self.config.mission_timeout,
                cooldown_seconds=self.config.failure_cooldown,
                can_preempt=False,
                commitment_seconds=self.config.commitment_seconds,
            ),
        )
