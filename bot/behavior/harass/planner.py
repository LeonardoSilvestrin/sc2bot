from __future__ import annotations

from dataclasses import dataclass, field

from bot.behavior.harass.config import HarassPlannerConfig
from bot.engine.missions.models import MissionKind, MissionProposal, UnitRequirement
from bot.world.knowledge.models import AwarenessSnapshot
from bot.world.observation.models import AttentionSnapshot


@dataclass(slots=True)
class HarassPlanner:
    """Proposes one worker-line harass when it is known and looks undefended.

    Conservative on purpose: it only argues for harass once the target has
    been observed at least once (``IntelPlanner`` already owns discovering
    it) and while no enemy unit is currently visible anywhere, since this
    slice has no notion of a defended-but-unseen base.
    """

    config: HarassPlannerConfig = field(default_factory=HarassPlannerConfig)
    planner_id: str = "harass_planner"
    _last_proposed_at: float = field(default=-9999.0, init=False, repr=False)
    _sequence: int = field(default=0, init=False, repr=False)

    def propose(
        self,
        attention: AttentionSnapshot,
        awareness: AwarenessSnapshot,
    ) -> tuple[MissionProposal, ...]:
        world = attention.world
        if world.time - self._last_proposed_at < self.config.proposal_cadence:
            return ()

        location = awareness.enemy.location(self.config.target_key)
        if location is None or location.last_observed_at is None:
            return ()
        if awareness.threat.visible_enemy_units > 0:
            return ()
        workers = sum(unit.is_worker for unit in world.own_units)
        if workers < self.config.minimum_workers:
            return ()
        if not any(
            unit.unit_type in self.config.unit_types for unit in world.own_units
        ):
            return ()

        self._last_proposed_at = world.time
        self._sequence += 1
        return (
            MissionProposal(
                proposal_id=(
                    f"{self.planner_id}:harass:{self.config.target_key}:"
                    f"{self._sequence}"
                ),
                deduplication_key=f"harass:{self.config.target_key}",
                planner=self.planner_id,
                kind=MissionKind.HARASS,
                priority=self.config.priority,
                target_key=self.config.target_key,
                target=location.position,
                reason="enemy_worker_line_known_and_currently_undefended",
                requirement=UnitRequirement(
                    unit_types=self.config.unit_types,
                    desired=1,
                    minimum=1,
                    minimum_health=self.config.minimum_unit_health,
                    exclude_resource_carriers=True,
                    exclude_constructors=True,
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
