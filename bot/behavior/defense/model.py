"""Types local to base defense."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.engine.missions.models import MissionKind
from bot.world.awareness.bases import BaseAssessment, BaseSecurityLevel

_DEFAULT_DEFENDER_TYPES: frozenset[UnitTypeId] = frozenset(
    {
        UnitTypeId.MARINE,
        UnitTypeId.MARAUDER,
        UnitTypeId.REAPER,
        UnitTypeId.SIEGETANK,
        UnitTypeId.SIEGETANKSIEGED,
        UnitTypeId.BANSHEE,
    }
)


@dataclass(frozen=True, slots=True)
class DefenseConfig:
    """Thresholds for defense proposals, one per threatened base."""

    proposal_cadence: float = 5.0
    threatened_priority: int = 85
    critical_priority: int = 95
    mission_timeout: float = 120.0
    failure_cooldown: float = 10.0
    unit_types: frozenset[UnitTypeId] = field(
        default_factory=lambda: _DEFAULT_DEFENDER_TYPES
    )
    minimum_units: int = 1
    max_desired_units: int = 6
    minimum_unit_health: float = 0.3
    commitment_seconds: float = 3.0

    # --- tactics ----------------------------------------------------------
    engagement_radius: float = 25.0
    arrival_radius: float = 2.0

    mission_kind: MissionKind = MissionKind.DEFENSE

    def __post_init__(self) -> None:
        if self.proposal_cadence <= 0.0:
            raise ValueError("proposal_cadence must be positive")
        if not 0 <= self.threatened_priority <= 100:
            raise ValueError("threatened_priority must be between 0 and 100")
        if not 0 <= self.critical_priority <= 100:
            raise ValueError("critical_priority must be between 0 and 100")
        if self.critical_priority < self.threatened_priority:
            raise ValueError("critical_priority must be >= threatened_priority")
        if self.mission_timeout <= 0.0:
            raise ValueError("mission_timeout must be positive")
        if self.failure_cooldown < 0.0:
            raise ValueError("failure_cooldown must not be negative")
        if not self.unit_types:
            raise ValueError("unit_types must not be empty")
        if self.minimum_units < 1:
            raise ValueError("minimum_units must be at least 1")
        if self.max_desired_units < self.minimum_units:
            raise ValueError("max_desired_units must be >= minimum_units")
        if not 0.0 <= self.minimum_unit_health <= 1.0:
            raise ValueError("minimum_unit_health must be between 0 and 1")
        if self.commitment_seconds < 0.0:
            raise ValueError("commitment_seconds must not be negative")
        if self.engagement_radius <= 0.0 or self.arrival_radius <= 0.0:
            raise ValueError("engagement and arrival radii must be positive")


@dataclass(frozen=True, slots=True)
class ThreatenedBase:
    """One base under attack, plus what kind of attack it is.

    `air_threats`/`ground_threats` describe the composition rather than only
    its size. Nothing reads them to choose defenders yet -- they are here
    because "which units are actually useful against *this*" is the question
    `UnitRequirement.type_desirability` exists to answer, and the answer has
    to be assessed somewhere before a planner can state it.
    """

    base: BaseAssessment
    air_threats: int
    ground_threats: int

    @property
    def base_id(self) -> str:
        return self.base.base_id

    @property
    def is_critical(self) -> bool:
        return self.base.security is BaseSecurityLevel.CRITICAL

    @property
    def target(self) -> Point2:
        return self.base.nearest_threat_position or self.base.position

    @property
    def gap(self) -> float:
        """How far the threat outweighs what is already defending the base."""

        return self.base.threat_score - self.base.protection_score


@dataclass(frozen=True, slots=True)
class DefenseAssessment:
    """Which of our bases are in trouble, and how badly."""

    now: float
    threatened: tuple[ThreatenedBase, ...]
    held_bases: int
    pressure: int

    @property
    def under_attack(self) -> bool:
        return bool(self.threatened)

    def log_fields(self) -> dict[str, Any]:
        return {
            "held_bases": self.held_bases,
            "threatened_bases": [item.base_id for item in self.threatened],
            "critical_bases": [
                item.base_id for item in self.threatened if item.is_critical
            ],
            "pressure": self.pressure,
            "air_threats": sum(item.air_threats for item in self.threatened),
            "ground_threats": sum(item.ground_threats for item in self.threatened),
        }


@dataclass(frozen=True, slots=True)
class DefensePlan:
    """The answer for one threatened base: go there, with this many, now."""

    base: ThreatenedBase
    desired_units: int
    priority: int
    reason: str

    @property
    def target(self) -> Point2:
        return self.base.target

    def log_fields(self) -> dict[str, Any]:
        return {
            "base_id": self.base.base_id,
            "desired_units": self.desired_units,
            "priority": self.priority,
            "reason": self.reason,
            "critical": self.base.is_critical,
        }
