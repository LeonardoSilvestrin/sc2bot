from __future__ import annotations

from dataclasses import dataclass, field

from sc2.ids.unit_typeid import UnitTypeId

from bot.attention.models import AttentionSnapshot
from bot.awareness.models import AwarenessSnapshot
from bot.contracts.allocation import UnitRequirement
from bot.ego.models import MissionKind, MissionProposal


@dataclass(frozen=True, slots=True)
class IntelPlannerConfig:
    target_key: str = "enemy_natural"
    location_stale_after: float = 90.0
    minimum_workers: int = 16
    repeat_scouts_after: float = 240.0
    proposal_cadence: float = 65.0
    priority: int = 55
    mission_timeout: float = 70.0
    failure_cooldown: float = 18.0
    minimum_worker_health: float = 0.70

    def __post_init__(self) -> None:
        if not self.target_key.strip():
            raise ValueError("target_key must not be empty")
        if self.location_stale_after <= 0.0 or self.proposal_cadence <= 0.0:
            raise ValueError("freshness and cadence must be positive")
        if self.minimum_workers < 1 or self.repeat_scouts_after < 0.0:
            raise ValueError("invalid economic scout gate")
        if not 0 <= self.priority <= 100 or self.mission_timeout <= 0.0:
            raise ValueError("invalid priority or mission timeout")
        if self.failure_cooldown < 0.0:
            raise ValueError("failure_cooldown must not be negative")
        if not 0.0 <= self.minimum_worker_health <= 1.0:
            raise ValueError("minimum_worker_health must be between 0 and 1")


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
                    unit_types=frozenset({UnitTypeId.SCV}),
                    desired=1,
                    minimum=1,
                    minimum_health=self.config.minimum_worker_health,
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
