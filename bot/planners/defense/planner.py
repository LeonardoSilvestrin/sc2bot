from __future__ import annotations

from dataclasses import dataclass, field

from sc2.ids.unit_typeid import UnitTypeId

from bot.attention.models import AttentionSnapshot, UnitSnapshot, WorldFacts
from bot.awareness.models import AwarenessSnapshot
from bot.contracts.allocation import UnitRequirement
from bot.ego.models import MissionKind, MissionProposal


@dataclass(frozen=True, slots=True)
class DefensePlannerConfig:
    """Thresholds for the first base-defense vertical slice."""

    target_key: str = "own_base"
    detection_radius: float = 25.0
    proposal_cadence: float = 5.0
    priority: int = 95
    mission_timeout: float = 120.0
    failure_cooldown: float = 10.0
    unit_types: frozenset[UnitTypeId] = field(
        default_factory=lambda: frozenset({UnitTypeId.MARINE, UnitTypeId.REAPER})
    )
    desired_units: int = 2
    minimum_units: int = 1
    minimum_unit_health: float = 0.3
    commitment_seconds: float = 3.0

    def __post_init__(self) -> None:
        if not self.target_key.strip():
            raise ValueError("target_key must not be empty")
        if self.detection_radius <= 0.0 or self.proposal_cadence <= 0.0:
            raise ValueError("detection_radius and proposal_cadence must be positive")
        if not 0 <= self.priority <= 100 or self.mission_timeout <= 0.0:
            raise ValueError("invalid priority or mission timeout")
        if self.failure_cooldown < 0.0:
            raise ValueError("failure_cooldown must not be negative")
        if not self.unit_types:
            raise ValueError("unit_types must not be empty")
        if self.minimum_units < 1 or self.minimum_units > self.desired_units:
            raise ValueError("expected 1 <= minimum_units <= desired_units")
        if not 0.0 <= self.minimum_unit_health <= 1.0:
            raise ValueError("minimum_unit_health must be between 0 and 1")
        if self.commitment_seconds < 0.0:
            raise ValueError("commitment_seconds must not be negative")


@dataclass(slots=True)
class DefensePlanner:
    """Proposes one base-defense mission while a combat threat is observed.

    Conservative on purpose: it only reacts to enemy units that are
    currently visible, not a worker, and able to attack, within
    ``detection_radius`` of an owned structure (or the starting location
    before any structure is tracked). It carries the highest default
    priority of the pilot planners so it can preempt lower-priority
    missions once ``UnitAllocator``'s preemption margin allows it.
    """

    config: DefensePlannerConfig = field(default_factory=DefensePlannerConfig)
    planner_id: str = "defense_planner"
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

        threat = self._closest_threat(world)
        if threat is None:
            return ()

        self._last_proposed_at = world.time
        self._sequence += 1
        return (
            MissionProposal(
                proposal_id=(
                    f"{self.planner_id}:defense:{self.config.target_key}:"
                    f"{self._sequence}"
                ),
                deduplication_key=f"defense:{self.config.target_key}",
                planner=self.planner_id,
                kind=MissionKind.DEFENSE,
                priority=self.config.priority,
                target_key=self.config.target_key,
                target=threat.position,
                reason="enemy_combat_unit_observed_near_own_base",
                requirement=UnitRequirement(
                    unit_types=self.config.unit_types,
                    desired=self.config.desired_units,
                    minimum=self.config.minimum_units,
                    minimum_health=self.config.minimum_unit_health,
                    exclude_resource_carriers=True,
                    exclude_constructors=True,
                ),
                created_at=world.time,
                timeout_seconds=self.config.mission_timeout,
                cooldown_seconds=self.config.failure_cooldown,
                can_preempt=True,
                commitment_seconds=self.config.commitment_seconds,
            ),
        )

    def _closest_threat(self, world: WorldFacts) -> UnitSnapshot | None:
        anchors = [structure.position for structure in world.own_structures]
        if not anchors:
            anchors = [world.map.own_start]

        closest: UnitSnapshot | None = None
        closest_distance: float | None = None
        for enemy in world.enemy_units:
            if not enemy.visible_now or enemy.is_worker:
                continue
            if not (enemy.can_attack_ground or enemy.can_attack_air):
                continue
            distance = min(enemy.position.distance_to(anchor) for anchor in anchors)
            if distance > self.config.detection_radius:
                continue
            if closest_distance is None or distance < closest_distance:
                closest = enemy
                closest_distance = distance
        return closest
