from dataclasses import dataclass, field

from sc2.ids.unit_typeid import UnitTypeId


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
