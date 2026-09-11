"""Types local to information gathering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.engine.missions.models import MissionKind
from bot.engine.services import VisionRequestResult, VisionUrgency


@dataclass(frozen=True, slots=True)
class IntelConfig:
    """When information is worth a unit, and which unit is worth spending."""

    target_key: str = "enemy_main"
    location_stale_after: float = 90.0
    minimum_workers: int = 16
    repeat_scouts_after: float = 240.0
    proposal_cadence: float = 65.0
    priority: int = 65
    mission_timeout: float = 105.0
    failure_cooldown: float = 18.0
    unit_types: frozenset[UnitTypeId] = field(
        default_factory=lambda: frozenset({UnitTypeId.REAPER})
    )
    fallback_unit_types: frozenset[UnitTypeId] = field(
        default_factory=lambda: frozenset({UnitTypeId.SCV})
    )
    minimum_unit_health: float = 0.70

    # --- tactics ----------------------------------------------------------
    arrival_radius: float = 4.0
    observation_radius: float = 10.0

    mission_kind: MissionKind = MissionKind.SCOUT

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
        if not self.unit_types:
            raise ValueError("unit_types must not be empty")
        if not 0.0 <= self.minimum_unit_health <= 1.0:
            raise ValueError("minimum_unit_health must be between 0 and 1")
        if self.arrival_radius <= 0.0 or self.observation_radius <= 0.0:
            raise ValueError("arrival and observation radii must be positive")


@dataclass(frozen=True, slots=True)
class ScoutTarget:
    """The location this behavior currently wants looked at.

    `key` may not be the configured one: on synthetic or unusual maps the
    enemy main has no extractable perimeter route, and the natural is used
    instead. Resolving that is assessment's job, so the planner and the
    executor both see one already-decided target.
    """

    key: str
    position: Point2
    last_observed_at: float | None
    age: float | None
    stale_after: float
    is_stale: bool
    has_route: bool

    @property
    def never_seen(self) -> bool:
        return self.last_observed_at is None


@dataclass(frozen=True, slots=True)
class IntelAssessment:
    """What we do and do not know, and what we could send to find out."""

    now: float
    target: ScoutTarget | None
    workers: int
    scout_unit_types: frozenset[UnitTypeId]
    preferred_scout_alive: bool

    def log_fields(self) -> dict[str, Any]:
        return {
            "target": None if self.target is None else self.target.key,
            "stale": None if self.target is None else self.target.is_stale,
            "never_seen": None if self.target is None else self.target.never_seen,
            "workers": self.workers,
            "scout_types": sorted(item.name for item in self.scout_unit_types),
            "preferred_scout_alive": self.preferred_scout_alive,
        }


@dataclass(frozen=True, slots=True)
class ScoutPlan:
    """Send one unit of these types to look at this place."""

    target: ScoutTarget
    unit_types: frozenset[UnitTypeId]
    priority: int
    reason: str

    def log_fields(self) -> dict[str, Any]:
        return {
            "target": self.target.key,
            "unit_types": sorted(item.name for item in self.unit_types),
            "priority": self.priority,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ScoutingVisionConfig:
    """When stale scouting information becomes an active-vision need."""

    target_key: str = "enemy_main"
    max_without_vision: float = 120.0
    request_cadence: float = 5.0
    request_ttl: float = 12.0
    urgency: VisionUrgency = VisionUrgency.NORMAL

    def __post_init__(self) -> None:
        if not self.target_key.strip():
            raise ValueError("target_key must not be empty")
        if min(
            self.max_without_vision, self.request_cadence, self.request_ttl
        ) <= 0.0:
            raise ValueError("vision age, cadence and ttl must be positive")


@dataclass(frozen=True, slots=True)
class ScoutingVisionAssessment:
    now: float
    target: Point2 | None
    visible_now: bool
    last_observed_at: float | None
    seconds_without_vision: float

    def log_fields(self) -> dict[str, Any]:
        return {
            "target": None if self.target is None else [self.target.x, self.target.y],
            "visible_now": self.visible_now,
            "last_observed_at": self.last_observed_at,
            "seconds_without_vision": self.seconds_without_vision,
        }


@dataclass(frozen=True, slots=True)
class ScoutingVisionPlan:
    target: Point2
    urgency: VisionUrgency
    requester: str
    reason: str
    ttl: float

    def log_fields(self) -> dict[str, Any]:
        return {
            "target": [self.target.x, self.target.y],
            "urgency": self.urgency.name,
            "requester": self.requester,
            "reason": self.reason,
            "ttl": self.ttl,
        }


@dataclass(frozen=True, slots=True)
class ScoutingVisionDecision:
    plan: ScoutingVisionPlan
    result: VisionRequestResult
