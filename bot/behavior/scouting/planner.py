from __future__ import annotations

from dataclasses import dataclass, field

from sc2.ids.unit_typeid import UnitTypeId

from bot.behavior.scouting.config import IntelPlannerConfig
from bot.engine.missions.models import MissionKind, MissionProposal, UnitRequirement
from bot.world.knowledge.models import AwarenessSnapshot
from bot.world.observation.models import AttentionSnapshot, WorldFacts


@dataclass(slots=True)
class IntelPlanner:
    """Proposes one scout when selected enemy information is unknown or stale."""

    config: IntelPlannerConfig = field(default_factory=IntelPlannerConfig)
    planner_id: str = "intel_planner"
    _last_proposed_at: float = field(default=-9999.0, init=False, repr=False)
    _sequence: int = field(default=0, init=False, repr=False)

    def propose(
        self,
        attention: AttentionSnapshot,
        awareness: AwarenessSnapshot,
    ) -> tuple[MissionProposal, ...]:
        world = attention.world
        location = awareness.enemy.location(self.config.target_key)
        if location is None or not location.is_stale:
            return ()
        workers = sum(unit.is_worker for unit in world.own_units)
        if workers < self.config.minimum_workers:
            return ()
        if (
            location.last_observed_at is not None
            and world.time < self.config.repeat_scouts_after
        ):
            return ()
        if world.time - self._last_proposed_at < self.config.proposal_cadence:
            return ()

        unit_types = self._select_unit_types(world)
        if not unit_types:
            return ()

        self._last_proposed_at = world.time
        self._sequence += 1
        reason = (
            f"{self.config.target_key}_information_unknown"
            if location.last_observed_at is None
            else f"{self.config.target_key}_information_stale"
        )
        return (
            MissionProposal(
                proposal_id=f"{self.planner_id}:scout:{self.config.target_key}:{self._sequence}",
                deduplication_key=f"scout:{self.config.target_key}",
                planner=self.planner_id,
                kind=MissionKind.SCOUT,
                priority=self.config.priority,
                target_key=self.config.target_key,
                target=location.position,
                reason=reason,
                requirement=UnitRequirement(
                    unit_types=unit_types,
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
                commitment_seconds=5.0,
            ),
        )

    def _select_unit_types(self, world: WorldFacts) -> frozenset[UnitTypeId]:
        """Prefer the configured scout unit; fall back only once none is alive."""

        preferred_alive = any(
            unit.unit_type in self.config.unit_types for unit in world.own_units
        )
        if preferred_alive:
            return self.config.unit_types
        return self.config.fallback_unit_types
