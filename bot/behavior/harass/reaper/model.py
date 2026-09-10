"""Types local to Reaper worker-line harass."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.engine.missions.models import MissionKind


@dataclass(frozen=True, slots=True)
class ReaperHarassConfig:
    """Tuning for the single-Reaper raid on a worker line.

    Unlike the Banshee squad, this raid only ever has one or two precious
    Reapers, so it withholds unless one is genuinely idle and healthy right
    now -- never stealing the Reaper mid-scout to propose a raid that would
    just get preempted.
    """

    target_keys: tuple[str, ...] = ("enemy_natural",)
    unit_types: frozenset[UnitTypeId] = field(
        default_factory=lambda: frozenset({UnitTypeId.REAPER})
    )
    minimum_workers: int = 16
    proposal_cadence: float = 45.0
    priority: int = 60
    mission_timeout: float = 60.0
    failure_cooldown: float = 30.0
    minimum_unit_health: float = 0.5
    commitment_seconds: float = 5.0

    # --- tactics ----------------------------------------------------------
    worker_search_radius: float = 16.0
    arrival_radius: float = 3.0
    retreat_health: float = 0.40
    retreat_arrival_radius: float = 10.0

    mission_kind: MissionKind = MissionKind.HARASS

    def __post_init__(self) -> None:
        if not self.target_keys or any(not key.strip() for key in self.target_keys):
            raise ValueError("target_keys must not be empty or blank")
        if not self.unit_types:
            raise ValueError("unit_types must not be empty")
        if self.minimum_workers < 1:
            raise ValueError("minimum_workers must be at least 1")
        if self.proposal_cadence <= 0.0:
            raise ValueError("proposal_cadence must be positive")
        if not 0 <= self.priority <= 100:
            raise ValueError("priority must be between 0 and 100")
        if self.mission_timeout <= 0.0:
            raise ValueError("mission_timeout must be positive")
        if self.failure_cooldown < 0.0:
            raise ValueError("failure_cooldown must not be negative")
        if not 0.0 <= self.minimum_unit_health <= 1.0:
            raise ValueError("minimum_unit_health must be between 0 and 1")
        if self.commitment_seconds < 0.0:
            raise ValueError("commitment_seconds must not be negative")
        for name in (
            "worker_search_radius",
            "arrival_radius",
            "retreat_arrival_radius",
        ):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if not 0.0 <= self.retreat_health <= 1.0:
            raise ValueError("retreat_health must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class ReaperHarassTarget:
    key: str
    position: Point2
    last_observed_at: float | None
    age: float | None
    stale_after: float

    @property
    def is_known(self) -> bool:
        return self.last_observed_at is not None


@dataclass(frozen=True, slots=True)
class ReaperHarassAssessment:
    """Whether a Reaper raid is currently available and worth flying."""

    now: float
    reapers_available: int
    workers: int
    candidate_targets: tuple[ReaperHarassTarget, ...]
    readiness: float

    @property
    def preferred_target(self) -> ReaperHarassTarget | None:
        return next(
            (target for target in self.candidate_targets if target.is_known), None
        )

    def log_fields(self) -> dict[str, Any]:
        target = self.preferred_target
        return {
            "readiness": round(self.readiness, 2),
            "reapers_available": self.reapers_available,
            "workers": self.workers,
            "target": None if target is None else target.key,
        }


@dataclass(frozen=True, slots=True)
class ReaperHarassPlan:
    target: ReaperHarassTarget
    priority: int
    reason: str
    readiness: float

    def log_fields(self) -> dict[str, Any]:
        return {
            "target": self.target.key,
            "priority": self.priority,
            "reason": self.reason,
            "readiness": round(self.readiness, 2),
        }
