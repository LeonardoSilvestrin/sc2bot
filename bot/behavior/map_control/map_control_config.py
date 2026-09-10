from dataclasses import dataclass, field

from sc2.ids.unit_typeid import UnitTypeId


@dataclass(frozen=True, slots=True)
class MapControlPlannerConfig:
    """Conservative thresholds for a persistent map-presence squad."""

    start_after: float = 0.0
    proposal_cadence: float = 15.0
    priority: int = 40
    mission_timeout: float = 3600.0
    failure_cooldown: float = 15.0
    unit_types: frozenset[UnitTypeId] = field(
        default_factory=lambda: frozenset({UnitTypeId.MARINE})
    )
    force_ratio: float = 0.2
    minimum_force_size: int = 6
    # Optional fixed override retained for experiments/config compatibility.
    desired_units: int | None = None
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
        if not 0.0 < self.force_ratio < 1.0:
            raise ValueError("force_ratio must be between 0 and 1")
        if self.minimum_force_size < 1:
            raise ValueError("minimum_force_size must be positive")
        if self.desired_units is not None and self.desired_units < 1:
            raise ValueError("desired_units must be positive when provided")
        if not 0.0 <= self.minimum_unit_health <= 1.0:
            raise ValueError("minimum_unit_health must be between 0 and 1")
        if self.commitment_seconds < 0.0:
            raise ValueError("commitment_seconds must not be negative")
