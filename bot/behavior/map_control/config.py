from dataclasses import dataclass, field

from sc2.ids.unit_typeid import UnitTypeId


@dataclass(frozen=True, slots=True)
class MapControlPlannerConfig:
    """Conservative thresholds for a persistent map-presence squad."""

    start_after: float = 180.0
    proposal_cadence: float = 15.0
    priority: int = 40
    mission_timeout: float = 3600.0
    failure_cooldown: float = 15.0
    unit_types: frozenset[UnitTypeId] = field(
        default_factory=lambda: frozenset({UnitTypeId.MARINE})
    )
    desired_units: int = 3
    minimum_units: int = 2
    reserve_units: int = 3
    minimum_unit_health: float = 0.7
    commitment_seconds: float = 1.0

    def __post_init__(self) -> None:
        if self.start_after < 0.0:
            raise ValueError("start_after must not be negative")
        if self.proposal_cadence <= 0.0:
            raise ValueError("proposal_cadence must be positive")
        if not 0 <= self.priority <= 100:
            raise ValueError("priority must be between 0 and 100")
        if self.mission_timeout <= 0.0:
            raise ValueError("mission_timeout must be positive")
        if self.failure_cooldown < 0.0:
            raise ValueError("failure_cooldown must not be negative")
        if not self.unit_types:
            raise ValueError("unit_types must not be empty")
        if self.minimum_units < 1 or self.minimum_units > self.desired_units:
            raise ValueError("expected 1 <= minimum_units <= desired_units")
        if self.reserve_units < 0:
            raise ValueError("reserve_units must not be negative")
        if not 0.0 <= self.minimum_unit_health <= 1.0:
            raise ValueError("minimum_unit_health must be between 0 and 1")
        if self.commitment_seconds < 0.0:
            raise ValueError("commitment_seconds must not be negative")
