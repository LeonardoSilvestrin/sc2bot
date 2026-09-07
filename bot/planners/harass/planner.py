from __future__ import annotations

from dataclasses import dataclass, field

from sc2.ids.unit_typeid import UnitTypeId

from bot.attention.models import AttentionSnapshot
from bot.awareness.models import AwarenessSnapshot
from bot.contracts.allocation import UnitRequirement
from bot.ego.models import MissionKind, MissionProposal


@dataclass(frozen=True, slots=True)
class HarassPlannerConfig:
    """Thresholds for the first worker-line harass vertical slice."""

    target_key: str = "enemy_natural"
    minimum_workers: int = 16
    proposal_cadence: float = 45.0
    priority: int = 60
    mission_timeout: float = 60.0
    failure_cooldown: float = 30.0
    unit_types: frozenset[UnitTypeId] = field(
        default_factory=lambda: frozenset({UnitTypeId.REAPER})
    )
    minimum_unit_health: float = 0.5
    commitment_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not self.target_key.strip():
            raise ValueError("target_key must not be empty")
        if self.proposal_cadence <= 0.0:
            raise ValueError("proposal_cadence must be positive")
        if self.minimum_workers < 1:
            raise ValueError("minimum_workers must be at least 1")
        if not 0 <= self.priority <= 100 or self.mission_timeout <= 0.0:
            raise ValueError("invalid priority or mission timeout")
        if self.failure_cooldown < 0.0:
            raise ValueError("failure_cooldown must not be negative")
        if not self.unit_types:
            raise ValueError("unit_types must not be empty")
        if not 0.0 <= self.minimum_unit_health <= 1.0:
            raise ValueError("minimum_unit_health must be between 0 and 1")
        if self.commitment_seconds < 0.0:
            raise ValueError("commitment_seconds must not be negative")


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
