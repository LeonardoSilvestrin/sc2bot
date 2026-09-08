from dataclasses import dataclass, field

from sc2.ids.unit_typeid import UnitTypeId


@dataclass(frozen=True, slots=True)
class IntelPlannerConfig:
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
